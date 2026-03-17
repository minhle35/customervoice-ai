"""
Manual integration test: fetch real reviews from SerpAPI then run through the cleaning pipeline.

Shows a before/after diff for each review.

Run from backend/:
    uv run python scripts/test_clean_pipeline.py
    uv run python scripts/test_clean_pipeline.py "Bien Vinh Hao 2" vn
"""

from __future__ import annotations

import httpx
from dotenv import dotenv_values

from pipelines.processing.clean_reviews import clean_review_text

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


_ENV = dotenv_values(ROOT / ".env")
SERPAPI = "https://serpapi.com/search.json"

DEFAULT_QUERY = "Bien Vinh Hao 2"
DEFAULT_COUNTRY = "vn"
KNOWN_DATA_ID = "0x3177290034d53dff:0x9b5a177cedafc5bf"


def get_api_key() -> str:
    key = _ENV.get("GOOGLE_REVIEWS_API_KEY") or os.getenv("GOOGLE_REVIEWS_API_KEY")
    if not key:
        print("GOOGLE_REVIEWS_API_KEY not set in .env")
        sys.exit(1)
    return key


def resolve_data_id(api_key: str, query: str, country: str) -> str:
    """Use google_maps engine to find the data_id for a business."""
    resp = httpx.get(
        SERPAPI,
        params={
            "engine": "google_maps",
            "q": query,
            "api_key": api_key,
            "hl": "en",
            "gl": country,
        },
        timeout=15.0,
    )
    payload = resp.json()
    if "error" in payload:
        print(f"Maps search error: {payload['error']}")
        sys.exit(1)

    place = payload.get("place_results")
    if place and isinstance(place, dict) and place.get("data_id"):
        return place["data_id"]

    results = payload.get("local_results", [])
    if results and results[0].get("data_id"):
        return results[0]["data_id"]

    print("Could not resolve data_id — falling back to known ID")
    return KNOWN_DATA_ID


def fetch_raw_reviews(api_key: str, data_id: str) -> list[dict]:
    resp = httpx.get(
        SERPAPI,
        params={
            "engine": "google_maps_reviews",
            "data_id": data_id,
            "api_key": api_key,
            "hl": "en",
            "sort_by": "newestFirst",
        },
        timeout=15.0,
    )
    payload = resp.json()
    if "error" in payload:
        print(f"Reviews fetch error: {payload['error']}")
        sys.exit(1)
    return payload.get("reviews", [])


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    country = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_COUNTRY

    api_key = get_api_key()

    print(f"Resolving data_id for: {query!r}")
    data_id = resolve_data_id(api_key, query, country)
    print(f"data_id: {data_id}")

    print("\nFetching reviews")
    raw_reviews = fetch_raw_reviews(api_key, data_id)
    print(f"Fetched {len(raw_reviews)} review(s)\n")

    if not raw_reviews:
        print("No reviews to process.")
        return

    print("=" * 70)
    for i, item in enumerate(raw_reviews, 1):
        user = item.get("user", {})
        author = user.get("name") if isinstance(user, dict) else str(user or "unknown")
        rating = item.get("rating", "n/a")
        raw_text = item.get("snippet") or item.get("content") or item.get("text") or ""

        result = clean_review_text(raw_text)

        print(f"[{i}] {author} | {rating}★")
        print(f"  RAW  ({len(raw_text):>4} chars): {repr(raw_text[:120])}")
        print(
            f"  CLEAN({len(result.cleaned_text):>4} chars): {repr(result.cleaned_text[:120])}"
        )
        print(f"  LANG : {result.language}")

        changed = raw_text != result.cleaned_text
        print(f"  DIFF : {'changed' if changed else 'no change'}")
        print()

    print("=" * 70)
    print(f"Done. Processed {len(raw_reviews)} review(s).")


if __name__ == "__main__":
    main()
