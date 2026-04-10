"""Centralised logging factory.

Usage (lazy import — call only when a logger is needed):
    from app.logger import get_logger
    logger = get_logger(__name__)

Initialisation (called once at startup in main.py):
    from app.logger import configure_logging
    configure_logging(get_settings())

AWS CloudWatch integration (future):
    Install `watchtower`, then in _build_handlers():
        import watchtower, boto3
        session = boto3.Session(region_name="ap-southeast-1")
        handlers.append(watchtower.CloudWatchLogHandler(
            boto3_session=session,
            log_group=f"/customervoice/{settings.app_env}",
            stream_name="api",
        ))
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import ServerSettings

_configured = False


def _build_handlers(settings: "ServerSettings") -> list[logging.Handler]:
    fmt = logging.Formatter(settings.log_fmt)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)

    handlers: list[logging.Handler] = [console]

    # File handler — disabled when log_file is explicitly empty
    if settings.log_file:
        file_handler = logging.FileHandler(settings.log_file)
        file_handler.setFormatter(fmt)
        handlers.append(file_handler)

    # ── AWS CloudWatch (not available yet) ────────────────────────────────
    # import watchtower, boto3
    # if settings.app_env != "development":
    #     session = boto3.Session(region_name="ap-southeast-1")
    #     cw = watchtower.CloudWatchLogHandler(
    #         boto3_session=session,
    #         log_group=f"/customervoice/{settings.app_env}",
    #         stream_name="api",
    #     )
    #     cw.setFormatter(fmt)
    #     handlers.append(cw)
    # ────────────────────────────────────────────────────────────────────────

    return handlers


def configure_logging(settings: "ServerSettings") -> None:
    """Configure the root logger once at application startup."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(settings.log_level)

    for handler in _build_handlers(settings):
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. configure_logging() must be called at startup first."""
    return logging.getLogger(name)
