from dotenv import load_dotenv
load_dotenv()

import os

import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from sqlalchemy.orm import Session
from sqlalchemy import text
import traceback
import httpx
import asyncio
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

logging.basicConfig(level=logging.INFO, format="%(levelname)s:\t%(name)s - %(message)s")
logger = logging.getLogger(__name__)
from database import engine, get_db, DATABASE_URL
import models
import schemas
from auth import (
    hash_password, verify_password, create_token,
    get_current_patient, get_optional_patient
)
from symptom_checker import analyze_symptoms, chat_analyze, generate_title, LANGUAGE_NAMES, LANGUAGE_NAMES
import json as _json
from image_analyzer import analyze_image_initial, image_chat_analyze
from email_service import send_reset_email

# ── DB setup & migration ─────────────────────────────────
models.Base.metadata.create_all(bind=engine)

# Schema migrations for columns added after initial deploy
_MIGRATIONS = [
    "ALTER TABLE patients  ADD COLUMN IF NOT EXISTS language     VARCHAR NOT NULL DEFAULT 'en'",
    "ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS title        VARCHAR",
    "ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS conversation TEXT",
    "ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS analysis     TEXT",
    """CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id         SERIAL PRIMARY KEY,
        patient_id INTEGER NOT NULL REFERENCES patients(id),
        token_hash VARCHAR NOT NULL,
        expires_at TIMESTAMP NOT NULL,
        used       INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]
try:
    with engine.connect() as conn:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as e:
                # "already exists" / "duplicate column" are expected (idempotent re-runs);
                # surface anything else so real migration failures aren't hidden.
                msg = str(e).lower()
                if "exist" not in msg and "duplicate" not in msg:
                    logger.warning(f"[DB] Migration statement failed: {e}")
except Exception as e:
    logger.warning(f"[DB] Migration skipped: {e}")
async def keep_alive():
    import os
    app_url = os.getenv("APP_URL")
    if not app_url:
        return  # No URL configured, skip keep-alive
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(app_url)
                logger.info("Keep-alive ping sent")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")
        await asyncio.sleep(840)

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(keep_alive())
    yield

class ForceHTTPSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("x-forwarded-proto") == "http":
            https_url = str(request.url).replace("http://", "https://", 1)
            return RedirectResponse(url=https_url, status_code=301)
        return await call_next(request)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="HealthAI API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Restrict CORS to the origins listed in ALLOWED_ORIGINS (comma-separated).
# Falls back to "*" only when the var is unset, to keep local development frictionless.
_allowed = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in _allowed.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allowed_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ForceHTTPSMiddleware)

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/png":  "image/png",
    "image/gif":  "image/gif",
    "image/webp": "image/webp",
}

MAX_SYMPTOMS_LENGTH = 2000
MAX_CHAT_MESSAGE_LENGTH = 2000
MAX_CHAT_MESSAGES = 40

# ── Request/Response models ───────────────────────────────

class _LangValidatedModel(BaseModel):
    """Base for request models that carry a `language` field, restricting it to
    the languages the prompts actually support (otherwise they silently fall
    back to English)."""
    @field_validator("language", check_fields=False)
    @classmethod
    def _validate_language(cls, v: str) -> str:
        if v not in LANGUAGE_NAMES:
            raise ValueError(
                f"Unsupported language '{v}'. Supported: {', '.join(sorted(LANGUAGE_NAMES))}"
            )
        return v

class SymptomRequest(_LangValidatedModel):
    symptoms: str = Field(min_length=1, max_length=MAX_SYMPTOMS_LENGTH)
    age:      Optional[int]  = None
    gender:   Optional[str]  = None
    language: str            = 'en'

class SymptomResponse(BaseModel):
    urgency:    str
    conditions: str
    advice:     str

class ImageResponse(BaseModel):
    type: str
    text: str

class ChatMessage(BaseModel):
    role:    Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)

class ImageChatRequest(_LangValidatedModel):
    messages:       List[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    language:       str = 'en'
    exchange_count: int = 0
    original_query: str = Field(default='', max_length=MAX_CHAT_MESSAGE_LENGTH)

class ChatRequest(_LangValidatedModel):
    messages: List[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    age:      Optional[int] = None
    gender:   Optional[str] = None
    language: str           = 'en'

class ChatResponse(BaseModel):
    type:       str
    text:       Optional[str] = None
    urgency:    Optional[str] = None
    conditions: Optional[str] = None
    advice:     Optional[str] = None
    title:      Optional[str] = None

# ── Health check ─────────────────────────────────────────

@app.get("/")
def home():
    return {"message": "HealthAI is running!"}

@app.get("/db-status")
def db_status(db: Session = Depends(get_db)):
    is_postgres = DATABASE_URL.startswith("postgresql")
    db_type = "PostgreSQL" if is_postgres else "SQLite (fallback - data will not persist!)"
    patient_count = db.query(models.Patient).count()
    return {
        "database": db_type,
        "patient_count": patient_count,
        "connected_to_supabase": is_postgres,
    }

@app.get("/app")
def serve_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(
        os.path.join(base_dir, "HealthAi.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/reset-password")
def serve_reset_page():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(
        os.path.join(base_dir, "reset-password.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )

# ── Auth ─────────────────────────────────────────────────

@app.post("/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, req: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.Patient).filter(models.Patient.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    patient = models.Patient(
        name     = req.name,
        email    = req.email,
        password = hash_password(req.password),
        age      = req.age,
    )
    try:
        db.add(patient)
        db.commit()
        db.refresh(patient)
        logger.info(f"[REGISTER] Patient saved successfully — id={patient.id} email={patient.email}")
        return schemas.TokenResponse(access_token=create_token(patient.id))
    except Exception as e:
        db.rollback()
        logger.error(f"[REGISTER] Failed to save patient: {e}")
        logger.error(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/login", response_model=schemas.TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, req: schemas.LoginRequest, db: Session = Depends(get_db)):
    patient = db.query(models.Patient).filter(models.Patient.email == req.email).first()
    if not patient or not verify_password(req.password, patient.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return schemas.TokenResponse(access_token=create_token(patient.id))

@app.get("/me", response_model=schemas.PatientOut)
def me(patient: models.Patient = Depends(get_current_patient)):
    return patient

@app.patch("/me/language", response_model=schemas.PatientOut)
def update_language(
    update:  schemas.LanguageUpdate,
    patient: models.Patient = Depends(get_current_patient),
    db:      Session = Depends(get_db),
):
    patient.language = update.language
    db.commit()
    db.refresh(patient)
    return patient

# ── Password reset ─────────────────────────────────────

@app.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, req: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    patient = db.query(models.Patient).filter(models.Patient.email == req.email).first()
    if not patient:
        return JSONResponse({"message": "If that email is registered, a reset link has been sent."})

    # Invalidate any previously issued, still-unused tokens for this patient.
    db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.patient_id == patient.id,
        models.PasswordResetToken.used == 0,
    ).update({"used": 1})

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = _utcnow() + timedelta(hours=1)

    db.add(models.PasswordResetToken(
        patient_id=patient.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    db.commit()

    try:
        send_reset_email(patient.email, raw_token)
    except Exception as e:
        logger.error(f"Failed to send reset email: {e}")

    return JSONResponse({"message": "If that email is registered, a reset link has been sent."})


@app.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(request: Request, req: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(req.token.encode()).hexdigest()
    now = _utcnow()

    reset_token = (
        db.query(models.PasswordResetToken)
        .filter(
            models.PasswordResetToken.token_hash == token_hash,
            models.PasswordResetToken.expires_at > now,
            models.PasswordResetToken.used == 0,
        )
        .first()
    )

    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    patient = db.query(models.Patient).filter(models.Patient.id == reset_token.patient_id).first()
    if not patient:
        raise HTTPException(status_code=400, detail="Patient not found")

    patient.password = hash_password(req.new_password)
    reset_token.used = 1
    db.commit()

    return JSONResponse({"message": "Password reset successfully."})


# ── Conversational symptom intake ────────────────────────

@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(
    request: ChatRequest,
    db:      Session = Depends(get_db),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    try:
        msgs   = [{"role": m.role, "content": m.content} for m in request.messages]
        result = chat_analyze(
            messages=msgs,
            age=request.age,
            gender=request.gender,
            language=request.language,
        )
        if result["type"] == "diagnosis":
            try:
                title = generate_title(msgs, result.get("conditions", ""))
            except Exception:
                # Title generation is non-critical; fall back to first user message
                title = next((m["content"] for m in msgs if m.get("role") == "user"), "Consultation")[:50]
            result["title"] = title
            first_user = next((m["content"] for m in msgs if m.get("role") == "user"), "")
            if patient:
                db.add(models.Diagnosis(
                    patient_id   = patient.id,
                    type         = "symptom",
                    query        = first_user,
                    title        = title,
                    urgency      = result.get("urgency"),
                    conditions   = result.get("conditions"),
                    advice       = result.get("advice"),
                    conversation = _json.dumps(msgs),
                ))
                db.commit()
        return ChatResponse(**result)
    except Exception as e:
        db.rollback()
        logger.error(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

# ── Symptom analysis ─────────────────────────────────────

@app.post("/analyze", response_model=SymptomResponse)
def analyze(
    request: SymptomRequest,
    db:      Session = Depends(get_db),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    try:
        result = analyze_symptoms(
            symptoms=request.symptoms,
            age=request.age,
            gender=request.gender,
            language=request.language,
        )
        if patient:
            db.add(models.Diagnosis(
                patient_id = patient.id,
                type       = "symptom",
                query      = request.symptoms,
                urgency    = result.get("urgency"),
                conditions = result.get("conditions"),
                advice     = result.get("advice"),
            ))
            db.commit()
        return SymptomResponse(**result)
    except Exception as e:
        db.rollback()
        logger.error(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

# ── Image analysis ───────────────────────────────────────

@app.post("/analyze-image", response_model=ImageResponse)
async def analyze_image_endpoint(
    file:            UploadFile = File(...),
    additional_info: str = Form(default=""),
    language:        str = Form(default="en"),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    """
    Initial image upload. Describes what the AI sees and asks ONE follow-up question.
    The frontend then routes subsequent patient replies to /image-chat until diagnosis.
    """
    if language not in LANGUAGE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unsupported language '{language}'. Supported: {', '.join(LANGUAGE_NAMES)}")
    if len(additional_info) > MAX_SYMPTOMS_LENGTH:
        raise HTTPException(status_code=400, detail=f"Additional info too long ({len(additional_info)} chars). Max: {MAX_SYMPTOMS_LENGTH}")

    try:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload a JPEG, PNG, GIF or WEBP image.")

        image_bytes = await file.read()
        if len(image_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large. Please upload an image smaller than 5MB.")

        result = analyze_image_initial(
            image_bytes=image_bytes,
            image_type=ALLOWED_IMAGE_TYPES[file.content_type],
            additional_info=additional_info,
            language=language,
        )
        return ImageResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")


@app.post("/image-chat", response_model=ChatResponse)
def image_chat_endpoint(
    request: ImageChatRequest,
    db:      Session = Depends(get_db),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    """
    Continue the conversation that started with an image upload.
    Saves to DB and returns title only when a final diagnosis is reached.
    """
    try:
        msgs   = [{"role": m.role, "content": m.content} for m in request.messages]
        result = image_chat_analyze(
            messages=msgs,
            language=request.language,
            exchange_count=request.exchange_count,
        )

        if result["type"] == "diagnosis":
            try:
                title = generate_title(msgs, result.get("conditions", ""))
            except Exception:
                title = (request.original_query or "[Image consultation]")[:50]
            result["title"] = title
            if patient:
                db.add(models.Diagnosis(
                    patient_id   = patient.id,
                    type         = "image",
                    query        = request.original_query or "[Image uploaded]",
                    title        = title,
                    urgency      = result.get("urgency"),
                    conditions   = result.get("conditions"),
                    advice       = result.get("advice"),
                    conversation = _json.dumps(msgs),
                ))
                db.commit()

        return ChatResponse(**result)

    except Exception as e:
        db.rollback()
        logger.error(f"FULL ERROR: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

# ── Patient history ──────────────────────────────────────

@app.get("/history", response_model=List[schemas.DiagnosisOut])
def history(
    limit:   int = 50,
    offset:  int = 0,
    patient: models.Patient = Depends(get_current_patient),
    db:      Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return (
        db.query(models.Diagnosis)
        .filter(models.Diagnosis.patient_id == patient.id)
        .order_by(models.Diagnosis.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

@app.delete("/history", status_code=204)
def delete_history(
    patient: models.Patient = Depends(get_current_patient),
    db:      Session = Depends(get_db),
):
    db.query(models.Diagnosis).filter(models.Diagnosis.patient_id == patient.id).delete()
    db.commit()
