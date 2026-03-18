"""
Integration test for GET /api/reviews and GET /api/reviews/{id}.

Seeds 3 reviews, hits the real API, then cleans up.

Run from backend/ with the FastAPI server running (uv run uvicorn app.main:app --reload):
    uv run python scripts/test_routes_reviews.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# fmt: off
import httpx  # noqa: E402
from app.database.database import SessionLocal  # noqa: E402
from app.models.review import Platform, Review, SentimentLabel  # noqa: E402
from app.schemas.review_schema import ReviewCreate, ReviewUpdate  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402
# fmt: on

BASE_URL = "http://localhost:8000"
BUSINESS_ID = "route-test-bien-vinh-hao-2"

SAMPLE_REVIEWS = [
    ReviewCreate(
        platform=Platform.google,
        platform_id="route-test-001",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Alice",
        rating=5.0,
        content="Great ocean view and fresh seafood",
    ),
    ReviewCreate(
        platform=Platform.google,
        platform_id="route-test-002",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Bob",
        rating=3.0,
        content="Pricey but decent food",
    ),
    ReviewCreate(
        platform=Platform.google,
        platform_id="route-test-003",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Charlie",
        rating=4.0,
        content="Food is expensive but very fresh",
    ),
]


def ok(label):
    print(f"  PASS  {label}")


def fail(label, detail):
    print(f"  FAIL  {label}: {detail}")


def seed_and_enrich(db) -> list:
    """Insert 3 reviews, mark first one as processed."""
    svc = ReviewService(db)
    reviews = [svc.upsert_review(r) for r in SAMPLE_REVIEWS]
    svc.mark_processed(
        reviews[0].id,
        ReviewUpdate(
            sentiment_score=0.9,
            sentiment_label=SentimentLabel.positive,
            topics=["ocean view", "seafood"],
            is_processed=True,
        ),
    )
    return reviews


def cleanup(db, ids: list):
    db.query(Review).filter(Review.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    print(f"\nCleaned up {len(ids)} test row(s).")


def main():
    print("=" * 60)
    print("GET /api/reviews — integration tests")
    print("=" * 60)

    # Seed DB
    with SessionLocal() as db:
        reviews = seed_and_enrich(db)
        ids = [r.id for r in reviews]
        first_id = ids[0]

    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    try:
        # ------------------------------------------------------------------
        # 1. List all reviews — no filter
        # ------------------------------------------------------------------
        print("\n[1] GET /api/reviews (no filter)")
        resp = client.get("/api/reviews", params={"business_id": BUSINESS_ID})
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] == 3 and len(data["items"]) == 3:
                ok(f"total=3, items=3")
            else:
                fail("list all", f"expected total=3, got {data}")
        else:
            fail("list all", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 2. Filter by is_processed=true
        # ------------------------------------------------------------------
        print("\n[2] GET /api/reviews?is_processed=true")
        resp = client.get("/api/reviews", params={"business_id": BUSINESS_ID, "is_processed": "true"})
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] == 1 and data["items"][0]["author"] == "Alice":
                ok(f"total=1, author=Alice")
            else:
                fail("is_processed filter", f"unexpected: {data}")
        else:
            fail("is_processed filter", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 3. Filter by is_processed=false
        # ------------------------------------------------------------------
        print("\n[3] GET /api/reviews?is_processed=false")
        resp = client.get("/api/reviews", params={"business_id": BUSINESS_ID, "is_processed": "false"})
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] == 2:
                ok("total=2 unprocessed")
            else:
                fail("unprocessed filter", f"expected 2, got {data['total']}")
        else:
            fail("unprocessed filter", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 4. Pagination — limit=1, offset=0
        # ------------------------------------------------------------------
        print("\n[4] GET /api/reviews?limit=1&offset=0")
        resp = client.get("/api/reviews", params={"business_id": BUSINESS_ID, "limit": 1, "offset": 0})
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] == 3 and len(data["items"]) == 1:
                ok(f"total=3, items=1 (paginated)")
            else:
                fail("pagination", f"unexpected: {data}")
        else:
            fail("pagination", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 5. Filter by platform
        # ------------------------------------------------------------------
        print("\n[5] GET /api/reviews?platform=google")
        resp = client.get("/api/reviews", params={"business_id": BUSINESS_ID, "platform": "google"})
        if resp.status_code == 200:
            data = resp.json()
            if data["total"] == 3:
                ok("platform=google returns all 3")
            else:
                fail("platform filter", f"expected 3, got {data['total']}")
        else:
            fail("platform filter", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 6. GET /api/reviews/{id} — found
        # ------------------------------------------------------------------
        print("\n[6] GET /api/reviews/{id} — found")
        resp = client.get(f"/api/reviews/{first_id}")
        if resp.status_code == 200:
            data = resp.json()
            if (
                data["id"] == str(first_id)
                and data["author"] == "Alice"
                and data["sentiment_score"] == 0.9
                and data["sentiment_label"] == "positive"
                and data["topics"] == ["ocean view", "seafood"]
                and data["is_processed"] is True
            ):
                ok("all fields correct including AI-enriched data")
            else:
                fail("get by id", f"unexpected: {data}")
        else:
            fail("get by id", f"HTTP {resp.status_code}: {resp.text}")

        # ------------------------------------------------------------------
        # 7. GET /api/reviews/{id} — not found
        # ------------------------------------------------------------------
        print("\n[7] GET /api/reviews/{id} — not found")
        resp = client.get(f"/api/reviews/{uuid.uuid4()}")
        if resp.status_code == 404:
            ok("returns 404 for unknown id")
        else:
            fail("404 case", f"expected 404, got {resp.status_code}")

    finally:
        client.close()
        with SessionLocal() as db:
            cleanup(db, ids)

    print("\n" + "=" * 60)
    print("All tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
