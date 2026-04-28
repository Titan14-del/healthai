import os
from urllib.parse import urlparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Supabase (and some other providers) return "postgres://" which SQLAlchemy
# requires to be "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

is_postgres = DATABASE_URL.startswith("postgresql")

def _make_postgres_engine(url):
    parsed = urlparse(url)
    is_pooler = parsed.port == 6543
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url += f"{sep}sslmode=require"
    engine = create_engine(
        url,
        connect_args={"sslmode": "require"},
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        **({"execution_options": {"no_parameters": True}} if is_pooler else {}),
    )
    # Test the connection immediately
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"[DB] Connected to PostgreSQL host={parsed.hostname} port={parsed.port} db={parsed.path.lstrip('/')} pooler={is_pooler}")
    return engine

def _make_sqlite_engine():
    url = "sqlite:///./healthai.db"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    print("[DB] Using SQLite fallback")
    return engine

if is_postgres:
    try:
        engine = _make_postgres_engine(DATABASE_URL)
    except Exception as e:
        print(f"[DB] PostgreSQL connection failed: {e}")
        print("[DB] Falling back to SQLite")
        engine = _make_sqlite_engine()
else:
    print("[DB] No DATABASE_URL set")
    engine = _make_sqlite_engine()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
