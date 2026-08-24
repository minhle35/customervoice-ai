"""
SerpApiService — Google Maps place lookup via SerpAPI.

    ├── search_places(query, country) → list[PlaceResult]
    │       Calls engine=google_maps to search by business name.
    │       Returns up to 5 candidates with their data_id, place_id, title, and address.
    │
    └── resolve_data_id(query, country) → str | None
            Convenience wrapper — returns the data_id of the top match.

PlaceResult contains two identifiers:
  - data_id   (hex, e.g. "0x3177...:0x9b5a...") — required by SerpAPI google_maps_reviews engine
  - place_id  (ChIJ format, e.g. "ChIJN1t_tDeuEmsRUsoyG83frY4") — Google's canonical Place ID,
              used as business_id in the DB so it matches the standard Google Maps URL identifier
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import get_settings

_SEARCH_PATH = "/search.json"
_MAX_CANDIDATES = 10


@dataclass
class PlaceResult:
    title: str
    data_id: str  # SerpAPI hex ID — pass as params["data_id"] to ingestion
    place_id: str | None  # Google Place ID (ChIJ...) — used as business_id in DB
    address: str | None
    rating: float | None
    reviews_count: int | None


class SerpApiService:
    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key or get_settings().google_reviews_api_key
        if not self._api_key:
            raise ValueError("GOOGLE_REVIEWS_API_KEY is not set")

    async def search_places(
        self, query: str, country: str = "us", limit: int = _MAX_CANDIDATES
    ) -> list[PlaceResult]:
        """Search Google Maps for a business by name.

        Returns up to `limit` results (capped at _MAX_CANDIDATES), each with a
        data_id that can be used to fetch reviews via the ingestion pipeline.
        """
        limit = min(limit, _MAX_CANDIDATES)
        try:
            response = await self._client.get(
                _SEARCH_PATH,
                params={
                    "engine": "google_maps",
                    "q": query,
                    "api_key": self._api_key,
                    "hl": "en",
                    "gl": country,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise RuntimeError("SerpAPI request timed out") from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"SerpAPI returned {exc.response.status_code}: {exc.response.text}"
            ) from None

        if "error" in payload:
            raise RuntimeError(f"SerpAPI error: {payload['error']}")

        results: list[PlaceResult] = []

        # Single exact match
        place = payload.get("place_results")
        if place and isinstance(place, dict) and place.get("data_id"):
            results.append(
                PlaceResult(
                    title=place.get("title", ""),
                    data_id=place["data_id"],
                    place_id=place.get("place_id"),
                    address=place.get("address"),
                    rating=place.get("rating"),
                    reviews_count=place.get("reviews"),
                )
            )

        # List of local results
        for item in payload.get("local_results", [])[:limit]:
            data_id = item.get("data_id")
            if not data_id:
                continue
            results.append(
                PlaceResult(
                    title=item.get("title", ""),
                    data_id=data_id,
                    place_id=item.get("place_id"),
                    address=item.get("address"),
                    rating=item.get("rating"),
                    reviews_count=item.get("reviews"),
                )
            )

        return results[:limit]

    async def resolve_data_id(self, query: str, country: str = "us") -> str | None:
        """Return the data_id of the top Google Maps match for a business name."""
        results = await self.search_places(query, country)
        return results[0].data_id if results else None
