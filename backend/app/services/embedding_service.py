from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.embedding import ReviewEmbedding


class EmbeddingService:
    def __init__(self, db: Session):
        self.db = db

    def upsert_embedding(
        self, review_id, embedding: list[float], model: str
    ) -> ReviewEmbedding:
        stmt = (
            insert(ReviewEmbedding)
            .values(review_id=review_id, embedding=embedding, model=model)
            .on_conflict_do_update(
                index_elements=["review_id"],
                set_={"embedding": embedding, "model": model},
            )
            .returning(ReviewEmbedding.id)
        )
        result = self.db.execute(stmt).scalar_one()
        self.db.commit()
        stored = self.db.execute(
            select(ReviewEmbedding).where(ReviewEmbedding.id == result)
        ).scalar_one()
        return stored
