from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.models.review import Platform
from app.schemas.review_schema import ReviewCreate

logger = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
DEFAULT_MAX_REVIEWS = 100
PAGE_DELAY_SECONDS = 1.0  # respectful delay between SerpAPI pages


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


def _parse_reviews_from_page(payload: dict, business_id: str, place_name: str | None) -> list[ReviewCreate]:
    """Parse one page of SerpAPI response into ReviewCreate objects."""
    reviews = []
    for item in payload.get("reviews", []):
        user = item.get("user") or item.get("author") or item.get("user_name")
        # SerpAPI returns user as a dict {"name": ..., "reviews": ..., "photos": ...}
        if isinstance(user, dict):
            author = user.get("name")
        else:
            author = str(user) if user else None

        content = item.get("snippet") or item.get("content") or item.get("text") or ""
        if not content.strip():
            continue

        rating = item.get("rating")
        published_at = _parse_datetime(
            item.get("timestamp") or item.get("time") or item.get("published_at")
        )
        platform_id = item.get("review_id") or item.get("id")
        if not platform_id:
            platform_id = _stable_id(str(author), str(published_at), content)

        reviews.append(
            ReviewCreate(
                platform=Platform.google,
                platform_id=str(platform_id),
                business_id=business_id,
                business_name=place_name,
                author=author[:255] if author else None,
                rating=float(rating) if rating is not None else None,
                content=content,
                published_at=published_at,
            )
        )
    return reviews


def fetch_google_reviews(business_id: str, params: dict) -> list[ReviewCreate]:
    """Fetch Google Maps reviews for a business, paginating until max_reviews is reached.

    Pagination:
        SerpAPI returns ~10 reviews per page with a `next_page_token` in
        `serpapi_pagination.next_page_token`. This function loops until
        either max_reviews is reached or no more pages exist.

    Args:
        business_id: Business identifier used as the DB foreign key.
        params:       Forwarded from the API request. Supports:
                        data_id        — SerpAPI data_id for the business (required)
                        hl             — language code (default: en)
                        sort_by        — 1=most relevant, 2=newest, 3=highest, 4=lowest
                        max_reviews    — cap on total reviews fetched (default: 100)
                        place_name     — stored in DB, not sent to SerpAPI
                        no_cache       — bypass SerpAPI cache (default: false)
    """
    api_key = get_settings().google_reviews_api_key
    if not api_key:
        raise ValueError("GOOGLE_REVIEWS_API_KEY is not set")

    max_reviews: int = int(params.get("max_reviews", DEFAULT_MAX_REVIEWS))

    # Only forward params that SerpAPI's google_maps_reviews engine accepts.
    SERPAPI_ALLOWED = {"data_id", "hl", "sort_by", "no_cache"}
    base_params = {
        "engine": "google_maps_reviews",
        "api_key": api_key,
        **{k: v for k, v in params.items() if k in SERPAPI_ALLOWED},
    }

    place_name: str | None = params.get("place_name")
    all_reviews: list[ReviewCreate] = []
    next_page_token: str | None = None
    page = 1

    with httpx.Client(timeout=30.0) as client:
        while True:
            query_params = {**base_params}
            if next_page_token:
                query_params["next_page_token"] = next_page_token

            logger.info(
                "Fetching Google reviews page %d for business_id=%s (collected=%d, max=%d)",
                page, business_id, len(all_reviews), max_reviews,
            )

            response = client.get(SERPAPI_ENDPOINT, params=query_params)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Re-raise without the request URL to avoid leaking the api_key.
                raise RuntimeError(
                    f"SerpAPI returned {exc.response.status_code} on page {page}: {exc.response.text}"
                ) from None

            payload = response.json()
            page_reviews = _parse_reviews_from_page(payload, business_id, place_name)
            all_reviews.extend(page_reviews)

            logger.info("Page %d returned %d reviews", page, len(page_reviews))

            if len(all_reviews) >= max_reviews:
                all_reviews = all_reviews[:max_reviews]
                logger.info("Reached max_reviews=%d, stopping pagination", max_reviews)
                break

            next_page_token = (
                payload.get("serpapi_pagination", {}).get("next_page_token")
            )
            if not next_page_token:
                logger.info("No more pages available after page %d", page)
                break

            page += 1
            time.sleep(PAGE_DELAY_SECONDS)

    logger.info(
        "Fetched %d total reviews across %d page(s) for business_id=%s",
        len(all_reviews), page, business_id,
    )
    return all_reviews
