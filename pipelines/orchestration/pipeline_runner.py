from __future__ import annotations

import logging
import time

from openai import RateLimitError

from app.config import get_settings
from app.database.database import (
    get_session,
)  # Since we call from Celery - no FastAPI context, need explicit context manager for DB sessions
from app.integrations.registry import get_handler
from app.models.review import Platform, Review
from app.schemas.review_schema import ReviewCreate, ReviewUpdate
from app.services.embedding_service import EmbeddingService
from app.services.review_service import ReviewService
from pipelines.embeddings.generate_embeddings import generate_embedding
from pipelines.processing.clean_reviews import clean_review_text
from pipelines.processing.sentiment_analysis import analyze_sentiment_and_topics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Celery progress emitter
# ---------------------------------------------------------------------------


def _emit(task, stage: str, **meta) -> None:
    """Push a PROGRESS state to Celery result backend.

    Accepts arbitrary keyword args as meta so each stage can send
    different fields without changing the function signature.

    Stages and their meta fields:
      fetching   — (no extra fields)
      saving     — total: int, saved: int
      processing — total: int, processed: int, skipped: int, rate_limited: int
      rate_limited — same as processing
    """
    if task is None:
        return
    task.update_state(state="PROGRESS", meta={"stage": stage, **meta})


# ---------------------------------------------------------------------------
# Phase 1 — fetch from external platform
# ---------------------------------------------------------------------------


def _fetch_reviews(
    platform_value: Platform, business_id: str, params: dict, task
) -> list[ReviewCreate]:
    """Call the appropriate ingestion adapter and return raw ReviewCreate objects."""
    _emit(task, "fetching")
    handler = get_handler(platform_value.value)
    return handler.fetch_reviews(business_id, params)


# ---------------------------------------------------------------------------
# Phase 2 — persist all reviews to DB before any LLM call
# ---------------------------------------------------------------------------


def _save_reviews(
    review_service: ReviewService, reviews: list[ReviewCreate], task
) -> list[Review]:
    """Upsert every fetched review into the DB.

    All reviews are saved before sentiment/embedding begins so that:
    - A rate limit in Phase 3 never causes data loss
    - The frontend can render the reviews table as soon as this phase ends
    - process_unprocessed() can resume from exactly where Phase 3 left off

    Emits `saving` progress so the frontend can show a save progress bar.
    """
    total = len(reviews)
    stored_reviews: list[Review] = []

    for i, review in enumerate(reviews):
        stored = review_service.upsert_review(review)
        stored_reviews.append(stored)
        _emit(task, "saving", total=total, saved=i + 1)

    logger.info("Saved %d reviews to database", total)
    return stored_reviews


# ---------------------------------------------------------------------------
# Phase 3 — sentiment analysis + embedding (LLM calls, rate-limit-sensitive)
# ---------------------------------------------------------------------------


def _process_single_review(
    review_service: ReviewService,
    embedding_service: EmbeddingService,
    stored: Review,
) -> bool:
    """Run clean → sentiment → embed for one stored review.

    Returns True if processed, False if skipped (already done).
    Raises RateLimitError so the caller can stop the loop cleanly.
    """
    if stored.is_processed:
        return False

    clean_result = clean_review_text(stored.content)
    analysis = analyze_sentiment_and_topics(clean_result.cleaned_text)
    review_service.mark_processed(
        stored.id,
        ReviewUpdate(
            sentiment_score=analysis.sentiment_score,
            sentiment_label=analysis.sentiment_label,
            topics=analysis.topics,
            is_processed=True,
        ),
    )

    embedding = generate_embedding(clean_result.cleaned_text)
    embedding_service.upsert_embedding(
        review_id=stored.id,
        embedding=embedding,
        model=get_settings().embedding_model,
    )
    return True


def _process_reviews(
    review_service: ReviewService,
    embedding_service: EmbeddingService,
    stored_reviews: list[Review],
    task,
) -> dict:
    """Run sentiment + embedding for every unprocessed review.

    Stops early on RateLimitError — remaining reviews stay in DB with
    is_processed=False and can be resumed via process_unprocessed().
    """
    total = len(stored_reviews)
    processed = 0
    skipped = 0
    rate_limited = 0

    for stored in stored_reviews:
        try:
            if _process_single_review(review_service, embedding_service, stored):
                processed += 1
                time.sleep(3)  # ~20 RPM free tier — stay under the limit
            else:
                skipped += 1
        except RateLimitError:
            rate_limited += 1
            logger.warning(
                "Rate limited — stopping early. %d review(s) left unprocessed; "
                "run process_unprocessed to finish.",
                total - processed - skipped - rate_limited,
            )
            _emit(
                task,
                "rate_limited",
                total=total,
                processed=processed,
                skipped=skipped,
                rate_limited=rate_limited,
            )
            break

        _emit(
            task,
            "processing",
            total=total,
            processed=processed,
            skipped=skipped,
            rate_limited=rate_limited,
        )

    return {
        "total": total,
        "processed": processed,
        "skipped": skipped,
        "rate_limited": rate_limited,
    }


# ---------------------------------------------------------------------------
# Public entry points (called by Celery tasks)
# ---------------------------------------------------------------------------


def ingest(platform: str | Platform, business_id: str, params: dict, task=None) -> dict:
    """Full ingestion pipeline: fetch → save all → process all.

    Phase 1 (fetch):   calls SerpAPI, returns ReviewCreate list in memory.
    Phase 2 (save):    upserts every review to DB before any LLM call —
                       guarantees no data loss if rate limiting hits in Phase 3.
    Phase 3 (process): sentiment + embedding per review; stops on RateLimitError,
                       remaining reviews stay as is_processed=False for recovery.
    """
    platform_value = Platform(platform) if isinstance(platform, str) else platform

    reviews = _fetch_reviews(platform_value, business_id, params, task)

    with get_session() as db:
        review_service = ReviewService(db)
        embedding_service = EmbeddingService(db)

        stored_reviews = _save_reviews(review_service, reviews, task)
        return _process_reviews(review_service, embedding_service, stored_reviews, task)


def process_unprocessed(limit: int = 100) -> dict:
    """Resume processing reviews saved but not yet sentiment-analysed.

    Used to recover from rate limiting or re-run failed processing.
    """
    processed = 0
    rate_limited = 0

    with get_session() as db:
        review_service = ReviewService(db)
        embedding_service = EmbeddingService(db)

        unprocessed = review_service.get_unprocessed_reviews(limit=limit)
        total = len(unprocessed)

        for stored in unprocessed:
            try:
                if _process_single_review(review_service, embedding_service, stored):
                    processed += 1
                    time.sleep(3)
            except RateLimitError:
                rate_limited += 1
                logger.warning(
                    "Rate limited — stopping early. %d review(s) left unprocessed; "
                    "run process_unprocessed again to finish.",
                    total - processed - rate_limited,
                )
                break

    return {"total": total, "processed": processed, "rate_limited": rate_limited}
