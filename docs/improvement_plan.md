# CustomerVoice AI — Backend Improvement Plan

**Date:** 2026-04-06
**Branch:** feat/rag-chat-ui
**Scope:** backend/, pipelines/, ai/ — Python service layer only

This document is an actionable engineering plan, not a generic checklist. Every step includes the exact file to change, the current code, the target pattern, why it matters, effort (S = < 1 h / M = half day / L = 1–2 days), and dependencies.

---

## Phase 1 — Critical (Security + Observability)

These four items must be done before any public or staging deployment. None require architectural changes. Combined effort is under 3 hours.

---

### 1.1 Fix SerpAPI error leak in routes_integrations.py

**File:** `backend/app/api/routes_integrations.py`

**What it matters:**
`detail=str(exc)` passes the raw `RuntimeError` message from `SerpApiService` directly to the HTTP response body. `RuntimeError` messages from API wrapper libraries routinely contain the upstream API response body, which can include rate-limit messages with quota metadata, internal service identifiers, and occasionally reflected request parameters. This is an information-disclosure vulnerability.

**Current code (line 37–40):**
```python
try:
    return SerpApiService().search_places(query=q, country=country)
except RuntimeError as exc:
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
    ) from exc
```

**Target pattern:**
```python
import logging

logger = logging.getLogger(__name__)

try:
    return SerpApiService().search_places(query=q, country=country)
except RuntimeError as exc:
    logger.warning("SerpAPI search failed: %s", exc, extra={"query": q, "country": country})
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Upstream search service is unavailable. Please try again later.",
    ) from exc
```

The `logger.warning` line goes to your log infrastructure (visible internally); the `detail` string goes to the client (generic, safe).

**Effort:** S
**Dependencies:** None (logging module is in stdlib)

---

### 1.2 Add logger.exception() to the catch-all 500 handler in main.py

**File:** `backend/app/main.py`

**Why it matters:**
The current handler swallows every unhandled exception without writing anything to a log. When a 500 fires in production, you have no stack trace, no exception type, no request context — nothing to diagnose with. This is the single highest-impact observability gap.

**Current code (lines 46–51):**
```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
```

**Target pattern:**
```python
import logging

logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
```

`logger.exception()` automatically attaches the current exception's traceback to the log record. The client response is unchanged — the traceback stays internal.

**Effort:** S
**Dependencies:** None

---

### 1.3 Add API key authentication middleware

**File (new):** `backend/app/api/dependencies.py`
**Files modified:** `backend/app/config.py`, `backend/app/api/routes_reviews.py`, `backend/app/api/routes_chat.py`, `backend/app/api/routes_integrations.py`

**Why it matters:**
Every endpoint is currently unauthenticated. `POST /api/chat` runs LLM queries against OpenRouter at your cost. `GET /api/integrations/google/search` proxies SerpAPI requests at your API quota's expense. `POST /api/integrations/{platform}` enqueues Celery tasks with no authorization. An `X-API-Key` header dependency is a 15-line stopgap that locks down all surfaces immediately while JWT auth is built.

**Current state:** No auth dependency exists anywhere.

**Target pattern — new file `backend/app/api/dependencies.py`:**
```python
import logging
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

logger = logging.getLogger(__name__)

_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(_api_key_scheme)) -> None:
    """Dependency: reject requests that don't carry a valid X-API-Key header."""
    if not api_key or api_key != settings.api_secret_key:
        logger.warning("Rejected request with invalid or missing API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
```

**Add `api_secret_key` to `backend/app/config.py`:**
```python
import secrets

class Settings(BaseSettings):
    ...
    api_secret_key: str = secrets.token_hex(32)  # override via API_SECRET_KEY env var
```

**Apply the dependency on each router (example for routes_chat.py):**
```python
# Before:
router = APIRouter(prefix="/api/chat", tags=["chat"])

# After:
from app.api.dependencies import require_api_key

router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(require_api_key)],
)
```

Apply the same `dependencies=[Depends(require_api_key)]` to the routers in `routes_reviews.py` and `routes_integrations.py`.

**Effort:** S
**Dependencies:** 2.2 (api_secret_key field in Settings)

---

### 1.4 Move CORS origins to Settings

**Files:** `backend/app/config.py`, `backend/app/main.py`

**Why it matters:**
`allow_origins=["http://localhost:3000"]` is hardcoded in `main.py`. This means the frontend cannot make credentialed requests from any staging or production domain without a code change and redeploy. CORS configuration is environment data, not source code.

**Current code in `main.py` (lines 28–34):**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Target pattern — add to `backend/app/config.py`:**
```python
class Settings(BaseSettings):
    ...
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
```

Set in `.env` for staging/production:
```
CORS_ALLOWED_ORIGINS=["https://app.customervoice.ai","https://staging.customervoice.ai"]
```

**Update `main.py`:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Effort:** S
**Dependencies:** None

---

