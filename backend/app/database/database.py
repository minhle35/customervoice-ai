from collections.abc import Generator

from pgvector.sqlalchemy import Vector  # registers Vector type with SQLAlchemy  # noqa: F401
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base  # noqa: F401 – imported so Alembic can discover models

_s = get_settings()
engine = create_engine(
    _s.db.url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)


# Ensure the pgvector extension exists before any table is created
@event.listens_for(engine, "connect")
def _enable_pgvector(dbapi_conn, _connection_record):
    with dbapi_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    dbapi_conn.commit()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
