"""
Smoke test for SerpAPI key + Google Maps reviews fetch.

Usage:
    # Just verify key is valid
    uv run python scripts/check_serpapi_key.py

    # Verify key + find data_id + fetch reviews
    uv run python scripts/check_serpapi_key.py "Bien Vinh Hao 2" vn
    uv run python scripts/check_serpapi_key.py "coffee shop Sydney" au
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
SERPAPI = "https://serpapi.com/search.json"


def check_key(api_key: str) -> bool:
    resp = httpx.get(
        "https://serpapi.com/account", params={"api_key": api_key}, timeout=10.0
    )
    data = resp.json()
    if "error" in data:
        print(f"Key rejected: {data['error']}")
        return False
    print(
        f"Key valid | Plan: {data.get('plan_name')} | Searches left: {data.get('searches_left', '?')}"
    )
    return True


def find_data_id(api_key: str, query: str, country: str = "us") -> str | None:
    """Search Google Maps for a business and return its data_id."""
    print(f"\nSearching Google Maps for: {query!r} (country: {country})")
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
        print(f"Search error: {payload['error']}")
        return None

    # SerpAPI returns either place_results (single match) or local_results (list)
    place = payload.get("place_results")
    if place and isinstance(place, dict):
        data_id = place.get("data_id")
        print(f"Found: {place.get('title')} | data_id: {data_id}")
        return data_id

    results = payload.get("local_results", [])
    if not results:
        print("No results found. Try a different query or country code.")
        return None

    print(f"Found {len(results)} result(s):")
    for r in results[:3]:
        print(f"  {r.get('title')} | {r.get('address')} | data_id: {r.get('data_id')}")
    return results[0].get("data_id")


def fetch_reviews(api_key: str, data_id: str) -> None:
    """Fetch reviews using a valid data_id."""
    print(f"\nFetching reviews (data_id: {data_id})")
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
        print(f"Reviews error: {payload['error']}")
        return

    reviews = payload.get("reviews", [])
    print(f"Reviews returned: {len(reviews)}")
    for r in reviews[:3]:
        user = r.get("user", {})
        name = user.get("name") if isinstance(user, dict) else str(user)
        print(
            f"  [{r.get('rating')}★] {name or 'n/a'}: {str(r.get('snippet') or r.get('text') or '')[:100]}"
        )


def main() -> None:
    api_key = _ENV.get("GOOGLE_REVIEWS_API_KEY") or os.getenv("GOOGLE_REVIEWS_API_KEY")
    if not api_key:
        print("GOOGLE_REVIEWS_API_KEY is not set in .env")
        sys.exit(1)

    print(f"Key: {api_key[:8]}{'*' * (len(api_key) - 8)}")
    if not check_key(api_key):
        sys.exit(1)

    if len(sys.argv) < 2:
        print("\nPass a business name to also test review fetching:")
        print(
            '  uv run python scripts/check_serpapi_key.py "business name" [country_code]'
        )
        return

    query = sys.argv[1]
    country = sys.argv[2] if len(sys.argv) > 2 else "us"
    data_id = find_data_id(api_key, query, country)
    if data_id:
        fetch_reviews(api_key, data_id)
        print("\nUse this data_id in your ingestion params:")
        print(f'  "params": {{"data_id": "{data_id}", "place_name": "{query}"}}')


if __name__ == "__main__":
    main()