## Phase 2 — Settings Refactor

The current `Settings` class is a flat bag of raw strings. This phase makes the config safer, more testable, and self-documenting.

---

### 2.1 Add nested DatabaseSettings and RedisSettings models

**File:** `backend/app/config.py`

**Why it matters:**
`database_url: str` accepts any string — a typo in the URL is only discovered when the first DB call fails, often with a cryptic `psycopg2` error. Breaking the URL into typed components lets Pydantic validate host, port, and database name individually at startup.

**Current code:**
```python
class Settings(BaseSettings):
    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str
```

**Target pattern:**
```python
from pydantic import BaseModel, field_validator

class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "customervoice"
    user: str = "postgres"
    password: str = ""

    @property
    def url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @field_validator("port")
    @classmethod
    def port_must_be_valid(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Invalid port: {v}")
        return v


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    db: int = 0

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_nested_delimiter="__",   # DB__HOST, DB__PORT → db.host, db.port
        extra="ignore",
    )

    db: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()

    # Keep database_url as a computed alias for Alembic compatibility
    @property
    def database_url(self) -> str:
        return self.db.url
```

`.env` migration — replace the single `DATABASE_URL=postgresql://...` line with:
```
DB__HOST=localhost
DB__PORT=5432
DB__NAME=customervoice
DB__USER=postgres
DB__PASSWORD=secret
```

**Note:** Alembic's `env.py` reads `settings.database_url` — the `@property` alias keeps this working without changes to the migration config.

**Effort:** M
**Dependencies:** None — but 4.1 and 4.5 depend on this step being done first.

---

### 2.2 Add secret_key field with auto-generated default

**File:** `backend/app/config.py`

**Why it matters:**
There is no `secret_key` in Settings. This field is required for signing auth tokens, CSRF protection, and any future signed-cookie session. Without it, adding JWT auth requires going back to touch Settings anyway. Defaulting to `secrets.token_hex(32)` means development works out of the box; production overrides via `SECRET_KEY` env var.

**Current state:** Field does not exist.

**Target pattern:**
```python
import secrets

class Settings(BaseSettings):
    ...
    secret_key: str = secrets.token_hex(32)
```

**Effort:** S
**Dependencies:** None

---

### 2.3 Add Literal types for constrained fields

**File:** `backend/app/config.py`

**Why it matters:**
`app_env: str = "development"` accepts any string. Passing `APP_ENV=prod` (missing the "uction") silently succeeds, but `docs_url` and `redoc_url` are shown because the check is `settings.app_env != "production"`. A `Literal` type catches invalid values at startup.

**Current code:**
```python
app_env: str = "development"
```

**Target pattern:**
```python
from typing import Literal

class Settings(BaseSettings):
    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
```

**Effort:** S
**Dependencies:** None

---

### 2.4 Add allowed_origins to Settings

Already specified in 1.4 above. Listed here for phase completeness.

**File:** `backend/app/config.py`

**Target pattern:**
```python
cors_allowed_origins: list[str] = ["http://localhost:3000"]
```

**Effort:** S (done as part of 1.4)
**Dependencies:** None

---

### 2.5 Add get_settings() / SettingsDep pattern for testability

**File:** `backend/app/config.py`

**Why it matters:**
`settings = Settings()` is instantiated at module import time. Tests that need different config (e.g., a test database URL) must monkey-patch the module-level object. The `lru_cache` + dependency-injection pattern allows per-test override via FastAPI's `app.dependency_overrides`.

**Current code:**
```python
settings = Settings()
```

**Target pattern:**
```python
from functools import lru_cache
from typing import Annotated

from fastapi import Depends

@lru_cache
def get_settings() -> Settings:
    return Settings()

# Keep the module-level alias for non-FastAPI code (Celery workers, scripts)
settings = get_settings()

# Type alias for route signatures
SettingsDep = Annotated[Settings, Depends(get_settings)]
```

**In tests:**
```python
def override_settings():
    return Settings(database_url="postgresql://localhost/test_db")

app.dependency_overrides[get_settings] = override_settings
```

**Effort:** S
**Dependencies:** None

---

## Phase 3 — Logging & Exception Handling

---

### 3.1 Add logging configuration in a dedicated module

**New file:** `backend/app/core/logging.py`
**File modified:** `backend/app/main.py`

**Why it matters:**
There is no logging configuration anywhere in `backend/app/`. Python's root logger defaults to WARNING level with no handlers — any `logging.info()` or `logging.debug()` call is silently dropped. Uvicorn emits its own unstructured access log to stdout. These two streams are uncorrelated. In production (CloudWatch, Datadog), you need structured JSON with consistent fields per line.

**Current state:** No `logging.basicConfig()` or `logging.config.dictConfig()` call anywhere in the codebase.

