from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Enum,
    Float,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.embedding import ReviewEmbedding


class Platform(str, enum.Enum):
    google = "google"
    reddit = "reddit"
    facebook = "facebook"


class SentimentLabel(str, enum.Enum):
    positive = "positive"
    negative = "negative"
    neutral = "neutral"


class Review(Base):
    """SQLAlchemy model - represents a customer review - later we create a SQLAlchemy ORM object of Review"""

    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Which platform this came from and its native ID there
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform_enum"), nullable=False, index=True
    )
    platform_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Business / location this review targets
    business_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business_name: Mapped[str] = mapped_column(String(512), nullable=False)

    # Review content
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)  # 1-5 or None
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # AI-enriched fields (populated after processing)
    sentiment_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # -1.0 to 1.0
    sentiment_label: Mapped[SentimentLabel | None] = mapped_column(
        Enum(SentimentLabel, name="sentiment_label_enum"), nullable=True
    )
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # Processing state
    is_processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set once entity/relationship extraction (GraphRAG indexing) has run for
    # this review. Deliberately separate from is_processed — extraction is a
    # distinct, independently-resumable Celery stage (see
    # pipelines/orchestration/pipeline_runner.py::extract_unprocessed_graph_entities)
    # so it doesn't compete with the sentiment/embedding rate limit budget.
    graph_extracted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    embedding: Mapped[ReviewEmbedding | None] = relationship(
        "ReviewEmbedding",
        back_populates="review",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Review id={self.id} platform={self.platform} rating={self.rating}>"
