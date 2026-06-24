"""VectorRAG orchestration: embed → retrieve → rerank → answer."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import ServerSettings
from pipelines.base import RAGResult
from pipelines.vector_rag.answer_generator import generate_answer
from pipelines.vector_rag.retriever import embed_query, rerank, retrieve


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
    """Full VectorRAG pipeline: embed → retrieve → rerank → answer.

    Args:
        db:             SQLAlchemy session (injected via FastAPI dependency).
        question:       User's natural language question.
        business_id:    Filter reviews to this business.
        settings:       Server settings (OpenRouter credentials/model).
        retrieve_top_k: Number of ANN candidates from pgvector (stage 1).
        rerank_top_k:   Number of chunks kept after cross-encoder reranking (stage 2).
        token_budget:   Max tokens allocated for review context in the LLM prompt.
    """
    query_vec = embed_query(question)
    candidates = retrieve(db, query_vec, business_id, top_k=retrieve_top_k)

    if not candidates:
        return RAGResult(
            answer=(
                "I don't have any reviews for this business yet. "
                "Please ingest some reviews first."
            ),
            contexts=[],
            source_ids=[],
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

    return RAGResult(
        answer=answer,
        contexts=[chunk.content for chunk in used_chunks],
        source_ids=[chunk.review_id for chunk in used_chunks],
    )
