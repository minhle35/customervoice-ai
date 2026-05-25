"""API tests for GET /api/reviews and related endpoints."""

from __future__ import annotations

import pytest

from app.services.review_service import ReviewService
from tests.conftest import make_review_create


@pytest.fixture()
def seeded(db):
    """Insert 3 reviews across 2 businesses into the test DB."""
    svc = ReviewService(db)
    svc.upsert_review(make_review_create(platform_id="r1", business_id="biz-A", business_name="Café Alpha"))
    svc.upsert_review(make_review_create(platform_id="r2", business_id="biz-A", business_name="Café Alpha"))
    svc.upsert_review(make_review_create(platform_id="r3", business_id="biz-B", business_name="Beta Bistro"))
    db.flush()
    return db


# ---------------------------------------------------------------------------
# GET /api/reviews
# ---------------------------------------------------------------------------

class TestListReviews:
    def test_returns_200_with_empty_list(self, client):
        resp = client.get("/api/reviews")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_returns_all_reviews(self, client, seeded):
        resp = client.get("/api/reviews")
        assert resp.json()["total"] == 3

    def test_response_item_shape(self, client, seeded):
        item = client.get("/api/reviews").json()["items"][0]
        for field in ("id", "platform", "content", "business_id", "is_processed"):
            assert field in item

    def test_filter_by_business_id(self, client, seeded):
        resp = client.get("/api/reviews?business_id=biz-A")
        assert resp.json()["total"] == 2

    def test_filter_by_platform(self, client, seeded):
        resp = client.get("/api/reviews?platform=google")
        assert resp.json()["total"] == 3

    def test_filter_unknown_platform_returns_422(self, client):
        resp = client.get("/api/reviews?platform=tiktok")
        assert resp.status_code == 422

    def test_pagination_limit(self, client, seeded):
        resp = client.get("/api/reviews?limit=2")
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3

    def test_pagination_offset(self, client, seeded):
        all_ids = [r["id"] for r in client.get("/api/reviews").json()["items"]]
        paged = client.get("/api/reviews?limit=2&offset=1").json()["items"]
        assert paged[0]["id"] == all_ids[1]


# ---------------------------------------------------------------------------
# GET /api/reviews/{id}
# ---------------------------------------------------------------------------

class TestGetReviewById:
    def test_returns_review(self, client, seeded):
        first_id = client.get("/api/reviews").json()["items"][0]["id"]
        resp = client.get(f"/api/reviews/{first_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == first_id

    def test_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/reviews/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_returns_422_for_invalid_uuid(self, client):
        resp = client.get("/api/reviews/not-a-uuid")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/reviews/businesses
# ---------------------------------------------------------------------------

class TestListBusinesses:
    def test_returns_empty_when_no_reviews(self, client):
        resp = client.get("/api/reviews/businesses")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_distinct_businesses(self, client, seeded):
        businesses = client.get("/api/reviews/businesses").json()
        ids = {b["business_id"] for b in businesses}
        assert ids == {"biz-A", "biz-B"}

    def test_includes_business_name(self, client, seeded):
        businesses = client.get("/api/reviews/businesses").json()
        names = {b["business_name"] for b in businesses}
        assert "Café Alpha" in names
