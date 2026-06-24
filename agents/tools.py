"""Agent tool definitions.

Each tool is a plain Python function decorated with @tool. They carry a Pydantic
args_schema so the LLM receives a strict JSON schema — this is the "structured
prompts for accurate LLM outputs" pattern: instead of free-form instructions we
give the model a typed contract it must satisfy.

Tools are built via build_tools(db, settings) so the DB session is captured in
a closure — FastAPI injects db per-request, and the graph is compiled inside
that request scope.

Tool catalogue:
  search_reviews        — semantic retrieval over stored reviews (calls RAG pipeline)
  get_sentiment_summary — aggregated sentiment stats from relational DB (raw SQL)
  trigger_ingestion     — queues a Celery ingestion task (multi-threaded, async)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from app.config import ServerSettings
from app.models.review import Review, SentimentLabel
from pipelines.vector_rag.retriever import embed_query, rerank, retrieve

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# Project root so both `app` and `pipelines` are importable
_ROOT = Path(__file__).parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Input schemas — strict Pydantic models the LLM must conform to
# ---------------------------------------------------------------------------


class SearchReviewsInput(BaseModel):
    query: str = Field(description="Natural language question about customer reviews")
    top_k: int = Field(
        default=5, ge=1, le=20, description="Number of reviews to return"
    )


class SentimentSummaryInput(BaseModel):
    platform: Optional[str] = Field(
        default=None,
        description="Filter by platform: 'google', 'reddit', or 'facebook'. Omit for all platforms.",
    )


class TriggerIngestionInput(BaseModel):
    platform: str = Field(
        description="Platform to ingest from: 'google', 'reddit', or 'facebook'"
    )
    business_url: str = Field(
        description="URL or search query identifying the business on the platform"
    )


# ---------------------------------------------------------------------------
# Factory — captures db + business_id + settings in closure
# ---------------------------------------------------------------------------


def build_tools(db: Session, business_id: str, settings: ServerSettings) -> list:
    """Return tool list bound to the current request's DB session and business."""

    @tool(args_schema=SearchReviewsInput)
    def search_reviews(query: str, top_k: int = 5) -> str:
        """Semantically search customer reviews for the current business.

        Uses two-stage retrieval:
          1. pgvector HNSW cosine search → top-20 candidates  (fast, approximate)
          2. Cross-encoder re-ranking    → top-k final results (slow, precise)

        Returns review excerpts with author, rating, platform, and sentiment.
        Cite reviews in your answer using the provided indices [1], [2], etc.
        """
        query_vec = embed_query(query)
        candidates = retrieve(db, query_vec, business_id, top_k=20)
        if not candidates:
            return "No reviews found for this business yet."

        reranked = rerank(query, candidates, final_top_k=top_k)

        lines = []
        for i, chunk in enumerate(reranked, 1):
            rating_str = f"Rating: {chunk.rating}/5" if chunk.rating else "No rating"
            lines.append(
                f"[{i}] {chunk.platform.upper()} | {rating_str} | "
                f"Sentiment: {chunk.sentiment_label or 'unknown'}\n"
                f"Author: {chunk.author or 'Anonymous'}\n"
                f"{chunk.content}"
            )
        return "\n\n".join(lines)

    @tool(args_schema=SentimentSummaryInput)
    def get_sentiment_summary(platform: Optional[str] = None) -> str:
        """Get aggregated sentiment statistics for the current business.

        Queries the relational database (PostgreSQL) to count reviews by
        sentiment label, compute average rating, and show platform breakdown.
        Use this for trend questions like "how is our sentiment overall?" or
        "which platform has the most negative reviews?".
        """
        # Base query scoped to this business
        filters = [Review.business_id == business_id, Review.is_processed == True]  # noqa: E712
        if platform:
            filters.append(Review.platform == platform)

        # Sentiment distribution — demonstrates raw SQL + GROUP BY
        rows = db.execute(
            select(
                Review.sentiment_label,
                Review.platform,
                func.count(Review.id).label("count"),
                func.avg(Review.rating).label("avg_rating"),
            )
            .where(*filters)
            .group_by(Review.sentiment_label, Review.platform)
            .order_by(Review.platform, Review.sentiment_label)
        ).all()

        if not rows:
            return "No processed reviews found. Ingest some reviews first."

        # Aggregate totals
        total = sum(r.count for r in rows)
        positive = sum(
            r.count for r in rows if r.sentiment_label == SentimentLabel.positive
        )
        negative = sum(
            r.count for r in rows if r.sentiment_label == SentimentLabel.negative
        )
        neutral = sum(
            r.count for r in rows if r.sentiment_label == SentimentLabel.neutral
        )

        avg_ratings = [r.avg_rating for r in rows if r.avg_rating is not None]
        overall_avg = sum(avg_ratings) / len(avg_ratings) if avg_ratings else None

        lines = [
            f"Total reviews analysed: {total}",
            f"Positive: {positive} ({100 * positive // total}%)  "
            f"Neutral: {neutral} ({100 * neutral // total}%)  "
            f"Negative: {negative} ({100 * negative // total}%)",
        ]
        if overall_avg:
            lines.append(f"Average rating: {overall_avg:.1f}/5")

        lines.append("\nBreakdown by platform:")
        by_platform: dict[str, list] = {}
        for r in rows:
            by_platform.setdefault(str(r.platform), []).append(r)

        for plat, plat_rows in by_platform.items():
            plat_total = sum(r.count for r in plat_rows)
            plat_pos = sum(
                r.count
                for r in plat_rows
                if r.sentiment_label == SentimentLabel.positive
            )
            lines.append(f"  {plat}: {plat_total} reviews, {plat_pos} positive")

        return "\n".join(lines)

    @tool(args_schema=TriggerIngestionInput)
    def trigger_ingestion(platform: str, business_url: str) -> str:
        """Queue an async review ingestion job for this business.

        Dispatches a Celery task (backed by Redis broker) that runs in a
        separate worker process — non-blocking, multi-threaded execution.
        The task fetches reviews from the platform, stores them in PostgreSQL,
        runs LLM sentiment analysis, and generates vector embeddings.

        Returns a task ID for polling ingestion progress.
        """
        # Import here to avoid loading Celery at module import time
        from workers.tasks import ingest_platform  # noqa: PLC0415

        result = ingest_platform.delay(
            platform,
            business_id,
            {"business_url": business_url},
        )
        return (
            f"Ingestion job queued. Task ID: {result.id}\n"
            f"Platform: {platform} | Business URL: {business_url}\n"
            "Reviews will be fetched, analysed, and embedded in the background. "
            "Check /api/integrations/status/{task_id} for progress."
        )

    return [search_reviews, get_sentiment_summary, trigger_ingestion]
