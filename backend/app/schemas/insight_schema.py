from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.insight import InsightType


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class InsightOut(BaseModel):
    id: UUID
    insight_type: InsightType
    business_id: str
    platform: Optional[str]
    period_start: date
    period_end: date
    title: str
    content: str
    extra_data: Optional[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


class InsightListOut(BaseModel):
    total: int
    items: list[InsightOut]


# ---------------------------------------------------------------------------
# Summary / aggregation schemas (returned by /insights/summary)
# ---------------------------------------------------------------------------

class SentimentBreakdown(BaseModel):
    positive: int
    negative: int
    neutral: int
    avg_score: float


class TopicCount(BaseModel):
    topic: str
    count: int


class InsightSummaryOut(BaseModel):
    business_id: str
    period_start: date
    period_end: date
    total_reviews: int
    sentiment: SentimentBreakdown
    top_topics: list[TopicCount]


# ---------------------------------------------------------------------------
# Chat schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    business_id: str = Field(..., min_length=1, max_length=255)
    messages: list[ChatMessage] = Field(..., min_length=1)


class ChatResponse(BaseModel):
    answer: str
    sources: list[UUID] = Field(default_factory=list)  # review IDs used as context
