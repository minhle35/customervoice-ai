FROM python:3.14-slim

ARG HOST=0.0.0.0
ENV HOST=${HOST}
ARG PORT=8000
ENV PORT=${PORT}
EXPOSE ${PORT}

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install deps with cache mount. uv.lock is bound so the layer cache is
# invalidated whenever the lock file changes (e.g. new package added).
ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/opt/uv-cache/
RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync \
        --no-install-project \
        --locked \
        --compile-bytecode


# Add the app and install the project, rem: uv sync --locked
ADD . /app

RUN --mount=from=ghcr.io/astral-sh/uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f "http://localhost:${PORT}/health" || exit 1

# Run the application
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "app.main"]
