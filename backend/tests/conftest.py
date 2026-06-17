"""Shared pytest fixtures for all test layers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.integrations.google import GoogleHandler
from app.models.review import Platform

# ---------------------------------------------------------------------------
# sys.path — make app.* and pipelines.* importable from every test file
# ---------------------------------------------------------------------------
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for _p in (str(BACKEND), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Test database URL — falls back to the dev DB so tests can run without setup
# ---------------------------------------------------------------------------
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai_test",
)

# ---------------------------------------------------------------------------
# Session-scoped engine — created once, shared across all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    # Ensure pgvector extension exists in the test DB
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Function-scoped DB session — each test runs inside a rolled-back transaction
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(db_engine):
    """Yield a DB session. Every change is rolled back after the test — no cleanup needed."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# FastAPI TestClient — get_db dependency overridden with the test session
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(db):
    from app.database.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Create a global instance of GoogleHandler()
# ---------------------------------------------------------------------------
@pytest.fixture()
def handlingGoogleReview():
    return GoogleHandler()


# ---------------------------------------------------------------------------
# Reusable ReviewCreate factory helper
# ---------------------------------------------------------------------------


def make_review_create(
    *,
    platform: Platform = Platform.google,
    platform_id: str = "test-platform-id",
    business_id: str = "biz-test",
    business_name: str | None = "Test Business",
    content: str = "Great experience overall.",
    rating: float | None = 4.0,
    author: str | None = "Test User",
):
    from app.schemas.review_schema import ReviewCreate

    return ReviewCreate(
        platform=platform,
        platform_id=platform_id,
        business_id=business_id,
        business_name=business_name,
        content=content,
        rating=rating,
        author=author,
    )
