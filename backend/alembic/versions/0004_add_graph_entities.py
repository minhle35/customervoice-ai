"""Add entities/entity_relationships tables (GraphRAG) + graph_extracted flag on reviews

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

entity_type_enum = postgresql.ENUM(
    "staff", "dish", "service_aspect", "location", "other", name="entity_type_enum"
)


def upgrade() -> None:
    bind = op.get_bind()
    entity_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "entity_type",
            postgresql.ENUM(
                "staff",
                "dish",
                "service_aspect",
                "location",
                "other",
                name="entity_type_enum",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("name_embedding", Vector(768), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_entities_business_id", "entities", ["business_id"])
    op.create_index("ix_entities_canonical_name", "entities", ["canonical_name"])

    op.create_table(
        "entity_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(255), nullable=False),
        sa.Column(
            "review_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_entity_relationships_source_entity_id",
        "entity_relationships",
        ["source_entity_id"],
    )
    op.create_index(
        "ix_entity_relationships_target_entity_id",
        "entity_relationships",
        ["target_entity_id"],
    )
    op.create_index(
        "ix_entity_relationships_review_id", "entity_relationships", ["review_id"]
    )

    op.add_column(
        "reviews",
        sa.Column(
            "graph_extracted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("reviews", "graph_extracted")
    op.drop_index(
        "ix_entity_relationships_review_id", table_name="entity_relationships"
    )
    op.drop_index(
        "ix_entity_relationships_target_entity_id", table_name="entity_relationships"
    )
    op.drop_index(
        "ix_entity_relationships_source_entity_id", table_name="entity_relationships"
    )
    op.drop_table("entity_relationships")
    op.drop_index("ix_entities_canonical_name", table_name="entities")
    op.drop_index("ix_entities_business_id", table_name="entities")
    op.drop_table("entities")
    entity_type_enum.drop(op.get_bind(), checkfirst=True)
