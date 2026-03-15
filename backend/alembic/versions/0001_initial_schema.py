"""Initial schema: reviews, insights, review_embeddings

Revision ID: 0001
Revises:
Create Date: 2026-03-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Define enums once — reused in upgrade() and downgrade()
platform_enum = postgresql.ENUM("google", "reddit", "facebook", name="platform_enum")
sentiment_label_enum = postgresql.ENUM("positive", "negative", "neutral", name="sentiment_label_enum")
insight_type_enum = postgresql.ENUM(
    "summary", "trend", "topic", "recommendation", name="insight_type_enum"
)


def upgrade() -> None:
    bind = op.get_bind()

    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create enum types — checkfirst=True makes this idempotent
    platform_enum.create(bind, checkfirst=True)
    sentiment_label_enum.create(bind, checkfirst=True)
    insight_type_enum.create(bind, checkfirst=True)

    # -- reviews --
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # postgresql.ENUM with create_type=False — type already created above
        sa.Column("platform", postgresql.ENUM("google", "reddit", "facebook", name="platform_enum", create_type=False), nullable=False),
        sa.Column("platform_id", sa.String(255), nullable=False),
        sa.Column("business_id", sa.String(255), nullable=False),
        sa.Column("business_name", sa.String(512), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column(
            "sentiment_label",
            postgresql.ENUM("positive", "negative", "neutral", name="sentiment_label_enum", create_type=False),
            nullable=True,
        ),
        sa.Column("topics", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_reviews_platform", "reviews", ["platform"])
    op.create_index("ix_reviews_business_id", "reviews", ["business_id"])
    op.create_unique_constraint("uq_reviews_platform_platform_id", "reviews", ["platform", "platform_id"])

    # -- review_embeddings --
    op.create_table(
        "review_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "review_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("model", sa.String(128), nullable=False, server_default="text-embedding-3-small"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_review_embeddings_review_id", "review_embeddings", ["review_id"])
    op.execute(
        "CREATE INDEX ix_review_embeddings_hnsw ON review_embeddings "
        "USING hnsw (embedding vector_cosine_ops);"
    )

    # -- insights --
    op.create_table(
        "insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_type",
            postgresql.ENUM("summary", "trend", "topic", "recommendation", name="insight_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("business_id", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(64), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("extra_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_insights_insight_type", "insights", ["insight_type"])
    op.create_index("ix_insights_business_id", "insights", ["business_id"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("insights")
    op.execute("DROP INDEX IF EXISTS ix_review_embeddings_hnsw;")
    op.drop_table("review_embeddings")
    op.drop_table("reviews")

    insight_type_enum.drop(bind, checkfirst=True)
    sentiment_label_enum.drop(bind, checkfirst=True)
    platform_enum.drop(bind, checkfirst=True)