**Target pattern — `backend/app/core/logging.py`:**
```python
import logging
import logging.config
import sys
from app.config import settings

def configure_logging() -> None:
    log_format = (
        "%(asctime)s %(levelname)-8s %(name)s %(message)s"
        if settings.app_env != "production"
        else '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    )

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": log_format},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "formatter": "standard",
            },
        },
        "root": {
            "level": settings.log_level,
            "handlers": ["console"],
        },
        # Quieten noisy third-party loggers
        "loggers": {
            "uvicorn.access": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "httpx": {"level": "WARNING"},
        },
    })
```

**Call it at the top of `backend/app/main.py`**, before the app factory:
```python
from app.core.logging import configure_logging
configure_logging()
```

**Effort:** S
**Dependencies:** 2.3 (log_level Literal field in Settings)

---

### 3.2 Add request logging middleware

**File:** `backend/app/main.py` (or `backend/app/core/middleware.py` imported by main)

**Why it matters:**
Without per-request log lines, you cannot measure latency, track error rates by endpoint, or correlate a user-reported failure with a backend event. This is the minimum for operating any web service.

**Target pattern:**
```python
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("app.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "%s %s %s %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
```

Register in `create_app()` before the CORS middleware so timing includes all middleware:
```python
app.add_middleware(RequestLoggingMiddleware)
```

**Effort:** S
**Dependencies:** 3.1

---

### 3.3 Standardise error response shapes with custom exception classes

**New file:** `backend/app/core/exceptions.py`
**File modified:** `backend/app/main.py`

**Why it matters:**
Currently, error shapes differ depending on the raise site. FastAPI's built-in `RequestValidationError` (Pydantic 422) returns `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`. The `ValueError` handler returns `{"detail": "string"}`. `HTTPException` from routes returns `{"detail": "string"}`. Clients need three different parsing strategies for errors.

**Target pattern — `backend/app/core/exceptions.py`:**
```python
from fastapi import status


class AppException(Exception):
    """Base class for all domain exceptions."""
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    detail: str = "An unexpected error occurred."

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    detail = "Resource not found."


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    detail = "Bad request."


class UpstreamServiceException(AppException):
    status_code = status.HTTP_502_BAD_GATEWAY
    detail = "Upstream service is unavailable."
```

**Register in `main.py`:**
```python
from app.core.exceptions import AppException

@app.exception_handler(AppException)
async def app_exception_handler(_request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "detail": exc.detail}},
    )
```

**Usage in routes (replaces inline HTTPException):**
```python
# Before (routes_reviews.py):
raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

# After:
from app.core.exceptions import NotFoundException
raise NotFoundException("Review not found.")
```

**Effort:** M
**Dependencies:** None

---

### 3.4 Fix Pydantic 422 response to match custom error shape

**File:** `backend/app/main.py`

**Why it matters:**
FastAPI's default `RequestValidationError` handler returns a different JSON shape from the custom handlers defined above. Overriding it unifies the error contract.

**Current state:** No `RequestValidationError` handler is registered; FastAPI's default is used.

**Target pattern:**
```python
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": status.HTTP_422_UNPROCESSABLE_ENTITY,
                "detail": "Validation failed.",
                "fields": exc.errors(),
            }
        },
    )
```

Also remove the current `ValueError → 422` handler — it is too broad. `ValueError` from business logic should be a 500, not a client error.

**Effort:** S
**Dependencies:** 3.3 (to align the envelope shape)

---

## Phase 4 — Database Improvements

---

### 4.1 Move engine creation into an explicit init_db() startup event

**File:** `backend/app/database/database.py`, `backend/app/main.py`

**Why it matters:**
The engine is created at module import time (`engine = create_engine(...)` at module level). If the database is unavailable when the module loads, the process crashes with no log context — just a raw `psycopg2.OperationalError`. Deferring to a startup event means the failure is caught, logged with context, and the process can exit cleanly with a useful error message.

**Current code (`database.py` module level):**
```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

@event.listens_for(engine, "connect")
def _enable_pgvector(dbapi_conn, _connection_record):
    with dbapi_conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    dbapi_conn.commit()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

**Target pattern:**
```python
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from app.config import settings

logger = logging.getLogger(__name__)

# Declare without binding — engine is injected by init_db()
_SessionLocal: sessionmaker | None = None


