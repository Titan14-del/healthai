from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, Request
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from sqlalchemy.orm import Session
from sqlalchemy import text
import traceback
import httpx
import asyncio
from contextlib import asynccontextmanager


from database import engine, get_db, DATABASE_URL
import models
import schemas
from auth import (
    hash_password, verify_password, create_token,
    get_current_patient, get_optional_patient
)
from symptom_checker import analyze_symptoms, chat_analyze, generate_title
import json as _json
from image_analyzer import analyze_image_initial, image_chat_analyze

# ── DB setup & migration ─────────────────────────────────
models.Base.metadata.create_all(bind=engine)

# Schema migrations for columns added after initial deploy
_MIGRATIONS = [
    "ALTER TABLE patients  ADD COLUMN IF NOT EXISTS language     VARCHAR NOT NULL DEFAULT 'en'",
    "ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS title        VARCHAR",
    "ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS conversation TEXT",
]
try:
    with engine.connect() as conn:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists
except Exception as e:
    print(f"[DB] Migration skipped: {e}")
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
                print("Keep-alive ping sent")
        except Exception as e:
            print(f"Keep-alive error: {e}")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

class SymptomRequest(BaseModel):
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

class ImageChatRequest(BaseModel):
    messages:       List[ChatMessage] = Field(min_length=1, max_length=MAX_CHAT_MESSAGES)
    language:       str = 'en'
    exchange_count: int = 0
    original_query: str = Field(default='', max_length=MAX_CHAT_MESSAGE_LENGTH)

class ChatRequest(BaseModel):
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
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(
        os.path.join(base_dir, "HealthAi.html"),
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
        print(f"[REGISTER] Patient saved successfully — id={patient.id} email={patient.email}")
        return schemas.TokenResponse(access_token=create_token(patient.id))
    except Exception as e:
        db.rollback()
        print(f"[REGISTER] Failed to save patient: {e}")
        print("FULL ERROR:", traceback.format_exc())
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
        print("FULL ERROR:", traceback.format_exc())
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
        print("FULL ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

# ── Image analysis ───────────────────────────────────────

@app.post("/analyze-image", response_model=ImageResponse)
async def analyze_image_endpoint(
    file:            UploadFile = File(...),
    additional_info: str = Form(default=""),
    language:        str = Form(default="en"),
    db:      Session = Depends(get_db),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    """
    Initial image upload. Describes what the AI sees and asks ONE follow-up question.
    The frontend then routes subsequent patient replies to /image-chat until diagnosis.
    """
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
        print("FULL ERROR:", traceback.format_exc())
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
        print("FULL ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="An internal error occurred. Please try again.")

# ── Patient history ──────────────────────────────────────

@app.get("/history", response_model=List[schemas.DiagnosisOut])
def history(
    patient: models.Patient = Depends(get_current_patient),
    db:      Session = Depends(get_db),
):
    return (
        db.query(models.Diagnosis)
        .filter(models.Diagnosis.patient_id == patient.id)
        .order_by(models.Diagnosis.created_at.desc())
        .all()
    )

@app.delete("/history", status_code=204)
def delete_history(
    patient: models.Patient = Depends(get_current_patient),
    db:      Session = Depends(get_db),
):
    db.query(models.Diagnosis).filter(models.Diagnosis.patient_id == patient.id).delete()
    db.commit()
