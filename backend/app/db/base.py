"""SQLAlchemy engine + session, built from DATABASE_URL.

Works identically against PostgreSQL (production) and SQLite (dev fallback);
models only use portable column types (JSON instead of Postgres ARRAY, etc.)
so the same migrations run on both.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..core.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = get_settings().database_url
    kwargs = {}
    if url.startswith("sqlite"):
        # FastAPI serves each request in its own thread; SQLite needs this flag.
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI dependency: one session per request, always closed."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
