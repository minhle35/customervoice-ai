"""RAG retriever: query embedding + pgvector cosine search + cross-encoder re-rank."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from sentence_transformers import CrossEncoder, SentenceTransformer
from sqlalchemy import text
from sqlalchemy.orm import Session

# Make `app` importable when this module is run from the project root
_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.config import settings  # noqa: E402

# ---------------------------------------------------------------------------
# Model singletons — loaded once per process
# ---------------------------------------------------------------------------

_encoder: SentenceTransformer | None = None
_cross_encoder: CrossEncoder | None = None

CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _get_encoder() -> SentenceTransformer:
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer(settings.embedding_model)
    return _encoder


def _get_cross_encoder() -> CrossEncoder:
    global _cross_encoder
    if _cross_encoder is None:
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
    return _cross_encoder


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ReviewChunk:
    review_id: UUID
    content: str
    author: str | None
    rating: float | None
    sentiment_label: str | None
    platform: str
    similarity_score: float
    rerank_score: float = field(default=0.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_query(query_text: str) -> list[float]:
    """Embed a retrieval query using the 'query:' prefix.

    multilingual-e5-base requires:
      - 'passage: <text>' for documents stored in the index
      - 'query: <text>'   for queries at retrieval time
    Using the wrong prefix degrades recall significantly.
    """
    model = _get_encoder()
    vector = model.encode(f"query: {query_text}", normalize_embeddings=True)
    return vector.tolist()


def retrieve(
    db: Session,
    query_embedding: list[float],
    business_id: str,
    top_k: int = 20,
) -> list[ReviewChunk]:
    """Cosine similarity search via pgvector HNSW index.

    The <=> operator returns cosine *distance* (0 = identical, 2 = opposite).
    We convert to similarity by computing 1 - distance so higher = more relevant.
    Results are ordered closest-first (ascending distance).
    """
    sql = text(
        """
        SELECT
            r.id,
            r.content,
            r.author,
            r.rating,
            r.sentiment_label,
            r.platform,
            1 - (re.embedding <=> CAST(:query_vec AS vector)) AS similarity_score
        FROM review_embeddings re
        JOIN reviews r ON r.id = re.review_id
        WHERE r.business_id = :business_id
          AND r.content IS NOT NULL
        ORDER BY re.embedding <=> CAST(:query_vec AS vector)
        LIMIT :top_k
        """
    )

    rows = db.execute(
        sql,
        {
            "query_vec": str(query_embedding),
            "business_id": business_id,
            "top_k": top_k,
        },
    ).fetchall()

    return [
        ReviewChunk(
            review_id=row.id,
            content=row.content,
            author=row.author,
            rating=float(row.rating) if row.rating is not None else None,
            sentiment_label=str(row.sentiment_label) if row.sentiment_label else None,
            platform=str(row.platform),
            similarity_score=float(row.similarity_score),
        )
        for row in rows
    ]


def rerank(
    query: str,
    chunks: list[ReviewChunk],
    final_top_k: int = 5,
) -> list[ReviewChunk]:
    """Re-rank retrieved chunks using a cross-encoder model.

    The cross-encoder reads (query, document) jointly — more accurate than the
    bi-encoder but slower. We apply it only to the first-stage candidates to
    keep end-to-end latency manageable.

    Strategy: retrieve-20 (fast, approximate) → rerank-5 (slow, precise).
    """
    if not chunks:
        return []

    cross_encoder = _get_cross_encoder()
    pairs = [(query, chunk.content) for chunk in chunks]
    scores = cross_encoder.predict(pairs)

    for chunk, score in zip(chunks, scores):
        chunk.rerank_score = float(score)

    chunks.sort(key=lambda c: c.rerank_score, reverse=True)
    return chunks[:final_top_k]
