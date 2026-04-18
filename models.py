from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

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
    urgency    = Column(String, nullable=True)
    conditions = Column(Text, nullable=True)
    advice     = Column(Text, nullable=True)
    analysis   = Column(Text, nullable=True)      # raw text for image results
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient", back_populates="diagnoses")
