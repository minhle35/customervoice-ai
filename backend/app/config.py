"""App-wide settings."""

__all__ = (
    "DatabaseSettings",
    "ServerSettings",
    "SettingsDep",
    "get_settings",
)

import secrets
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi.params import Depends
from pydantic import BaseModel, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    pass

# Forward-reference resolved after ServerSettings is defined
_SETTINGS: "ContextVar[ServerSettings]" = ContextVar("app.config.ServerSettings")


class DatabaseSettings(BaseModel):
    drivername: str = "postgresql+psycopg2"
    host: str = "localhost"
    port: int = 5432
    name: str = "customer_voice_ai"
    username: str = "postgres"
    password: str = "postgres"
    query: dict[str, str] = {}

    poolclass: Literal["_default_", "static_pool", "queue_pool"] = "_default_"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        return (
            f"{self.drivername}://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseModel):
    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0
    decode_responses: bool = False
    socket_connect_timeout: int = 5
    socket_timeout: int = 5
    retry_on_timeout: bool = True
    health_check_interval: int = 30

    @computed_field  # type: ignore[prop-decorator]
    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class CelerySettings(BaseModel):
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",  # double-underscore: DB__HOST, DB__PORT etc.
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "CustomerVoiceAI"
    dev_reload: bool = False

    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_version: str = "0.1.0"

    secret_key: str = secrets.token_urlsafe(32)

    db: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()
    celery: CelerySettings = CelerySettings()

    # Logging
    log_fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_file: Path = Path("app.log")

    # CORS — consumed by main.py, override in production
    allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # OpenRouter (chat/LLM — OpenAI-compatible)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str = "google/gemini-2.0-flash-001"

    # Embeddings — sentence-transformers (local, no API cost)
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dimensions: int = 768

    # LangSmith observability
    langsmith_tracing: str = "true"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "customervoice-ai"

    # External APIs
    google_reviews_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""


def get_settings() -> ServerSettings:
    try:
        return _SETTINGS.get()
    except LookupError:
        s = ServerSettings()
        _SETTINGS.set(s)
        return s


def set_settings(settings: ServerSettings) -> None:
    _SETTINGS.set(settings)


# FastAPI dependency — use in route signatures: settings: SettingsDep
SettingsDep = Annotated[ServerSettings, Depends(get_settings)]
