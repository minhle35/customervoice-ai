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
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_SETTINGS: ContextVar["ServerSettings"] = ContextVar("app.settings.Settings")


class DatabaseSettings(BaseModel):
    """Database settings."""

    drivername: str = "postgresql"
    host: str | None = None
    port: int | None = None
    name: str = "db"
    username: str | None = None
    password: str | None = None
    query: dict[str, str] = {}

    poolclass: Literal["_default_", "static_pool", "queue_pool"] = "_default_"


class RedisSettings(BaseModel):
    """Redis settings."""

    host: str = "localhost"
    port: int = 6379
    password: str | None = None
    db: int = 0
    decode_responses: bool = False
    socket_connect_timeout: int = 5
    socket_timeout: int = 5
    retry_on_timeout: bool = True
    health_check_interval: int = 30


class ServerSettings(BaseSettings):
    """App-wide settings."""

    model_config = SettingsConfigDict(
        env_file=".env",  # load settings from environment file.
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
        extra="ignore",
    )

    # Development environment
    environment: str = "development"
    dev_reload: bool = False

    server_host: str = "0.0.0.0"
    server_port: int = 8000
    server_version: str = "0.1.0"

    secret_key: str = secrets.token_hex(32)

    db: DatabaseSettings = DatabaseSettings()
    redis: RedisSettings = RedisSettings()

    log_fmt: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: Path = Path("app.log")

    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    ai_service_provider: Literal["offline", "openai"] = "offline"
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None


def get_settings() -> ServerSettings:
    try:
        return _SETTINGS.get()
    except LookupError:
        return ServerSettings()


def set_settings(settings: ServerSettings) -> None:
    _SETTINGS.set(settings)


SettingsDep = Annotated[ServerSettings, Depends(get_settings)]