def init_db() -> None:
    """Called once during app startup. Creates engine, verifies connectivity, enables pgvector."""
    global _SessionLocal

    logger.info(
        "Connecting to database host=%s port=%s db=%s",
        settings.db.host, settings.db.port, settings.db.name,
    )
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )

    # Verify connectivity at startup — fail fast with context
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")

        # Enable pgvector once at startup instead of on every pool connection
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            logger.info("pgvector extension ready.")
        except Exception:
            logger.warning("Could not enable pgvector extension — may already exist or lack permission.", exc_info=True)

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        raise RuntimeError("Database not initialised — call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**Register in `main.py`:**
```python
from app.database.database import init_db

@app.on_event("startup")
def on_startup():
    init_db()
```

**Effort:** M
**Dependencies:** 2.1 (nested DatabaseSettings for structured log fields), 3.1 (logging configured before startup runs)

---

### 4.2 Move pgvector CREATE EXTENSION from event hook to init_db()

This is addressed as part of 4.1 above — the `@event.listens_for(engine, "connect")` hook is removed and replaced with a single `CREATE EXTENSION IF NOT EXISTS vector` call inside `init_db()`.

**Why it matters in isolation:**
The current event hook fires on every new connection opened from the pool. Under load with `pool_size=10`, this means 10 redundant `CREATE EXTENSION IF NOT EXISTS vector` round-trips to Postgres during the warm-up burst. Each requires a cursor, an execute, and a `COMMIT`. The overhead is small but the pattern is incorrect — extension management is a DBA/migration concern, not a per-connection concern.

**Effort:** S (done as part of 4.1)
**Dependencies:** 4.1

---

### 4.3 Add SessionDep type alias — update all route signatures

**Files:** `backend/app/database/database.py`, `backend/app/api/routes_reviews.py`, `backend/app/api/routes_chat.py`

**Why it matters:**
Every route currently carries `db: Session = Depends(get_db)` verbatim. With 5+ routes today and more coming, this boilerplate accumulates. The `Annotated` alias reduces each signature by one import and one repetition.

**Current code (routes_reviews.py line 25):**
```python
db: Session = Depends(get_db)
```

**Target pattern — add to `database.py`:**
```python
from typing import Annotated
from fastapi import Depends

SessionDep = Annotated[Session, Depends(get_db)]
```

**In routes:**
```python
from app.database.database import SessionDep

# Before:
def list_reviews(..., db: Session = Depends(get_db)):

# After:
def list_reviews(..., db: SessionDep):
```

Apply to: `routes_reviews.py` (2 occurrences), `routes_chat.py` (1 occurrence).

**Effort:** S
**Dependencies:** None (purely cosmetic — does not change runtime behaviour)

---

### 4.4 Add TimestampMixin to base.py

**File:** `backend/app/models/base.py`, `backend/app/models/review.py`, `backend/app/models/insight.py`, `backend/app/models/embedding.py`

**Why it matters:**
`created_at` and `updated_at` are copy-pasted identically into `Review` and `Insight`. `ReviewEmbedding` is likely missing them. When the column definition needs to change (e.g., adding an index, changing the timezone handling), it must be updated in N places.

**Current `base.py`:**
```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

**Current `review.py` (lines 74–82) — duplicated in every model:**
```python
created_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True), server_default=func.now(), nullable=False
)
updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
)
```

**Target pattern — `base.py`:**
```python
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column


