import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# text-embedding-3-large produces 3072-dimension vectors
EMBEDDING_DIMENSIONS = 1536


class ReviewEmbedding(Base):
    __tablename__ = "review_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=False
    )
    model: Mapped[str] = mapped_column(
        String(128), nullable=False, default="text-embedding-3-small"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    review: Mapped["Review"] = relationship("Review", back_populates="embedding")

    def __repr__(self) -> str:
        return f"<ReviewEmbedding review_id={self.review_id} model={self.model}>"
