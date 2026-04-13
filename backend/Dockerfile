FROM python:3.12-slim

ARG HOST=0.0.0.0
ENV HOST=${HOST}

ARG PORT=8000
ENV PORT=${PORT}
EXPOSE ${PORT}

# Set work directory
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies using uv
ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/opt/uv-cache/

RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync \
        --no-install-project \
        --locked \
        --compile-bytecode

# Copy backend source
COPY backend/ /app

# Copy project-root modules needed at runtime
COPY workers/ /app/workers/
COPY pipelines/ /app/pipelines/

# Install project itself
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root user — limits blast radius if the app is compromised
RUN useradd --no-create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f "http://localhost:${PORT}/health" || exit 1

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2"]