import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
import models

SECRET_KEY  = os.getenv("SECRET_KEY", "change-this-secret-in-production")
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7   # 1 week

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login", auto_error=False)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(patient_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": str(patient_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_patient(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> models.Patient:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload    = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        patient_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Patient not found")
    return patient

def get_optional_patient(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[models.Patient]:
    """Returns the patient if a valid token is present, otherwise None (guest mode)."""
    if not token:
        return None
    try:
        payload    = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        patient_id = int(payload["sub"])
        return db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    except Exception:
        return None
