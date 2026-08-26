from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.review import Review

# Matches ServerSettings.embedding_dimensions / intfloat/multilingual-e5-base
_EMBEDDING_DIMENSIONS = 768


class EntityType(str, enum.Enum):
    staff = "staff"
    dish = "dish"
    service_aspect = "service_aspect"
    location = "location"
    other = "other"


class Entity(Base):
    """A resolved entity mentioned in one or more reviews for a business.

    Populated by GraphRAG's extraction pipeline (pipelines/graph_rag/extractor.py),
    not VectorRAG. Distinct from a raw mention: `canonical_name` is the
    normalized form used for dedup lookups at extraction time so that
    "the waiter" and "our waiter Tom" don't become two separate nodes when
    they should merge into one.
    """

    __tablename__ = "entities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    business_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type_enum"), nullable=False
    )
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # `passage:`-prefixed embedding of `name`, used for entity resolution —
    # merging "the waiter" and "our waiter Tom" into one node by cosine
    # similarity instead of exact string match. Nullable because it's set at
    # extraction time via the same generate_embedding() VectorRAG uses, not
    # at model-construction time.
    name_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(_EMBEDDING_DIMENSIONS), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Entity id={self.id} name={self.name!r} type={self.entity_type}>"


class EntityRelationship(Base):
    """A directed, review-sourced edge between two entities (GraphRAG's graph store).

    One row per extracted (subject, predicate, object) triple. `review_id`
    is the provenance — which review this relationship was extracted from —
    so graph traversal results can cite back to source reviews the same way
    VectorRAG cites review chunks.
    """

    __tablename__ = "entity_relationships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(255), nullable=False)
    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source_entity: Mapped["Entity"] = relationship(
        "Entity", foreign_keys=[source_entity_id]
    )
    target_entity: Mapped["Entity"] = relationship(
        "Entity", foreign_keys=[target_entity_id]
    )
    review: Mapped["Review"] = relationship("Review")

    def __repr__(self) -> str:
        return (
            f"<EntityRelationship {self.source_entity_id} "
            f"-[{self.relation_type}]-> {self.target_entity_id}>"
        )