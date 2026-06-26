from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List
from datetime import datetime

# ── Auth ──────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str
    email:    EmailStr
    password: str = Field(min_length=8, max_length=128)
    age:      Optional[int] = None

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character (!@#$%^&*...)")
        return v

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

# ── Password reset ─────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character (!@#$%^&*...)")
        return v

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
