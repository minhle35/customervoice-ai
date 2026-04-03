"""RAG pipeline service — orchestrates embed → retrieve → rerank → answer."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session
from app.config import settings
from pipelines.rag.answer_generator import generate_answer
from pipelines.rag.retriever import embed_query, rerank, retrieve

# Project root must be on sys.path so `pipelines.*` is importable from the backend
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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
    query_vec = embed_query(question)
    candidates = retrieve(db, query_vec, business_id, top_k=retrieve_top_k)

    if not candidates:
        return (
            "I don't have any reviews for this business yet. "
            "Please ingest some reviews first.",
            [],
        )

    reranked = rerank(question, candidates, final_top_k=rerank_top_k)

    answer, used_chunks = generate_answer(
        question=question,
        chunks=reranked,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        token_budget=token_budget,
    )

    source_ids: list[UUID] = [chunk.review_id for chunk in used_chunks]
    return answer, source_ids
