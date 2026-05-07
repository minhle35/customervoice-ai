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
├── Dockerfile                  # python:3.14-slim + uv installer
└── requirements.txt            # pip fallback reference
workers/
├── celery_app.py               # Celery instance wired to settings
└── tasks.py                    # Task stubs (expanded in Phase 2)
```

---

## Architectural Decisions

### 1. `uv` + `pyproject.toml` over `pip` + `requirements.txt`

The Dockerfile uses `uv` (astral-sh) as the package manager with layer-cached installs via `uv.lock`. This gives faster, reproducible builds. `requirements.txt` is kept as a human-readable reference and for environments without `uv`.

To install locally:
```bash
cd backend
uv sync          # installs deps + creates .venv
uv run <command> # runs command inside the venv
```

### 2. Pydantic-settings as single config source

All environment variables are loaded through the `Settings` class in `app/config.py`. Alembic's `env.py` imports `settings` directly instead of calling `load_dotenv()` — this keeps configuration in one place and validates required fields at startup.

The `.env` file path is anchored to `config.py`'s own location so it resolves correctly regardless of the working directory:

```python
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
```

### 3. SQLAlchemy 2.0 `mapped_column` style

Models use the modern `Mapped[T]` + `mapped_column()` syntax instead of the older `Column()` style. This gives full type-checker support and clearer nullability intent.

### 4. Shared `DeclarativeBase` in `models/base.py`

A single `Base` is defined in `base.py` and imported by all models. Alembic's `env.py` imports `Base` (and all models) so it can detect schema changes automatically.

### 5. pgvector registered on connect

`pgvector.sqlalchemy.Vector` is imported in `database.py` to register the type with SQLAlchemy. The `@event.listens_for(engine, "connect")` hook runs `CREATE EXTENSION IF NOT EXISTS vector` automatically, so the extension is always available without a manual step.

### 6. Celery reads from `settings`

The original `celery_app.py` used literal `${CELERY_BROKER_URL}` shell-style strings (not Python interpolation), so the broker was never configured. Fixed to import `settings` directly:

```python
celery_app = Celery(
    "customer_voice_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
```

---

## Tradeoff Decisions

### Embedding model: `text-embedding-3-small` (1536 dims) over `text-embedding-3-large` (3072 dims)

| Factor | 3-small (chosen) | 3-large |
|--------|-----------------|---------|
| Dimensions | 1536 | 3072 |
| pgvector HNSW | Supported (≤ 2000) | Exceeds limit |
| Index type | HNSW | Requires ivfflat |
| Query speed | Faster | Slower |
| Cost per token | ~6x cheaper | Baseline |
| Quality delta | Minimal for review text | Marginal gain |

HNSW is preferred over ivfflat because it requires no training phase and performs better on small-to-medium datasets. ivfflat requires enough data to set the `lists` parameter meaningfully. For MVP, `text-embedding-3-small` + HNSW is the right call; upgrading to 3-large later requires a new migration and re-embedding all data.

---

## Issues & Resolutions

### Issue 1: `pydantic_core.ValidationError` — required fields missing

**Symptom:** Running `uv run alembic upgrade head` failed with 4 missing fields (`database_url`, `redis_url`, etc.) even though `.env` existed.

**Cause:** pydantic-settings resolves `env_file=".env"` relative to the current working directory. Running from `backend/` found no `.env` there; the file lives at the project root.

**Resolution:** Anchor the path to `config.py`'s file location:
```python
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"
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

### Issue 4: HNSW index fails on `Vector(3072)`

**Symptom:** Migration failed during HNSW index creation — pgvector caps HNSW at 2000 dimensions.

**Resolution:** Switched to `text-embedding-3-small` (1536 dims). See [Tradeoff Decisions](#tradeoff-decisions) above.

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
- Add sentiment analysis and topic extraction using OpenAI
- Implement embedding generation and pgvector storage