"""Integration tests for pipeline_runner — real DB, external APIs mocked."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.schemas.review_schema import ReviewCreate
from tests.conftest import make_review_create

_FETCH_TARGET = "pipelines.ingestion.google_reviews_ingestion.fetch_google_reviews"


# ---------------------------------------------------------------------------
# Fixtures — mock every external call, keep DB real
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_serpapi(mocker):
    return mocker.patch(
        _FETCH_TARGET,
        return_value=[
            make_review_create(platform_id="pipeline-r1", content="Pipeline test review."),
        ],
    )


@pytest.fixture()
def mock_sentiment(mocker):
    from pipelines.processing.sentiment_analysis import SentimentResult
    return mocker.patch(
        "pipelines.orchestration.pipeline_runner.analyze_sentiment_and_topics",
        return_value=SentimentResult(
            sentiment_score=0.85,
            sentiment_label="positive",
            topics=["food", "service"],
        ),
    )


@pytest.fixture()
def mock_embedding(mocker):
    return mocker.patch(
        "pipelines.orchestration.pipeline_runner.generate_embedding",
        return_value=[0.1] * 768,
    )


@pytest.fixture()
def mock_sleep(mocker):
    return mocker.patch("pipelines.orchestration.pipeline_runner.time.sleep")


@pytest.fixture()
def mock_get_session(mocker, db):
    """Redirect pipeline_runner's get_session() to the test DB session.

    Without this, ingest() and process_unprocessed() open their own connections
    and the test session can't see (or roll back) the written data.
    """
    @contextmanager
    def _use_test_db():
        yield db

    mocker.patch(
        "pipelines.orchestration.pipeline_runner.get_session",
        new=_use_test_db,
    )


# ---------------------------------------------------------------------------
# ingest()
# ---------------------------------------------------------------------------

class TestIngest:
    def test_stores_review_in_db(self, db, mock_serpapi, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest
        from app.services.review_service import ReviewService

        result = ingest("google", "biz-pipeline", {})

        assert result["processed"] == 1
        assert result["skipped"] == 0

        total, items = ReviewService(db).get_reviews()
        assert total == 1

    def test_sets_is_processed_true(self, db, mock_serpapi, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest
        from app.services.review_service import ReviewService

        ingest("google", "biz-pipeline", {})

        _, items = ReviewService(db).get_reviews()
        assert all(r.is_processed for r in items)

    def test_stores_sentiment_label(self, db, mock_serpapi, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest
        from app.services.review_service import ReviewService

        ingest("google", "biz-pipeline", {})

        _, items = ReviewService(db).get_reviews()
        assert items[0].sentiment_label.value == "positive"

    def test_skips_already_processed_review(self, db, mock_serpapi, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest

        ingest("google", "biz-pipeline", {})
        result = ingest("google", "biz-pipeline", {})

        assert result["skipped"] == 1
        assert result["processed"] == 0

    def test_deduplicates_same_platform_id(self, db, mocker, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest
        from app.services.review_service import ReviewService

        mocker.patch(
            _FETCH_TARGET,
            return_value=[
                make_review_create(platform_id="dup", content="First"),
                make_review_create(platform_id="dup", content="Duplicate"),
            ],
        )

        ingest("google", "biz-dup", {})

        total, _ = ReviewService(db).get_reviews()
        assert total == 1

    def test_stops_on_rate_limit(self, db, mocker, mock_embedding, mock_sleep, mock_get_session):
        from openai import RateLimitError
        from pipelines.orchestration.pipeline_runner import ingest
        from pipelines.processing.sentiment_analysis import SentimentResult

        call_count = 0

        def sentiment_side_effect(_text):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise RateLimitError("rate limited", response=mocker.MagicMock(), body={})
            return SentimentResult(sentiment_score=0.5, sentiment_label="neutral", topics=[])

        mocker.patch(
            _FETCH_TARGET,
            return_value=[
                make_review_create(platform_id="rl-1", content="First"),
                make_review_create(platform_id="rl-2", content="Second"),
            ],
        )
        mocker.patch(
            "pipelines.orchestration.pipeline_runner.analyze_sentiment_and_topics",
            side_effect=sentiment_side_effect,
        )

        result = ingest("google", "biz-rl", {})

        assert result["processed"] == 1
        assert result["rate_limited"] == 1

    def test_unsupported_platform_raises(self, db, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import ingest

        with pytest.raises((ValueError, KeyError)):
            ingest("tiktok", "biz-1", {})


# ---------------------------------------------------------------------------
# process_unprocessed()
# ---------------------------------------------------------------------------

class TestProcessUnprocessed:
    def test_processes_unprocessed_reviews(self, db, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import process_unprocessed
        from app.services.review_service import ReviewService

        svc = ReviewService(db)
        for i in range(3):
            svc.upsert_review(make_review_create(platform_id=f"unp-{i}"))
        db.flush()

        result = process_unprocessed(limit=10)

        assert result["processed"] == 3

    def test_respects_limit(self, db, mock_sentiment, mock_embedding, mock_sleep, mock_get_session):
        from pipelines.orchestration.pipeline_runner import process_unprocessed
        from app.services.review_service import ReviewService

        svc = ReviewService(db)
        for i in range(5):
            svc.upsert_review(make_review_create(platform_id=f"lim-{i}"))
        db.flush()

        result = process_unprocessed(limit=2)

        assert result["processed"] == 2
