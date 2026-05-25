from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.review_schema import ReviewCreate


class PlatformHandler(ABC):
    """Base class for platform-specific ingestion logic.

    To add a new platform:
      1. Subclass PlatformHandler and implement both abstract methods.
      2. Register an instance in registry.py.
    """

    @abstractmethod
    def derive_business_id(self, params: dict) -> str:
        """Extract or construct a stable business_id from the request params.

        Raises ValueError if the required params are missing.
        """

    @abstractmethod
    def fetch_reviews(self, business_id: str, params: dict) -> list[ReviewCreate]:
        """Fetch reviews from the platform and return ReviewCreate objects."""
