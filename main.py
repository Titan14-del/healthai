from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import text
import traceback
import httpx
import asyncio
from contextlib import asynccontextmanager


from database import engine, get_db
import models
import schemas
from auth import (
    hash_password, verify_password, create_token,
    get_current_patient, get_optional_patient
)
from symptom_checker import analyze_symptoms, chat_analyze, generate_title
import json as _json
from image_analyzer import analyze_image

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
    await asyncio.sleep(60)
    while True:
        try:
            async with httpx.AsyncClient() as client:
                await client.get("https://healthai-qoem.onrender.com/")
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

app = FastAPI(title="HealthAI API", lifespan=lifespan)

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

# ── Request/Response models ───────────────────────────────

class SymptomRequest(BaseModel):
    symptoms: str
    age:      Optional[int]  = None
    gender:   Optional[str]  = None
    language: str            = 'en'

class SymptomResponse(BaseModel):
    urgency:    str
    conditions: str
    advice:     str

class ImageResponse(BaseModel):
    analysis: str

class ChatMessage(BaseModel):
    role:    str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
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
@app.get("/app")
def serve_app():
    import os
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return FileResponse(os.path.join(base_dir, "HealthAi.html"))

# ── Auth ─────────────────────────────────────────────────

@app.post("/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.Patient).filter(models.Patient.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    patient = models.Patient(
        name     = req.name,
        email    = req.email,
        password = hash_password(req.password),
        age      = req.age,
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return schemas.TokenResponse(access_token=create_token(patient.id))

@app.post("/login", response_model=schemas.TokenResponse)
def login(req: schemas.LoginRequest, db: Session = Depends(get_db)):
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
        print("FULL ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

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
        print("FULL ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

# ── Image analysis ───────────────────────────────────────

@app.post("/analyze-image", response_model=ImageResponse)
async def analyze_image_endpoint(
    file:            UploadFile = File(...),
    additional_info: str = Form(default=""),
    language:        str = Form(default="en"),
    db:      Session = Depends(get_db),
    patient: Optional[models.Patient] = Depends(get_optional_patient),
):
    try:
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload a JPEG, PNG, GIF or WEBP image.")

        image_bytes = await file.read()
        if len(image_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Image too large. Please upload an image smaller than 5MB.")

        result = analyze_image(
            image_bytes=image_bytes,
            image_type=ALLOWED_IMAGE_TYPES[file.content_type],
            additional_info=additional_info,
            language=language,
        )
        if patient:
            db.add(models.Diagnosis(
                patient_id = patient.id,
                type       = "image",
                query      = additional_info or "[Image uploaded]",
                analysis   = result,
            ))
            db.commit()
        return ImageResponse(analysis=result)

    except HTTPException:
        raise
    except Exception as e:
        print("FULL ERROR:", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))

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
