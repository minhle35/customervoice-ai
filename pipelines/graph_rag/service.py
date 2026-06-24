"""GraphRAG orchestration — entity-relationship graph traversal (not yet implemented)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import ServerSettings
from pipelines.base import RAGResult


def run(
    db: Session,
    question: str,
    business_id: str,
    *,
    settings: ServerSettings,
    retrieve_top_k: int = 20,
    rerank_top_k: int = 5,
    token_budget: int = 2000,
) -> RAGResult:
    raise NotImplementedError("GraphRAG not yet implemented")
