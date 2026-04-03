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

    # OpenRouter (chat/LLM — OpenAI-compatible)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Embeddings — sentence-transformers (local, no API cost)
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dimensions: int = 768

    # LangSmith observability (set LANGCHAIN_TRACING_V2=true to enable)
    langchain_tracing_v2: str = "false"
    langchain_api_key: str = ""
    langchain_project: str = "customervoice-ai"

    # External APIs
    google_reviews_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""


settings = Settings()
