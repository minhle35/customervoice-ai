"""
ReviewService provides abstracted database operations for the Review model,
including
    ├── upsert_review(ReviewCreate)         → INSERT or skip duplicate
    ├── mark_processed(id, ReviewUpdate)    → write sentiment/topics, flip is_processed
    ├── get_unprocessed_reviews(limit)      → fetch batch for backfill
    ├── get_reviews(filters, pagination)    → list with optional filters
    └── get_by_id(id)                       → single lookup

    upsert_review() deduplicates on (platform, platform_id) - ensures idempotent ingestion by
    checking for existing reviews with the same (platform, platform_id) before inserting.

    mark_processed() allows partial updates to enrich reviews with AI-generated insights.

    get_unprocessed_reviews() supports batch processing for backfilling.

    get_reviews() provides flexible querying with pagination

    get_by_id() enables direct access to specific reviews.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.review import Platform, Review
from app.schemas.review_schema import ReviewCreate, ReviewUpdate


class ReviewService:
    def __init__(self, db: Session):
        self.db = db

    def upsert_review(self, data: ReviewCreate) -> Review:
        """Insert a new review or return the existing one if already ingested.

        Deduplication key: (platform, platform_id) — guarantees the same
        review from the same source is never stored twice.
        """
        existing = self.db.execute(
            select(Review).where(
                Review.platform == data.platform,
                Review.platform_id == data.platform_id,
            )
        ).scalar_one_or_none()

        if existing:
            return existing

        review = Review(
            id=uuid.uuid4(),
            platform=data.platform,
            platform_id=data.platform_id,
            business_id=data.business_id,
            business_name=data.business_name,
            author=data.author,
            rating=data.rating,
            content=data.content,
            published_at=data.published_at,
            is_processed=False,
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def mark_processed(self, review_id: uuid.UUID, update: ReviewUpdate) -> Review:
        """Write AI-enriched fields and flip is_processed=True."""
        review = self.db.get(Review, review_id)
        if review is None:
            raise ValueError(f"Review {review_id} not found")

        if update.sentiment_score is not None:
            review.sentiment_score = update.sentiment_score
        if update.sentiment_label is not None:
            review.sentiment_label = update.sentiment_label
        if update.topics is not None:
            review.topics = update.topics
        if update.is_processed is not None:
            review.is_processed = update.is_processed

        self.db.commit()
        self.db.refresh(review)
        return review

    def get_unprocessed_reviews(self, limit: int = 100) -> list[Review]:
        """Fetch a batch of reviews that haven't been enriched yet."""
        result = self.db.execute(
            select(Review)
            .where(Review.is_processed == False)  # noqa: E712
            .order_by(Review.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    def get_reviews(
        self,
        business_id: Optional[str] = None,
        platform: Optional[Platform] = None,
        is_processed: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[Review]]:
        """List reviews with optional filters. Returns (total, items)."""
        query = select(Review)
        count_query = select(func.count()).select_from(Review)

        if business_id:
            query = query.where(Review.business_id == business_id)
            count_query = count_query.where(Review.business_id == business_id)
        if platform:
            query = query.where(Review.platform == platform)
            count_query = count_query.where(Review.platform == platform)
        if is_processed is not None:
            query = query.where(Review.is_processed == is_processed)
            count_query = count_query.where(Review.is_processed == is_processed)

        total = self.db.execute(count_query).scalar_one()
        items = list(
            self.db.execute(
                query.order_by(Review.published_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return total, items

    def get_by_id(self, review_id: uuid.UUID) -> Optional[Review]:
        return self.db.get(Review, review_id)
