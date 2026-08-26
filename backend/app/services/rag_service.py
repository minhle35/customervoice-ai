"""RAG pipeline service — orchestrates embed → retrieve → rerank → answer."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

from langsmith import traceable
from sqlalchemy.orm import Session

from app.config import get_settings

# Project root must be on sys.path so `pipelines.*` is importable from the backend
# — set before the pipelines import below, not just relied on as a side effect
# of some other module (e.g. routes_agent.py) having already run first.
_ROOT = Path(__file__).parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pipelines.registry import get_rag_system  # noqa: E402


@traceable(name="rag_pipeline", metadata={"pipeline": "two-stage-rag"})
def run_rag_pipeline(
    db: Session,
    question: str,
    business_id: str,
    *,
    system_type: str = "vector",
    retrieve_top_k: int = 20,
    rerank_top_k: int = 5,
    token_budget: int = 2000,
) -> tuple[str, list[UUID]]:
    """Full RAG pipeline: embed/extract → retrieve → (rerank) → answer.

    Args:
        db:            SQLAlchemy session (injected via FastAPI dependency).
        question:      User's natural language question.
        business_id:   Filter reviews/graph to this business.
        system_type:   "vector" or "graph" — looked up via
                       pipelines.registry.get_rag_system(). Defaults to
                       "vector" so existing callers are unaffected.
        retrieve_top_k: Number of stage-1 candidates (pgvector ANN for
                       vector, graph facts for graph).
        rerank_top_k:  Chunks kept after cross-encoder reranking — vector
                       only; ignored (but still accepted) by graph.
        token_budget:  Max tokens allocated for context in the LLM prompt.

    Returns:
        answer:     Grounded LLM answer with [N] citation markers.
        source_ids: List of review UUIDs used as context (for the API response).
    """
    rag_system = get_rag_system(system_type)
    result = rag_system(
        db,
        question,
        business_id,
        settings=get_settings(),
        retrieve_top_k=retrieve_top_k,
        rerank_top_k=rerank_top_k,
        token_budget=token_budget,
    )
    return result.answer, result.source_ids