class TimestampMixin:
    """Adds server-managed created_at and updated_at to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Base(DeclarativeBase):
    pass
```

**In each model — remove the duplicate columns and inherit from `TimestampMixin`:**
```python
# review.py — before
class Review(Base):
    ...
    created_at: Mapped[datetime] = mapped_column(...)
    updated_at: Mapped[datetime] = mapped_column(...)

# review.py — after
from app.models.base import Base, TimestampMixin

class Review(TimestampMixin, Base):
    ...
    # created_at and updated_at removed — inherited from TimestampMixin
```

Apply to: `Review`, `Insight`, `ReviewEmbedding`. `Insight` currently only has `created_at` — adding `updated_at` via the mixin is a migration (additive, non-destructive).

**Effort:** S
**Dependencies:** Alembic migration required to add `updated_at` to `insights` table if not already present.

---

### 4.5 Add Redis ping health check at startup

**File:** `backend/app/database/database.py` or `backend/app/main.py`

**Why it matters:**
If Redis is down, Celery tasks silently fail to enqueue. The endpoint returns `{"status": "queued", "task_id": "..."}` but the task never runs. A startup ping surfaces this immediately rather than on the first background job.

**Current state:** No Redis connectivity check anywhere at startup.

**Target pattern — add to the `on_startup` handler in `main.py`:**
```python
import redis as redis_lib
from app.config import settings

@app.on_event("startup")
def on_startup():
    init_db()

    # Redis health check
    try:
        r = redis_lib.from_url(settings.redis.url, socket_connect_timeout=3)
        r.ping()
        logger.info("Redis connection verified at %s", settings.redis.url)
    except Exception:
        logger.error("Redis unavailable at %s — Celery tasks will not enqueue.", settings.redis.url, exc_info=True)
        # Do not raise: allow the app to start so /health returns a degraded status
```

**Effort:** S
**Dependencies:** 2.1 (RedisSettings.url property), 4.1 (startup event pattern established)

---

## Phase 5 — Sentiment Pipeline Modernisation

---

### 5.1 Add cardiffnlp/twitter-xlm-roberta-base-sentiment as local classifier

**New file:** `pipelines/processing/sentiment_classifier.py`

**Why it matters:**
`analyze_sentiment_and_topics()` currently sends every review to OpenRouter, incurring per-token cost and network latency for a task a local model handles well. `cardiffnlp/twitter-xlm-roberta-base-sentiment` is a 278M-parameter model that runs on CPU in ~50 ms per review, supports 100+ languages (matching the multilingual embedding model already in use), and returns a confidence score that enables the hybrid routing logic in 5.2.

**Current code (`sentiment_analysis.py`):**
```python
def analyze_sentiment_and_topics(text: str, max_topics: int = 5) -> SentimentResult:
    # Every call → OpenRouter API → LLM inference → JSON parse
    resp = _client().chat.completions.create(
        model=settings.openrouter_chat_model,
        messages=[...],
        temperature=0.2,
    )
```

**Target pattern — `pipelines/processing/sentiment_classifier.py`:**
```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from transformers import pipeline

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "cardiffnlp/twitter-xlm-roberta-base-sentiment"

_LABEL_MAP = {
    "Positive": "positive",
    "Negative": "negative",
    "Neutral": "neutral",
}


@dataclass
class ClassifierResult:
    sentiment_label: str   # "positive" | "negative" | "neutral"
    confidence: float      # 0.0 – 1.0


@lru_cache(maxsize=1)
def _get_pipeline():
    logger.info("Loading sentiment classifier model: %s", CLASSIFIER_MODEL)
    return pipeline(
        "text-classification",
        model=CLASSIFIER_MODEL,
        top_k=None,          # return all class scores
        truncation=True,
        max_length=512,
    )


def classify_sentiment(text: str) -> ClassifierResult:
    """Run local transformer classifier. Returns label and confidence score."""
    if not text.strip():
        return ClassifierResult(sentiment_label="neutral", confidence=1.0)

    pipe = _get_pipeline()
    results: list[dict] = pipe(text)[0]
    top = max(results, key=lambda r: r["score"])
    label = _LABEL_MAP.get(top["label"], "neutral")
    return ClassifierResult(sentiment_label=label, confidence=top["score"])
```

**pip install:** `transformers torch` (or `transformers[sentencepiece]` — the model uses SentencePiece tokeniser). Add to `backend/requirements.txt`.

**Effort:** M
**Dependencies:** `transformers`, `torch` (or `torchcpu`) available in the environment.

---

### 5.2 Add routing logic — local classifier first, LLM escalation for low-confidence

**File:** `pipelines/processing/sentiment_analysis.py`

**Why it matters:**
Routing the majority of reviews through the local classifier eliminates API cost and latency for straightforward cases. The LLM path is reserved for short, ambiguous, or sarcastic text where the classifier's confidence is below a threshold. This reduces OpenRouter spend without sacrificing accuracy on hard cases.

**Current code:**
```python
def analyze_sentiment_and_topics(text: str, max_topics: int = 5) -> SentimentResult:
    # Always calls LLM — no routing
    resp = _client().chat.completions.create(...)
```

**Target pattern — add routing wrapper:**
```python
from pipelines.processing.sentiment_classifier import classify_sentiment

CONFIDENCE_THRESHOLD = 0.80  # reviews below this go to LLM for confirmation

def analyze_sentiment_and_topics(text: str, max_topics: int = 5) -> SentimentResult:
    """Route: local classifier for confident cases, LLM for ambiguous ones."""
    if not text.strip():
        return SentimentResult(sentiment_score=0.0, sentiment_label=SentimentLabel.neutral, topics=[])

    # Step 1 — fast local classifier
    classifier_result = classify_sentiment(text)

    if classifier_result.confidence >= CONFIDENCE_THRESHOLD:
        # High confidence — only need topics from LLM (cheaper prompt)
        topics = _extract_topics_only(text, max_topics)
        score = _label_to_score(classifier_result.sentiment_label, classifier_result.confidence)
        return SentimentResult(
            sentiment_score=score,
            sentiment_label=SentimentLabel(classifier_result.sentiment_label),
            topics=topics,
        )

    # Step 2 — low confidence — full LLM call (existing logic)
    return _analyze_with_llm(text, max_topics)


def _label_to_score(label: str, confidence: float) -> float:
    """Convert classifier label + confidence to a -1.0..1.0 score."""
    if label == "positive":
        return confidence
    elif label == "negative":
        return -confidence
    return 0.0


def _extract_topics_only(text: str, max_topics: int) -> list[str]:
    """Cheaper LLM call — only asks for topics, not sentiment."""
    prompt = (
        f"Extract up to {max_topics} short noun phrases describing what this review is about. "
        "Return ONLY a JSON array of strings. No explanation."
    )
    resp = _client().chat.completions.create(
        model=settings.openrouter_chat_model,
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": text}],
        temperature=0.1,
    )
    ...  # parse array
```

**Effort:** M
**Dependencies:** 5.1

---

### 5.3 Add batch processing to sentiment_analysis.py

**File:** `pipelines/processing/sentiment_analysis.py`

**Why it matters:**
The Celery task currently calls `analyze_sentiment_and_topics()` once per review, meaning N reviews = N LLM API calls. Batching reduces cold-start overhead, enables prompt consolidation, and significantly cuts cost when processing backfills.

**Current state:** `analyze_sentiment_and_topics(text)` accepts a single string.

**Target pattern:**
```python
def analyze_sentiment_and_topics_batch(
    texts: list[str], max_topics: int = 5
) -> list[SentimentResult]:
    """Process a batch of reviews in a single LLM call for efficiency.

    Falls back to per-item local classifier first; only unresolved items go to LLM.
    """
    results: list[SentimentResult | None] = [None] * len(texts)
    llm_indices: list[int] = []

    for i, text in enumerate(texts):
        if not text.strip():
            results[i] = SentimentResult(
                sentiment_score=0.0, sentiment_label=SentimentLabel.neutral, topics=[]
            )
            continue
        cr = classify_sentiment(text)
        if cr.confidence >= CONFIDENCE_THRESHOLD:
            results[i] = SentimentResult(
                sentiment_score=_label_to_score(cr.sentiment_label, cr.confidence),
                sentiment_label=SentimentLabel(cr.sentiment_label),
                topics=[],  # topics filled by separate batch call if needed
            )
        else:
            llm_indices.append(i)

    if llm_indices:
        # Build a single prompt with all ambiguous reviews numbered
        batch_results = _analyze_batch_with_llm(
            [texts[i] for i in llm_indices], max_topics
        )
        for idx, result in zip(llm_indices, batch_results):
            results[idx] = result

    return results  # type: ignore[return-value]
```

**Update the Celery task** to call `analyze_sentiment_and_topics_batch(texts)` with chunks of 20 reviews instead of looping 1-by-1.

**Effort:** M
**Dependencies:** 5.1, 5.2

---

## Phase 6 — Benchmarking & Evaluation

---

### 6.1 Create backend/scripts/benchmark_sentiment.py

**New file:** `backend/scripts/benchmark_sentiment.py`

**Why it matters:**
Phase 5 introduces a two-path routing strategy. Without a benchmark, you cannot quantify the accuracy trade-off (local classifier vs LLM) or justify the confidence threshold value. This script makes the routing decision data-driven.

**Target pattern:**
```python
"""
Benchmark sentiment analysis accuracy and latency against a golden dataset.

