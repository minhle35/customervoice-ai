"""Agent API routes — exposes the LangGraph multi-agent graph over HTTP.

Endpoints:
  POST /api/agent/ask                   — invoke the agent for a new message
  POST /api/agent/{thread_id}/approve   — resume a paused ingestion (approved)
  POST /api/agent/{thread_id}/reject    — resume a paused ingestion (rejected)
  POST /api/agent/tools/search          — direct call to the search_reviews tool
  GET  /api/agent/tools/sentiment-summary — direct call to get_sentiment_summary
  POST /api/agent/tools/ingest          — direct call to trigger_ingestion

The graph instance is built per-request (db is request-scoped). MemorySaver
holds in-process state — swap for PostgresSaver for cross-restart persistence.

The /tools/* endpoints call the same agent tool functions (agents/tools.py)
used by the LangGraph nodes, but bypass intent classification — useful for
callers (e.g. the MCP server) that already know which tool they want.
"""

from __future__ import annotations  # noqa: I001

import sys
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver as _MemorySaver

from app.database import SessionDep
from app.config import SettingsDep
from app.logger import get_logger
from app.services.scope_guard import REFUSAL_MESSAGE, check_in_scope

_ROOT = Path(__file__).parent.parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentAskRequest(BaseModel):
    question: str = Field(description="Natural language question for the agent")
    business_id: str = Field(description="Business to scope the agent's knowledge to")
    thread_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Conversation thread ID — generate once per session, reuse for follow-ups",
    )


class AgentResponse(BaseModel):
    answer: str
    thread_id: str
    pending_approval: bool = False


class SearchReviewsRequest(BaseModel):
    query: str = Field(description="Natural language question about customer reviews")
    business_id: str = Field(description="Business to scope the search to")
    top_k: int = Field(
        default=5, ge=1, le=20, description="Number of reviews to return"
    )


class TriggerIngestionRequest(BaseModel):
    platform: str = Field(
        description="Platform to ingest from: 'google', 'reddit', or 'facebook'"
    )
    business_id: str = Field(description="Business to ingest reviews for")
    business_url: str = Field(
        description="URL or search query identifying the business on the platform"
    )


class ToolResult(BaseModel):
    result: str


# ---------------------------------------------------------------------------
# Agent graph singleton per process (MemorySaver is in-process)
# We rebuild the graph per request only for the DB closure; the checkpointer
# state is held in the MemorySaver singleton below.
# ---------------------------------------------------------------------------


_CHECKPOINTER = _MemorySaver()


def _get_graph(db, settings):
    """Build graph with request-scoped DB, shared checkpointer."""
    import sys
    from pathlib import Path

    _ROOT = Path(__file__).parent.parent.parent.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

    # Rebuild with shared checkpointer so thread state persists across requests
    from langgraph.graph import END, START, StateGraph  # noqa: PLC0415

    from agents.nodes.ingestion import (  # noqa: PLC0415
        clarification_node,
        ingestion_node,
    )
    from agents.nodes.insight import insight_node  # noqa: PLC0415
    from agents.nodes.intent import intent_node, route_intent  # noqa: PLC0415
    from agents.nodes.rag import rag_node  # noqa: PLC0415
    from agents.state import AgentState  # noqa: PLC0415

    builder = StateGraph(AgentState)
    # Wrap node constructors to match expected callable signature
    builder.add_node(
        "intent_classifier",
        lambda state, config=None, store=None: intent_node(state, settings),
    )
    builder.add_node(
        "rag",
        lambda state, config=None, store=None: rag_node(state, db, settings),
    )
    builder.add_node(
        "insight",
        lambda state, config=None, store=None: insight_node(state, db, settings),
    )
    builder.add_node("ingestion", ingestion_node)
    builder.add_node("clarification", clarification_node)
    builder.add_edge(START, "intent_classifier")
    builder.add_conditional_edges(
        "intent_classifier",
        route_intent,
        {
            "rag": "rag",
            "insight": "insight",
            "ingestion": "ingestion",
            "clarification": "clarification",
        },
    )
    for node in ("rag", "insight", "ingestion", "clarification"):
        builder.add_edge(node, END)

    return builder.compile(checkpointer=_CHECKPOINTER)


# ---------------------------------------------------------------------------
# Main agent endpoint
# ---------------------------------------------------------------------------


