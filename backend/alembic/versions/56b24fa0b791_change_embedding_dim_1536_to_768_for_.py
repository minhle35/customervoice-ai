"""change embedding dim 1536 to 768 for multilingual-e5

Revision ID: 56b24fa0b791
Revises: 0001
Create Date: 2026-03-18 12:10:55.571145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '56b24fa0b791'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the HNSW index on the old 1536-dim column
    op.drop_index('ix_review_embeddings_embedding', table_name='review_embeddings', if_exists=True)

    # Replace the embedding column: 1536 dims → 768 dims
    op.drop_column('review_embeddings', 'embedding')
    op.add_column('review_embeddings', sa.Column('embedding', Vector(768), nullable=False))

    # Recreate HNSW index for cosine similarity search
    op.execute(
        "CREATE INDEX ix_review_embeddings_embedding "
        "ON review_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.drop_index('ix_review_embeddings_embedding', table_name='review_embeddings', if_exists=True)

    op.drop_column('review_embeddings', 'embedding')
    op.add_column('review_embeddings', sa.Column('embedding', Vector(1536), nullable=False))

    op.execute(
        "CREATE INDEX ix_review_embeddings_embedding "
        "ON review_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
