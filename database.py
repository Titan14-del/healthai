import os
from urllib.parse import urlparse
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./healthai.db")

# Supabase (and some other providers) return "postgres://" which SQLAlchemy
# requires to be "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

is_postgres = DATABASE_URL.startswith("postgresql")

if is_postgres:
    # Ensure SSL is required
    if "sslmode=" not in DATABASE_URL:
        sep = "&" if "?" in DATABASE_URL else "?"
        DATABASE_URL += f"{sep}sslmode=require"
    connect_args = {"sslmode": "require"}
    # Supabase transaction-mode pooler (port 6543) doesn't support prepared statements
    parsed = urlparse(DATABASE_URL)
    is_pooler = parsed.port == 6543
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        **({"execution_options": {"no_parameters": True}} if is_pooler else {}),
    )
    print(f"[DB] Connecting to PostgreSQL host={parsed.hostname} port={parsed.port} db={parsed.path.lstrip('/')} pooler={is_pooler}")
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    print("[DB] Using SQLite (no DATABASE_URL set)")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
