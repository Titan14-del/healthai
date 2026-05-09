import os
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Supabase (and some other providers) return "postgres://" which SQLAlchemy
# requires to be "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

is_postgres = DATABASE_URL.startswith("postgresql")

def _make_postgres_engine(url):
    parsed = urlparse(url)
    port = parsed.port

    # Add SSL if not already in URL
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}sslmode=require"

    # Port 6543 = transaction pooler — use NullPool + no prepared statements
    # Port 5432 on pooler host = session pooler — use NullPool
    # Port 5432 on db.*.supabase.co = direct connection — use standard pool
    is_transaction_pooler = port == 6543
    is_session_pooler = port == 5432 and "pooler.supabase.com" in (parsed.hostname or "")
    use_null_pool = is_transaction_pooler or is_session_pooler

    if use_null_pool:
        engine = create_engine(
            url,
            connect_args={"sslmode": "require", "options": "-c statement_cache_size=0"},
            poolclass=NullPool,
        )
        mode = "transaction pooler" if is_transaction_pooler else "session pooler"
    else:
        engine = create_engine(
            url,
            connect_args={"sslmode": "require"},
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        mode = "direct connection"

    # Test the connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    logger.info(f"[DB] Connected to PostgreSQL via {mode} — host={parsed.hostname} port={port}")
    return engine

def _make_sqlite_engine():
    engine = create_engine("sqlite:///./healthai.db", connect_args={"check_same_thread": False})
    logger.info("[DB] Using SQLite fallback")
    return engine

# NEW CODE (No fallback allowed)
if is_postgres:
    # This will now throw a real error if the connection fails
    engine = _make_postgres_engine(DATABASE_URL)
else:
    raise ValueError("[DB] CRITICAL: No PostgreSQL DATABASE_URL found. Check your Railway variables.")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
