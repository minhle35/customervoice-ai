from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.models.review import Platform
from app.schemas.review_schema import ReviewCreate


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


def _stable_id(*parts: str) -> str:
    raw = "|".join([p or "" for p in parts])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def fetch_google_reviews(business_id: str, params: dict) -> list[ReviewCreate]:
    api_key = settings.google_reviews_api_key
    if not api_key:
        raise ValueError("GOOGLE_REVIEWS_API_KEY is not set")

    # Only forward params that SerpAPI's google_maps_reviews engine accepts.
    # Internal keys like place_id and place_name are for DB storage only.
    SERPAPI_ALLOWED = {"data_id", "hl", "sort_by", "next_page_token", "no_cache"}
    serpapi_params = {k: v for k, v in params.items() if k in SERPAPI_ALLOWED}

    query_params = {
        "engine": "google_maps_reviews",
        "api_key": api_key,
        **serpapi_params,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(SERPAPI_ENDPOINT, params=query_params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Re-raise without the request URL to avoid leaking the api_key query param.
            raise RuntimeError(
                f"SerpAPI returned {exc.response.status_code}: {exc.response.text}"
            ) from None
        payload = response.json()

    reviews = []
    for item in payload.get("reviews", []):
        user = item.get("user") or item.get("author") or item.get("user_name")
        # SerpAPI returns user as a dict {"name": ..., "reviews": ..., "photos": ...}
        if isinstance(user, dict):
            author = user.get("name")
        else:
            author = str(user) if user else None

        content = item.get("snippet") or item.get("content") or item.get("text") or ""
        rating = item.get("rating")
        published_at = _parse_datetime(item.get("timestamp") or item.get("time") or item.get("published_at"))
        platform_id = item.get("review_id") or item.get("id")
        if not platform_id:
            platform_id = _stable_id(str(author), str(published_at), content)

        if not content.strip():
            continue

        reviews.append(
            ReviewCreate(
                platform=Platform.google,
                platform_id=str(platform_id),
                business_id=business_id,
                business_name=params.get("place_name"),
                author=author[:255] if author else None,
                rating=float(rating) if rating is not None else None,
                content=content,
                published_at=published_at,
            )
        )

    return reviews
