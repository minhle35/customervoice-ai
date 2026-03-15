import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

import enum


class InsightType(str, enum.Enum):
    summary = "summary"
    trend = "trend"
    topic = "topic"
    recommendation = "recommendation"


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    insight_type: Mapped[InsightType] = mapped_column(
        Enum(InsightType, name="insight_type_enum"), nullable=False, index=True
    )

    # Scope — null platform means cross-platform aggregate
    business_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Time window this insight covers
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Content
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Flexible payload for charts / raw numbers
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Insight id={self.id} type={self.insight_type} business={self.business_id}>"
