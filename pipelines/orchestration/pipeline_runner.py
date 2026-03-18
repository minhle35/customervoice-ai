from __future__ import annotations

import logging
import time

from openai import RateLimitError

from app.config import settings
from app.database.database import SessionLocal
from app.models.review import Platform
from app.schemas.review_schema import ReviewUpdate
from app.services.embedding_service import EmbeddingService
from app.services.review_service import ReviewService
from pipelines.embeddings.generate_embeddings import generate_embedding
from pipelines.ingestion.facebook_ingestion import fetch_facebook_reviews
from pipelines.ingestion.google_reviews_ingestion import fetch_google_reviews
from pipelines.ingestion.reddit_ingestion import fetch_reddit_reviews
from pipelines.processing.clean_reviews import clean_review_text
from pipelines.processing.sentiment_analysis import analyze_sentiment_and_topics

logger = logging.getLogger(__name__)


def _process_review(review_service, embedding_service, stored) -> bool:
    """Run clean → sentiment → embed for a single stored review.

    Returns True if processed, False if skipped (already done).
    Raises RateLimitError so callers can stop the loop cleanly.
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
        model=settings.embedding_model,
    )
    return True


def ingest(platform: str | Platform, business_id: str, params: dict) -> dict:
    platform_value = Platform(platform) if isinstance(platform, str) else platform

    if platform_value == Platform.google:
        reviews = fetch_google_reviews(business_id, params)
    elif platform_value == Platform.reddit:
        reviews = fetch_reddit_reviews(business_id, params)
    elif platform_value == Platform.facebook:
        reviews = fetch_facebook_reviews(business_id, params)
    else:
        raise ValueError(f"Unsupported platform: {platform_value}")

    processed = 0
    skipped = 0
    rate_limited = 0

    with SessionLocal() as db:
        review_service = ReviewService(db)
        embedding_service = EmbeddingService(db)

        for review in reviews:
            stored = review_service.upsert_review(review)
            try:
                if _process_review(review_service, embedding_service, stored):
                    processed += 1
                    time.sleep(3)  # ~20 RPM free tier — stay well under the limit
                else:
                    skipped += 1
            except RateLimitError:
                rate_limited += 1
                logger.warning(
                    "Rate limited by LLM provider — stopping early. "
                    "%d review(s) left unprocessed; run process_unprocessed to finish.",
                    len(reviews) - processed - skipped - rate_limited,
                )
                break

    return {"processed": processed, "skipped": skipped, "rate_limited": rate_limited}


def process_unprocessed(limit: int = 100) -> dict:
    processed = 0
    rate_limited = 0

    with SessionLocal() as db:
        review_service = ReviewService(db)
        embedding_service = EmbeddingService(db)

        unprocessed = review_service.get_unprocessed_reviews(limit=limit)
        for stored in unprocessed:
            try:
                if _process_review(review_service, embedding_service, stored):
                    processed += 1
                    time.sleep(3)
            except RateLimitError:
                rate_limited += 1
                logger.warning(
                    "Rate limited by LLM provider — stopping early. "
                    "%d review(s) left unprocessed; run process_unprocessed again to finish.",
                    len(unprocessed) - processed - rate_limited,
                )
                break

    return {"processed": processed, "rate_limited": rate_limited}
