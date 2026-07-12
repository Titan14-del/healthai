from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Patient(Base):
    __tablename__ = "patients"

    id       = Column(Integer, primary_key=True, index=True)
    name     = Column(String, nullable=False)
    email    = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    age      = Column(Integer, nullable=True)
    language = Column(String, default='en', nullable=False, server_default='en')

    diagnoses = relationship("Diagnosis", back_populates="patient", cascade="all, delete-orphan")

class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False)
    type       = Column(String, nullable=False)   # "symptom" | "image"
    query      = Column(Text, nullable=False)
    title        = Column(String, nullable=True)
    urgency      = Column(String, nullable=True)
    conditions   = Column(Text, nullable=True)
    advice       = Column(Text, nullable=True)
    analysis     = Column(Text, nullable=True)     # raw text for image results
    conversation = Column(Text, nullable=True)     # JSON string of full chat messages
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="diagnoses")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id         = Column(Integer, primary_key=True, index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Integer, default=0, nullable=False)  # boolean 0/1
    created_at = Column(DateTime, default=_utcnow)

    patient = relationship("Patient")
