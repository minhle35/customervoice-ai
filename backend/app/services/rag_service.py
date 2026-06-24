"""RAG pipeline service — orchestrates embed → retrieve → rerank → answer."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from langsmith import traceable
from sqlalchemy.orm import Session
from app.config import get_settings
from pipelines.vector_rag import service as vector_rag

# Project root must be on sys.path so `pipelines.*` is importable from the backend
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@traceable(name="rag_pipeline", metadata={"pipeline": "two-stage-rag"})
def run_rag_pipeline(
    db: Session,
    question: str,
    business_id: str,
    *,
    retrieve_top_k: int = 20,
    rerank_top_k: int = 5,
    token_budget: int = 2000,
) -> tuple[str, list[UUID]]:
    """Full RAG pipeline: embed → retrieve → rerank → answer.

    Args:
        db:            SQLAlchemy session (injected via FastAPI dependency).
        question:      User's natural language question.
        business_id:   Filter reviews to this business.
        retrieve_top_k: Number of ANN candidates from pgvector (stage 1).
        rerank_top_k:  Number of chunks kept after cross-encoder reranking (stage 2).
        token_budget:  Max tokens allocated for review context in the LLM prompt.

    Returns:
        answer:     Grounded LLM answer with [N] citation markers.
        source_ids: List of review UUIDs used as context (for the API response).
    """
    result = vector_rag.run(
        db,
        question,
        business_id,
        settings=get_settings(),
        retrieve_top_k=retrieve_top_k,
        rerank_top_k=rerank_top_k,
        token_budget=token_budget,
    )
    return result.answer, result.source_ids
