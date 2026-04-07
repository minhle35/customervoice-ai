"""Database Configuration and Session Management"""

__all__ = ["get_db", "get_session", "SessionDep", "init_db"]

import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base  # noqa: F401 – imported so Alembic can discover models

logger = logging.getLogger(__name__)

# Initialised by init_db() at app startup — not at import time
engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def init_db() -> None:
    """Initialise database engine, verify connection, and enable pgvector.

    Called once from the FastAPI lifespan so failures surface with context
    rather than crashing silently at import time.
    """
    global engine, SessionLocal

    settings = get_settings()
    logger.info(
        "Connecting to database %s:%s/%s",
        settings.db.host,
        settings.db.port,
        settings.db.name,
    )

    engine = create_engine(
        settings.db.url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        logger.info("pgvector extension ready")

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("Database initialised")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    if SessionLocal is None:
        raise RuntimeError("Database not initialised — was init_db() called?")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for DB sessions outside FastAPI (pipelines, Celery tasks).

    Usage:
        with get_session() as db:
            ...
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialised — was init_db() called?")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


SessionDep = Annotated[Session, Depends(get_db)]
