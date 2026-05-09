# Backend Setup

This document covers the architectural direction, key decisions, tradeoffs, and issues encountered during Phase 1 backend setup.

---

## Stack Overview

| Layer | Technology | Notes |
|-------|-----------|-------|
| Web framework | FastAPI 0.115 | Async-ready, automatic OpenAPI docs |
| Validation | Pydantic v2 + pydantic-settings | Settings resolved from `.env` |
| ORM | SQLAlchemy 2.0 (mapped columns) | Declarative with type annotations |
| Database | PostgreSQL 16 + pgvector | Vector similarity search |
| Migrations | Alembic | Schema versioning |
| Task queue | Celery + Redis | Background ingestion jobs |
| Package manager | uv + pyproject.toml | Replaces pip + requirements.txt |

---

## Project Structure

```
backend/
├── alembic/                    # Migration tooling
│   ├── env.py                  # Reads DB URL from pydantic settings
│   ├── script.py.mako          # Migration file template
│   └── versions/
│       └── 0001_initial_schema.py
├── alembic.ini                 # Points script_location to alembic/
├── app/
│   ├── api/                    # Route handlers (reviews, insights, chat, integrations)
│   ├── database/
│   │   └── database.py         # Engine, SessionLocal, get_db(), pgvector registration
│   ├── models/
│   │   ├── base.py             # Shared DeclarativeBase
│   │   ├── review.py           # Review model
│   │   ├── insight.py          # Insight model
│   │   └── embedding.py        # ReviewEmbedding model (pgvector)
│   ├── schemas/
│   │   ├── review_schema.py    # ReviewCreate, ReviewOut, IngestRequest
│   │   └── insight_schema.py   # InsightOut, ChatRequest, ChatResponse
│   ├── config.py               # pydantic-settings Settings class
│   └── main.py                 # App factory, CORS, error handlers, entrypoint
├── pyproject.toml              # Dependencies (uv-managed)
└── Dockerfile                  # python:3.12-slim + uv installer
workers/
├── celery_app.py               # Celery instance wired to settings
└── tasks.py                    # Task stubs (expanded in Phase 2)
```

---

## Architectural Decisions

### 1. `uv` + `pyproject.toml` over `pip` + `requirements.txt`

The Dockerfile uses `uv` (astral-sh) as the package manager with layer-cached installs via `uv.lock`. This gives faster, reproducible builds. There is no `requirements.txt` — all dependencies are declared in `pyproject.toml` and pinned via `uv.lock`.

To install locally:
```bash
cd backend
uv sync          # installs deps + creates .venv
uv run <command> # runs command inside the venv
```

### 2. Pydantic-settings as single config source

All environment variables are loaded through the `ServerSettings` class in `app/config.py`. Alembic's `env.py` imports `get_settings()` directly instead of calling `load_dotenv()` — this keeps configuration in one place and validates required fields at startup.

The `.env` file is located using pydantic-settings' built-in `env_file` option:

```python
class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",  # DB__HOST, DB__PORT, etc.
    )
```

Alembic commands must be run from `backend/` so that `env_file=".env"` resolves to `backend/.env` (which is a symlink or copy of the root `.env`).

### 3. SQLAlchemy 2.0 `mapped_column` style

Models use the modern `Mapped[T]` + `mapped_column()` syntax instead of the older `Column()` style. This gives full type-checker support and clearer nullability intent.

### 4. Shared `DeclarativeBase` in `models/base.py`

A single `Base` is defined in `base.py` and imported by all models. Alembic's `env.py` imports `Base` (and all models) so it can detect schema changes automatically.

### 5. pgvector registered on startup

`pgvector.sqlalchemy.Vector` is imported in `database.py` to register the type with SQLAlchemy. The `init_db()` function runs `CREATE EXTENSION IF NOT EXISTS vector` directly via a raw connection at application startup, so the extension is always available without a manual step. FastAPI's lifespan calls `init_db()` before accepting requests.

### 6. Celery reads from `settings`

The original `celery_app.py` used literal `${CELERY_BROKER_URL}` shell-style strings (not Python interpolation), so the broker was never configured. Fixed to import `get_settings()` directly and access the nested `celery` settings object:

```python
from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "customer_voice_ai",
    broker=_settings.celery.broker_url,
    backend=_settings.celery.result_backend,
)
```

---

## Tradeoff Decisions

### Embedding model: `intfloat/multilingual-e5-base` (768 dims, local) over OpenAI API embeddings

