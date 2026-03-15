from fastapi import FastAPI
from app.api import routes_reviews, routes_insights, routes_chat, routes_integrations


def create_app() -> FastAPI:
    app = FastAPI(title="CustomerVoice AI API")
    app.include_router(routes_reviews.router, prefix="/api/reviews", tags=["reviews"])
    app.include_router(routes_insights.router, prefix="/api/insights", tags=["insights"])
    app.include_router(routes_chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(routes_integrations.router, prefix="/api/integrations", tags=["integrations"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()

