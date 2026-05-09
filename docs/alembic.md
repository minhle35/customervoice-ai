# Alembic — Database Schema Migrations

## What is Alembic?

Alembic is a schema migration tool for SQLAlchemy. It tracks changes to your database schema (tables, columns, indexes, enums) as versioned Python files — the same way Git tracks changes to source code.

Without Alembic, evolving a database schema across environments looks like this:
```sql
-- manually run on dev, staging, prod — easy to forget, no history
ALTER TABLE review_embeddings ALTER COLUMN embedding TYPE vector(768);
```

With Alembic, the same change is a versioned file that runs automatically on deploy:
```python
# alembic/versions/56b24fa0b791_change_embedding_dim.py
def upgrade():
    op.drop_column('review_embeddings', 'embedding')
    op.add_column('review_embeddings', sa.Column('embedding', Vector(768)))
```

---

## How it's wired in this codebase

### Config: `backend/alembic.ini`

The `alembic.ini` file lives at `backend/alembic.ini`. One important detail: the `sqlalchemy.url` is intentionally left blank:

```ini
sqlalchemy.url =   # ← blank on purpose
```

The connection URL is injected at runtime from the validated Pydantic settings in `env.py`:

```python
# alembic/env.py
config.set_main_option("sqlalchemy.url", get_settings().db.url)
```

This means Alembic reads the same `DB__HOST`, `DB__PORT`, `DB__NAME`, `DB__USERNAME`, `DB__PASSWORD` from `.env` that the FastAPI app uses — no separate database config to maintain.

### Auto-discovery: `env.py` imports the models

```python
# alembic/env.py
from app.models import Base  # registers all SQLAlchemy models with metadata
from app.models import Insight, Review, ReviewEmbedding
```

By importing all models, Alembic's `autogenerate` can diff the current database against your SQLAlchemy model definitions and detect what changed. This is how `alembic revision --autogenerate` works.

---

## Migration history in this project

| Revision | File | What it does |
|---|---|---|
| `0001` | `0001_initial_schema.py` | Creates `reviews`, `review_embeddings`, `insights` tables; enables pgvector extension; creates `platform_enum`, `sentiment_label_enum`, `insight_type_enum` |
| `56b24fa0b791` | `56b24fa0b791_change_embedding_dim_1536_to_768...` | Drops 1536-dim embedding column, adds 768-dim column; rebuilds HNSW index for `multilingual-e5-base` model |
| `0003` | `0003_add_chat_messages.py` | Adds `chat_messages` table for conversation history persistence |

Each file has `revision`, `down_revision` (its parent), `upgrade()`, and `downgrade()`. Alembic uses `down_revision` to build a linked chain — it knows which order to apply migrations and how to roll back.

---

## Common commands

Run from `backend/`:

```bash
# Apply all pending migrations (bring DB up to latest)
alembic upgrade head

# Roll back the last migration
alembic downgrade -1

# Roll back to a specific revision
alembic downgrade 0001

# Create a new migration manually
alembic revision -m "add_business_name_to_reviews"

# Auto-generate a migration by diffing models vs current DB
alembic revision --autogenerate -m "add_business_name_to_reviews"

# See current revision the DB is at
alembic current

# See full migration history
alembic history
```

### In Docker

```bash
docker compose exec backend alembic upgrade head
```

---

## How migrations run on startup

Migrations are **not** applied automatically on FastAPI startup. They run as a manual step (or a CI/CD step before deploy). The FastAPI lifespan only calls `init_db()` which verifies the connection and enables the pgvector extension — it does not run Alembic.

---

## Limitations — when Alembic is not enough

| Problem | Why Alembic can't fully solve it |
|---|---|
| Long-running `ALTER TABLE` on a large table | PostgreSQL holds an `ACCESS EXCLUSIVE` lock for the duration — blocks all reads and writes. Alembic just executes the SQL; it doesn't know the table has 10M rows. |
| Zero-downtime column renames | Renaming a column in one deploy breaks the old code still running in other pods. Requires a multi-step approach: add column → dual-write → migrate data → drop old column across multiple deploys. |
| Large backfills | Backfilling a new column on millions of rows in a single transaction risks timeouts and bloat. Needs to be done in batches outside the migration. |
| `autogenerate` blind spots | Alembic cannot detect changes to PostgreSQL-specific constructs like HNSW index parameters, custom functions, or triggers. Always review generated migrations before running them. |

For this project at its current scale (hundreds to low thousands of reviews), none of these are blocking concerns. The rule of thumb: write migrations by hand for anything involving indexes, enums, or pgvector columns — `autogenerate` is reliable for simple column additions.
