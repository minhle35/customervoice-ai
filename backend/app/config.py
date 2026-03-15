from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file: backend/app/config.py → ../../.env (project root)
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # App
    app_env: str = "development"
    app_name: str = "CustomerVoiceAI"

    # Database
    database_url: str

    # Redis / Celery
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    # OpenAI
    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-large"
    openai_chat_model: str = "gpt-4o-mini"

    # External APIs
    google_reviews_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""


settings = Settings()