@router.post("/ask", response_model=AgentResponse)
def ask_agent(request: AgentAskRequest, db: SessionDep, settings: SettingsDep):
    """Invoke the multi-agent graph for a user question.

    The graph routes the question through:
      intent_classifier → rag | insight | ingestion | clarification

    If the intent is 'ingestion', the graph pauses at interrupt() and returns
    a pending_approval=True response. The client must call /approve or /reject.
    """
    from agents.graph import run_agent  # noqa: PLC0415

    scope = check_in_scope(request.question, settings)
    if not scope.in_scope:
        return AgentResponse(
            answer=REFUSAL_MESSAGE, thread_id=request.thread_id, pending_approval=False
        )

    try:
        graph = _get_graph(db, settings)
        answer = run_agent(
            graph=graph,
            question=request.question,
            business_id=request.business_id,
            thread_id=request.thread_id,
        )
    except Exception as exc:
        logger.error("Agent error thread=%s: %s", request.thread_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent failed to generate a response.",
        ) from exc

    pending = answer.startswith("__PENDING_APPROVAL__:")
    return AgentResponse(
        answer=answer,
        thread_id=request.thread_id,
        pending_approval=pending,
    )


# ---------------------------------------------------------------------------
# Human-in-the-loop endpoints
# ---------------------------------------------------------------------------


@router.post("/{thread_id}/approve", response_model=AgentResponse)
def approve_ingestion(thread_id: str, db: SessionDep, settings: SettingsDep):
    """Resume a paused ingestion graph with approval=True.

    The ingestion_node's interrupt() call receives True and dispatches the
    Celery task to fetch reviews in a background worker process.
    """
    from agents.graph import resume_agent  # noqa: PLC0415

    try:
        graph = _get_graph(db, settings)
        answer = resume_agent(graph=graph, thread_id=thread_id, approved=True)
    except Exception as exc:
        logger.error("Approve error thread=%s: %s", thread_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve ingestion.",
        ) from exc

    return AgentResponse(answer=answer, thread_id=thread_id)


@router.post("/{thread_id}/reject", response_model=AgentResponse)
def reject_ingestion(thread_id: str, db: SessionDep, settings: SettingsDep):
    """Resume a paused ingestion graph with approval=False (cancel)."""
    from agents.graph import resume_agent  # noqa: PLC0415

    try:
        graph = _get_graph(db, settings)
        answer = resume_agent(graph=graph, thread_id=thread_id, approved=False)
    except Exception as exc:
        logger.error("Reject error thread=%s: %s", thread_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject ingestion.",
        ) from exc

    return AgentResponse(answer=answer, thread_id=thread_id)


# ---------------------------------------------------------------------------
# Direct tool endpoints — thin wrappers around agents/tools.py, bypassing
# intent classification. Used by the MCP server when the caller already
# knows which tool it wants.
# ---------------------------------------------------------------------------


@router.post("/tools/search", response_model=ToolResult)
def search_reviews_tool(
    request: SearchReviewsRequest, db: SessionDep, settings: SettingsDep
):
    """Two-stage RAG retrieval: pgvector HNSW search -> cross-encoder rerank."""
    from agents.tools import build_tools  # noqa: PLC0415

    scope = check_in_scope(request.query, settings)
    if not scope.in_scope:
        return ToolResult(result=REFUSAL_MESSAGE)

    try:
        tools = build_tools(db, request.business_id, settings)
        search_reviews = next(t for t in tools if t.name == "search_reviews")
        result = search_reviews.invoke({"query": request.query, "top_k": request.top_k})
    except Exception as exc:
        logger.error("search_reviews tool error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="search_reviews tool failed.",
        ) from exc

    return ToolResult(result=result)


@router.get("/tools/sentiment-summary", response_model=ToolResult)
def sentiment_summary_tool(
    business_id: str,
    db: SessionDep,
    settings: SettingsDep,
    platform: str | None = None,
):
    """Sentiment distribution + average rating + platform breakdown for a business."""
    from agents.tools import build_tools  # noqa: PLC0415

    try:
        tools = build_tools(db, business_id, settings)
        get_sentiment_summary = next(
            t for t in tools if t.name == "get_sentiment_summary"
        )
        result = get_sentiment_summary.invoke({"platform": platform})
    except Exception as exc:
        logger.error("get_sentiment_summary tool error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="get_sentiment_summary tool failed.",
        ) from exc

    return ToolResult(result=result)


@router.post("/tools/ingest", response_model=ToolResult)
def trigger_ingestion_tool(
    request: TriggerIngestionRequest, db: SessionDep, settings: SettingsDep
):
    """Queue a Celery ingestion job for the given platform and business."""
    from agents.tools import build_tools  # noqa: PLC0415

    try:
        tools = build_tools(db, request.business_id, settings)
        trigger_ingestion = next(t for t in tools if t.name == "trigger_ingestion")
        result = trigger_ingestion.invoke(
            {"platform": request.platform, "business_url": request.business_url}
        )
    except Exception as exc:
        logger.error("trigger_ingestion tool error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="trigger_ingestion tool failed.",
        ) from exc

    return ToolResult(result=result)
