"""Integration tests for ReviewService — real test DB, transaction rollback per test."""

from __future__ import annotations

import uuid

import pytest

from app.models.review import Platform, SentimentLabel
from app.schemas.review_schema import ReviewCreate, ReviewUpdate
from app.services.review_service import ReviewService
from tests.conftest import make_review_create


@pytest.fixture()
def svc(db):
    return ReviewService(db)


@pytest.fixture()
def review(svc):
    """A single persisted review, ready for use in tests."""
    return svc.upsert_review(make_review_create())


# ---------------------------------------------------------------------------
# upsert_review
# ---------------------------------------------------------------------------

class TestUpsertReview:
    def test_inserts_new_review(self, svc):
        r = svc.upsert_review(make_review_create())
        assert r.id is not None
        assert r.content == "Great experience overall."

    def test_deduplicates_on_platform_and_platform_id(self, svc):
        svc.upsert_review(make_review_create(platform_id="dup-1"))
        svc.upsert_review(make_review_create(platform_id="dup-1"))
        total, _ = svc.get_reviews()
        assert total == 1

    def test_returns_existing_on_duplicate(self, svc):
        first = svc.upsert_review(make_review_create(platform_id="dup-2"))
        second = svc.upsert_review(make_review_create(platform_id="dup-2"))
        assert first.id == second.id

    def test_stores_business_name(self, svc):
        r = svc.upsert_review(make_review_create(business_name="My Café"))
        assert r.business_name == "My Café"

    def test_stores_none_rating(self, svc):
        r = svc.upsert_review(make_review_create(rating=None))
        assert r.rating is None

    def test_is_processed_defaults_false(self, svc):
        r = svc.upsert_review(make_review_create())
        assert r.is_processed is False


# ---------------------------------------------------------------------------
# mark_processed
# ---------------------------------------------------------------------------

class TestMarkProcessed:
    def test_sets_is_processed_true(self, svc, review):
        svc.mark_processed(review.id, ReviewUpdate(is_processed=True))
        db_review = svc.get_by_id(review.id)
        assert db_review.is_processed is True

    def test_stores_sentiment_score_and_label(self, svc, review):
        svc.mark_processed(
            review.id,
            ReviewUpdate(sentiment_score=0.8, sentiment_label="positive", is_processed=True),
        )
        db_review = svc.get_by_id(review.id)
        assert db_review.sentiment_score == pytest.approx(0.8)
        assert db_review.sentiment_label == SentimentLabel.positive

    def test_stores_topics_as_list(self, svc, review):
        svc.mark_processed(
            review.id,
            ReviewUpdate(topics=["food", "service"], is_processed=True),
        )
        db_review = svc.get_by_id(review.id)
        assert db_review.topics == ["food", "service"]

    def test_raises_on_unknown_id(self, svc):
        with pytest.raises(Exception):
            svc.mark_processed(uuid.uuid4(), ReviewUpdate(is_processed=True))


# ---------------------------------------------------------------------------
# get_unprocessed_reviews
# ---------------------------------------------------------------------------

class TestGetUnprocessedReviews:
    def test_returns_only_unprocessed(self, svc):
        r1 = svc.upsert_review(make_review_create(platform_id="u1"))
        r2 = svc.upsert_review(make_review_create(platform_id="u2"))
        svc.upsert_review(make_review_create(platform_id="u3"))
        svc.mark_processed(r1.id, ReviewUpdate(is_processed=True))
        svc.mark_processed(r2.id, ReviewUpdate(is_processed=True))

        unprocessed = svc.get_unprocessed_reviews(limit=10)
        assert len(unprocessed) == 1

    def test_respects_limit(self, svc):
        for i in range(5):
            svc.upsert_review(make_review_create(platform_id=f"lim-{i}"))

        result = svc.get_unprocessed_reviews(limit=3)
        assert len(result) == 3

    def test_returns_empty_when_all_processed(self, svc):
        r = svc.upsert_review(make_review_create(platform_id="done"))
        svc.mark_processed(r.id, ReviewUpdate(is_processed=True))

        assert svc.get_unprocessed_reviews(limit=10) == []


# ---------------------------------------------------------------------------
# get_reviews
# ---------------------------------------------------------------------------

class TestGetReviews:
    def test_returns_all_reviews(self, svc):
        svc.upsert_review(make_review_create(platform_id="g1"))
        svc.upsert_review(make_review_create(platform_id="g2"))
        total, items = svc.get_reviews()
        assert total == 2

    def test_filters_by_business_id(self, svc):
        svc.upsert_review(make_review_create(platform_id="b1", business_id="biz-A"))
        svc.upsert_review(make_review_create(platform_id="b2", business_id="biz-B"))
        total, items = svc.get_reviews(business_id="biz-A")
        assert total == 1
        assert items[0].business_id == "biz-A"

    def test_filters_by_platform(self, svc):
        svc.upsert_review(make_review_create(platform_id="p1", platform="google"))
        total, _ = svc.get_reviews(platform=Platform.google)
        assert total == 1

    def test_pagination_limit(self, svc):
        for i in range(5):
            svc.upsert_review(make_review_create(platform_id=f"page-{i}"))
        total, items = svc.get_reviews(limit=3)
        assert len(items) == 3
        assert total == 5

    def test_total_unaffected_by_limit(self, svc):
        for i in range(4):
            svc.upsert_review(make_review_create(platform_id=f"tot-{i}"))
        total, items = svc.get_reviews(limit=2, offset=0)
        assert total == 4

    def test_returns_empty_when_no_reviews(self, svc):
        total, items = svc.get_reviews()
        assert total == 0
        assert items == []


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------

class TestGetById:
    def test_returns_review(self, svc, review):
        found = svc.get_by_id(review.id)
        assert found.id == review.id

    def test_returns_none_for_unknown_id(self, svc):
        assert svc.get_by_id(uuid.uuid4()) is None