Usage:
    python -m backend.scripts.benchmark_sentiment --dataset data/golden_sentiment.jsonl

Dataset format (JSONL):
    {"text": "Great food!", "label": "positive"}
    {"text": "Service was terrible.", "label": "negative"}
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from sklearn.metrics import classification_report, f1_score

from pipelines.processing.sentiment_classifier import classify_sentiment
from pipelines.processing.sentiment_analysis import analyze_sentiment_and_topics


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def benchmark(dataset: list[dict], use_llm: bool = False) -> dict:
    true_labels, pred_labels, latencies = [], [], []

    for item in dataset:
        start = time.perf_counter()
        if use_llm:
            result = analyze_sentiment_and_topics(item["text"])
            pred = result.sentiment_label.value
        else:
            result = classify_sentiment(item["text"])
            pred = result.sentiment_label
        latencies.append((time.perf_counter() - start) * 1000)

        true_labels.append(item["label"])
        pred_labels.append(pred)

    return {
        "macro_f1": f1_score(true_labels, pred_labels, average="macro"),
        "report": classification_report(true_labels, pred_labels),
        "p50_ms": sorted(latencies)[len(latencies) // 2],
        "p99_ms": sorted(latencies)[int(len(latencies) * 0.99)],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--llm", action="store_true", help="Also benchmark full LLM path")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    print("=== Local Classifier ===")
    local_results = benchmark(dataset, use_llm=False)
    print(f"Macro F1:  {local_results['macro_f1']:.4f}")
    print(f"P50 lat:   {local_results['p50_ms']:.1f}ms")
    print(f"P99 lat:   {local_results['p99_ms']:.1f}ms")
    print(local_results["report"])

    if args.llm:
        print("=== LLM (OpenRouter) ===")
        llm_results = benchmark(dataset, use_llm=True)
        print(f"Macro F1:  {llm_results['macro_f1']:.4f}")
        print(f"P50 lat:   {llm_results['p50_ms']:.1f}ms")
        print(local_results["report"])
```

**pip install:** `scikit-learn` (already likely present).

**Effort:** M
**Dependencies:** 5.1, 5.2

---

### 6.2 Add MLflow tracking to benchmark script

**File:** `backend/scripts/benchmark_sentiment.py`

**Why it matters:**
Running the benchmark once is useful. Running it repeatedly (after model updates, threshold changes, or new training data) and comparing runs requires experiment tracking. MLflow is the standard open-source tool for this; it requires no external service in local mode (`mlflow.set_tracking_uri("./mlruns")`).

**Target pattern — add to benchmark script:**
```python
import mlflow

def run_tracked_benchmark(dataset: list[dict], run_name: str, threshold: float) -> None:
    mlflow.set_experiment("sentiment-benchmark")

    with mlflow.start_run(run_name=run_name):
        mlflow.log_param("confidence_threshold", threshold)
        mlflow.log_param("dataset_size", len(dataset))

        results = benchmark(dataset, use_llm=False)
        mlflow.log_metric("macro_f1", results["macro_f1"])
        mlflow.log_metric("p50_latency_ms", results["p50_ms"])
        mlflow.log_metric("p99_latency_ms", results["p99_ms"])

        # Log the classification report as an artifact
        report_path = Path("/tmp/classification_report.txt")
        report_path.write_text(results["report"])
        mlflow.log_artifact(str(report_path))
```

**pip install:** `mlflow`.

**Effort:** S
**Dependencies:** 6.1

---

### 6.3 Add DeepEval test cases for RAG pipeline faithfulness and answer relevancy

**New file:** `backend/tests/test_rag_eval.py`

**Why it matters:**
The RAG pipeline (Phase 5 in the original build) has no automated quality gate. A change to the retriever, reranker, or answer generator could silently degrade answer quality — fewer citations, hallucinated facts, irrelevant answers. DeepEval provides LLM-as-judge metrics for `faithfulness` (does the answer stay grounded in the retrieved context?) and `answer_relevancy` (does the answer address the question?).

**Target pattern:**
```python
"""
RAG pipeline evaluation using DeepEval.

Run with:  pytest backend/tests/test_rag_eval.py -v
Requires:  DEEPEVAL_API_KEY (or set use_local=True for local judge)
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase

# Minimal golden test cases — expand this set before production
GOLDEN_CASES = [
    {
        "input": "What do customers say about wait times?",
        "expected_output_keywords": ["wait", "time", "minutes", "slow", "fast"],
        "context": [
            "The wait was 45 minutes, completely unacceptable.",
            "Quick service, in and out in 10 minutes.",
        ],
        "actual_output": None,  # filled at test time by calling run_rag_pipeline()
    },
]


@pytest.mark.parametrize("case", GOLDEN_CASES)
def test_rag_faithfulness(case, db_session):
    from app.services.rag_service import run_rag_pipeline

    answer, _ = run_rag_pipeline(db=db_session, question=case["input"], business_id="test-biz")

    test_case = LLMTestCase(
        input=case["input"],
        actual_output=answer,
        retrieval_context=case["context"],
    )
    faithfulness = FaithfulnessMetric(threshold=0.7)
    relevancy = AnswerRelevancyMetric(threshold=0.7)

    assert_test(test_case, [faithfulness, relevancy])
```

**pip install:** `deepeval`.

**Effort:** M
**Dependencies:** A working test database fixture (`db_session`); RAG pipeline must be importable in test context.

---

## Phase 7 — Production Readiness

---

### 7.1 Add /health/ready and /health/live endpoints

**File:** `backend/app/main.py` (or a new `backend/app/api/routes_health.py`)

**Why it matters:**
The current `/health` endpoint always returns `{"status": "ok"}`. A Kubernetes liveness probe or ALB health check using this endpoint will never detect a degraded state (DB down, Redis down). Separating liveness (is the process alive?) from readiness (is the process ready to serve traffic?) is standard practice.

**Current code (main.py lines 64–66):**
```python
@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok", "env": settings.app_env}
```

**Target pattern:**
```python
import logging
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
import redis as redis_lib
from sqlalchemy import text
from app.database.database import get_db
from app.config import settings

logger = logging.getLogger(__name__)
health_router = APIRouter(tags=["health"])


@health_router.get("/health/live")
def liveness() -> dict:
    """Kubernetes liveness probe — is the process running?"""
    return {"status": "alive"}


@health_router.get("/health/ready")
def readiness() -> JSONResponse:
    """Kubernetes readiness probe — can the process serve traffic?"""
    checks: dict[str, str] = {}
    ok = True

    # Database check
    try:
        db = next(get_db())
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.error("Readiness check: database unavailable", exc_info=True)
        checks["database"] = "error"
        ok = False

    # Redis check
    try:
        r = redis_lib.from_url(settings.redis.url, socket_connect_timeout=1)
        r.ping()
        checks["redis"] = "ok"
    except Exception:
        logger.error("Readiness check: redis unavailable", exc_info=True)
        checks["redis"] = "error"
        ok = False

    status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if ok else "degraded", "checks": checks},
    )
```

Register: `app.include_router(health_router)` in `create_app()`.

**Effort:** S
**Dependencies:** 4.1 (init_db pattern), 4.5 (Redis settings), 3.1 (logging)

---

### 7.2 Add rate limiting middleware on integrations and chat endpoints

**File:** `backend/app/main.py`, `backend/app/api/routes_integrations.py`, `backend/app/api/routes_chat.py`

**Why it matters:**
`POST /api/chat` runs an LLM query per request. `GET /api/integrations/google/search` consumes SerpAPI quota per request. Both are exposed to cost amplification without rate limiting. `slowapi` integrates with FastAPI in ~10 lines and uses Redis as the backing store (already a dependency).

**Current state:** No rate limiting on any endpoint.

**Target pattern:**
```python
# backend/app/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis.url)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Apply per-endpoint (routes_chat.py):**
```python
from app.main import limiter

@router.post("")
@limiter.limit("20/minute")   # 20 RAG calls per minute per IP
def chat(request: Request, body: ChatRequest, db: SessionDep) -> ChatResponse:
    ...
```

**Apply to integrations (routes_integrations.py):**
```python
@router.get("/google/search")
@limiter.limit("30/minute")   # 30 SerpAPI proxy calls per minute per IP
def search_google_places(request: Request, ...):
    ...
```

**pip install:** `slowapi`.

**Effort:** S
**Dependencies:** 2.1 (RedisSettings.url), 1.3 (API key auth — rate limit by API key instead of IP once auth is in place)

---

### 7.3 Pool configuration in settings — pool_size, max_overflow per environment

**Files:** `backend/app/config.py`, `backend/app/database/database.py`

**Why it matters:**
`pool_size=10, max_overflow=20` is hardcoded in `database.py`. A development laptop running tests does not need 30 connections. A production instance behind a load balancer may need more. These values should be environment-driven and validated.

**Current code (`database.py` line 10–15):**
```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
```

**Target pattern — add to `DatabaseSettings` (from 2.1):**
```python
class DatabaseSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "customervoice"
    user: str = "postgres"
    password: str = ""
    pool_size: int = 5          # conservative default — override per environment
    max_overflow: int = 10

    @field_validator("pool_size", "max_overflow")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Pool size must be >= 1")
        return v
```

**In `.env` per environment:**
```
# development
DB__POOL_SIZE=2
DB__MAX_OVERFLOW=3

# production
DB__POOL_SIZE=10
DB__MAX_OVERFLOW=20
```

**In `init_db()`:**
```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db.pool_size,
    max_overflow=settings.db.max_overflow,
)
```

**Effort:** S
**Dependencies:** 2.1, 4.1

---

## Prioritised Summary Table

| Phase | Key Steps | Total Effort | Priority | What It Unblocks |
|---|---|---|---|---|
| **Phase 1 — Critical** | Fix SerpAPI error leak; log 500s; add X-API-Key auth; move CORS to settings | **S+S+S+S = ~2h** | P0 — do before any deployment | Every other phase is safer to ship once auth is in place |
| **Phase 2 — Settings** | Nested DB/Redis models; secret_key; Literal types; allowed_origins; get_settings() | **S+S+S+S+S = ~3h** | P1 — foundation for phases 4 and 7 | 4.1 (structured DB logging), 4.5 (Redis ping), 7.1 (health endpoint), 7.3 (pool config) |
| **Phase 3 — Logging** | Logging config module; request middleware; AppException hierarchy; Pydantic 422 fix | **S+S+M+S = ~4h** | P1 — production visibility | Without this, 500s are invisible and error shapes are inconsistent for frontend |
| **Phase 4 — Database** | init_db() startup event; remove pgvector hook; SessionDep; TimestampMixin; Redis ping | **M+S+S+S+S = ~5h** | P2 — correctness + maintainability | Cleaner route signatures; fail-fast startup; consistent model timestamps |
| **Phase 5 — Sentiment** | Local classifier; routing logic; batch processing | **M+M+M = ~1.5d** | P2 — cost reduction | Eliminates per-review LLM cost for ~80% of reviews; unblocks Phase 6 benchmarking |
| **Phase 6 — Evaluation** | Benchmark script; MLflow tracking; DeepEval RAG tests | **M+S+M = ~1d** | P3 — quality gates | Enables confident changes to the RAG and sentiment pipeline; CI quality gate |
| **Phase 7 — Production** | /health/ready + /health/live; slowapi rate limiting; pool config in settings | **S+S+S = ~3h** | P2 — ops readiness | Required for Kubernetes deployment, ALB health checks, and cost protection |

**Recommended execution order within immediate sprint:**
1. Phase 1 entirely (2 hours) — security baseline
2. Phase 2 (3 hours) — settings cleanup, required by Phase 4 and 7
3. Phase 3 (4 hours) — logging and exceptions, required for diagnosing everything else
4. Phase 7.1 and 7.2 (health + rate limiting, 2 hours) — minimal ops readiness before staging

**Next sprint:**
5. Phase 4 (database improvements)
6. Phase 5 (sentiment modernisation)
7. Phase 6 (benchmarking) — run after Phase 5 to validate routing thresholds