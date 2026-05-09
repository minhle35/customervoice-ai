import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_agent, routes_chat, routes_insights, routes_integrations, routes_reviews
from app.config import get_settings
from app.database import init_db
from app.logger import configure_logging, get_logger

configure_logging(get_settings())
logger = get_logger(__name__)

_settings = get_settings()

# Propagate LangSmith settings to os.environ so the langsmith SDK picks them up
os.environ.setdefault("LANGSMITH_TRACING", _settings.langsmith_tracing)
os.environ.setdefault("LANGSMITH_ENDPOINT", _settings.langsmith_endpoint)
os.environ.setdefault("LANGSMITH_API_KEY", _settings.langsmith_api_key)
os.environ.setdefault("LANGSMITH_PROJECT", _settings.langsmith_project)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting up CustomerVoice AI API")
    init_db()
    yield
    logger.info("Shutting down CustomerVoice AI API")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CustomerVoice AI API",
        version=settings.server_version,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
        lifespan=lifespan,
    )

    # ---------------------------------------------------------------------------
    # CORS — origins driven by settings, not hardcoded
    # ---------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Global error handlers
    # ---------------------------------------------------------------------------
    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled exception on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    app.include_router(routes_reviews.router)
    app.include_router(routes_insights.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_integrations.router)
    app.include_router(routes_agent.router)

    # ---------------------------------------------------------------------------
    # Health check
    # ---------------------------------------------------------------------------
    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.app_env == "development",
    )
