from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.review import Platform, SentimentLabel


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class ReviewCreate(BaseModel):
    platform: Platform
    platform_id: str = Field(..., min_length=1, max_length=255)
    business_id: str = Field(..., min_length=1, max_length=255)
    business_name: Optional[str] = Field(None, max_length=512)
    author: Optional[str] = Field(None, max_length=255)
    rating: Optional[float] = Field(None, ge=1.0, le=5.0)
    content: str = Field(..., min_length=1)
    published_at: Optional[datetime] = None

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v.strip()


class ReviewUpdate(BaseModel):
    sentiment_score: Optional[float] = Field(None, ge=-1.0, le=1.0)
    sentiment_label: Optional[SentimentLabel] = None
    topics: Optional[list[str]] = None
    is_processed: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ReviewOut(BaseModel):
    """Pydantic model representing SQLAlchemy Review ORM object, used for API responses."""

    id: UUID
    platform: Platform
    platform_id: str
    business_id: str
    business_name: Optional[str]
    author: Optional[str]
    rating: Optional[float]
    content: str
    published_at: Optional[datetime]
    sentiment_score: Optional[float]
    sentiment_label: Optional[SentimentLabel]
    topics: Optional[list[str]]
    is_processed: bool
    created_at: datetime
    updated_at: datetime

    # Enable loading from ORM objects directly
    model_config = {"from_attributes": True}


class ReviewListOut(BaseModel):
    total: int
    items: list[ReviewOut]


# ---------------------------------------------------------------------------
# Ingestion trigger schema
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    platform: Platform
    business_id: str = Field(..., min_length=1, max_length=255)
    # Platform-specific query params passed through to the ingestion pipeline
    params: dict = Field(default_factory=dict)
