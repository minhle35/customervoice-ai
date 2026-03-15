import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_chat, routes_insights, routes_integrations, routes_reviews
from app.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="CustomerVoice AI API",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
    )

    # ---------------------------------------------------------------------------
    # CORS — allow the Next.js frontend (adjust origins in production)
    # ---------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
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
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    app.include_router(routes_reviews.router, prefix="/api/reviews", tags=["reviews"])
    app.include_router(routes_insights.router, prefix="/api/insights", tags=["insights"])
    app.include_router(routes_chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(routes_integrations.router, prefix="/api/integrations", tags=["integrations"])

    # ---------------------------------------------------------------------------
    # Health check
    # ---------------------------------------------------------------------------
    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "development",
    )
