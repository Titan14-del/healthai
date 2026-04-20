from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# ── Auth ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str
    email:    EmailStr
    password: str
    age:      Optional[int] = None

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"

# ── Patient ───────────────────────────────────────────────

class PatientOut(BaseModel):
    id:       int
    name:     str
    email:    str
    age:      Optional[int]
    language: str = 'en'

    model_config = {"from_attributes": True}

class LanguageUpdate(BaseModel):
    language: str

# ── Diagnosis ─────────────────────────────────────────────

class DiagnosisOut(BaseModel):
    id:           int
    type:         str
    query:        str
    title:        Optional[str] = None
    urgency:      Optional[str] = None
    conditions:   Optional[str] = None
    advice:       Optional[str] = None
    analysis:     Optional[str] = None
    conversation: Optional[str] = None
    created_at:   datetime

    model_config = {"from_attributes": True}
