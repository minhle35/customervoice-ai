from __future__ import annotations

from app.integrations.base import PlatformHandler
from app.schemas.review_schema import ReviewCreate


class GoogleHandler(PlatformHandler):
    """Handler for Google Maps Reviews ingestion via SerpAPI.

    Required param: data_id (hex CID from SerpAPI search results).
    Optional param: place_id (ChIJ... canonical ID — preferred as business_id).
    """

    def derive_business_id(self, params: dict) -> str:
        place_id = params.get("place_id")
        data_id = params.get("data_id")
        bid = place_id or data_id
        if not bid:
            raise ValueError(
                "Google ingestion requires place_id or data_id in params. "
                "Run /integrations/google/search to obtain a data_id."
            )
        return bid

    def fetch_reviews(self, business_id: str, params: dict) -> list[ReviewCreate]:
        from pipelines.ingestion.google_reviews_ingestion import fetch_google_reviews
        return fetch_google_reviews(business_id, params)