| Factor | multilingual-e5-base (chosen) | text-embedding-3-small (OpenAI) |
|--------|-------------------------------|----------------------------------|
| Dimensions | 768 | 1536 |
| pgvector HNSW | Supported (≤ 2000) | Supported (≤ 2000) |
| Cost | Free — runs locally via sentence-transformers | Pay-per-token API call |
| Language support | Multilingual (100+ languages) | Primarily English |
| Latency | CPU inference (~100 ms per batch) | Network round-trip |
| Index type | HNSW | HNSW |

HNSW is preferred over ivfflat because it requires no training phase and performs better on small-to-medium datasets. `intfloat/multilingual-e5-base` was chosen for zero API cost and multilingual review support (Vietnamese, Chinese, etc.). The 768-dim space fits well within HNSW's limit. Switching to an API-based model later requires a re-embedding migration.

---

## Issues & Resolutions

### Issue 1: `pydantic_core.ValidationError` — required fields missing

**Symptom:** Running `uv run alembic upgrade head` failed with 4 missing fields (`database_url`, `redis_url`, etc.) even though `.env` existed.

**Cause:** pydantic-settings resolves `env_file=".env"` relative to the current working directory. Running from `backend/` found no `.env` there; the file lives at the project root.

**Resolution:** Alembic must be run from `backend/` so that pydantic-settings' `env_file=".env"` resolves to the correct `.env` symlink in that directory:
```bash
cd backend
uv run alembic upgrade head
```

---

### Issue 2: `could not translate host name "db"`

**Symptom:** SQLAlchemy connection failed with a DNS resolution error for host `db`.

**Cause:** `DATABASE_URL` in `.env` uses `@db:5432` — the Docker Compose internal service name. This only resolves inside the Docker network. Running Alembic locally bypasses Docker DNS.

**Resolution:** For local development outside Docker, use `localhost`:
```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai
```
Start only the database container:
```bash
docker compose up db -d
```

---

### Issue 3: `DuplicateObject` — type "platform_enum" already exists

**Symptom:** Migration failed with `psycopg2.errors.DuplicateObject` on enum creation, even on a fresh database.

**Root cause (multi-part):**

1. **`sa.Enum` ignores `create_type=False`** — `create_type=False` is a `postgresql.ENUM`-specific parameter. When passed to `sa.Enum` (the generic type), it is silently ignored and the type is always auto-created during `op.create_table`.

2. **`op.create_table` fires `before_create` events** — Even with an explicit `postgresql.ENUM.create()` call beforehand (with `checkfirst=True`), `op.create_table` triggers SQLAlchemy's internal `_on_table_create` on each column's type, which runs `CREATE TYPE` again.

**Resolution:** Use `postgresql.ENUM` (not `sa.Enum`) in all column definitions within `op.create_table`, and always pass `create_type=False`:

```python
# Correct pattern
platform_enum = postgresql.ENUM("google", "reddit", "facebook", name="platform_enum")
platform_enum.create(bind, checkfirst=True)  # explicit, idempotent

op.create_table(
    "reviews",
    sa.Column(
        "platform",
        postgresql.ENUM(..., name="platform_enum", create_type=False),  # no auto-create
        ...
    ),
)
```

---

### Issue 4: HNSW index fails on `Vector(1536)` → migrated to 768 dims

**Symptom:** Initial schema used `Vector(1536)` (sized for OpenAI `text-embedding-3-small`). After switching to `intfloat/multilingual-e5-base` (768-dim), the column dimension and HNSW index needed to change.

**Resolution:** Migration `56b24fa0b791` drops the 1536-dim embedding column, adds a new `Vector(768)` column, and rebuilds the HNSW index for the new dimension. See [Tradeoff Decisions](#tradeoff-decisions) above.

---

## Local Development Quickstart

```bash
# 1. Start the database
docker compose up db -d

# 2. Install Python deps
cd backend
uv sync

# 3. Run migrations
uv run alembic upgrade head

# 4. Start the API server
uv run uvicorn app.main:app --reload
# → http://localhost:8000/docs
```

To run inside Docker fully:
```bash
docker compose up --build
```

---

## Phase 2

- Implement data ingestion pipelines (Google Reviews via SerpAPI, Reddit via PRAW)
- Wire Celery tasks to ingestion pipeline runners
- Add sentiment analysis and topic extraction using OpenRouter (Gemini 2.0 Flash via OpenAI-compatible client)
- Implement embedding generation with `intfloat/multilingual-e5-base` (sentence-transformers) and pgvector storage