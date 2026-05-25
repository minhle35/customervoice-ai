from __future__ import annotations

from app.integrations.base import PlatformHandler
from app.integrations.google import GoogleHandler

# Map platform name → handler instance.
# To support a new platform, add its handler here.
_REGISTRY: dict[str, PlatformHandler] = {
    "google": GoogleHandler(),
    # "reddit": RedditHandler(),
    # "facebook": FacebookHandler(),
}

SUPPORTED_PLATFORMS = frozenset(_REGISTRY)


def get_handler(platform: str) -> PlatformHandler:
    """Return the handler for the given platform.

    Raises KeyError if the platform is not registered.
    """
    try:
        return _REGISTRY[platform]
    except KeyError:
        raise KeyError(
            f"Unsupported platform '{platform}'. "
            f"Supported: {sorted(SUPPORTED_PLATFORMS)}"
        )
