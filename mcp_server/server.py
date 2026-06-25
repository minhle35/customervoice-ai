"""FastMCP server exposing the CustomerVoice AI backend to MCP clients.

This process runs locally (spawned by Claude Desktop / Cursor over stdio) and
is stateless — every tool call makes an HTTP request to the FastAPI backend
and returns its response. All business logic, data, and state live in the
backend; this file only handles the MCP protocol + HTTP transport.

See docs/mcp-server.md for the full architecture and tool catalogue.

Run:
    backend/.venv/bin/python mcp_server/server.py

Env vars:
    CUSTOMERVOICE_API_URL       FastAPI backend URL (default http://localhost:8000)
    CUSTOMERVOICE_API_KEY       API key, sent as Authorization: Bearer <key>, if set
    CUSTOMERVOICE_BUSINESS_ID   Default business_id for tools that need one
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastmcp import FastMCP

API_URL = os.environ.get("CUSTOMERVOICE_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("CUSTOMERVOICE_API_KEY", "")
DEFAULT_BUSINESS_ID = os.environ.get("CUSTOMERVOICE_BUSINESS_ID", "")

mcp = FastMCP("CustomerVoice AI")


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def _resolve_business_id(business_id: Optional[str]) -> str:
    business_id = business_id or DEFAULT_BUSINESS_ID
    if not business_id:
        raise ValueError(
            "No business_id provided and CUSTOMERVOICE_BUSINESS_ID is not set."
        )
    return business_id


def _request(method: str, path: str, **kwargs):
    resp = httpx.request(method, f"{API_URL}{path}", headers=_headers(), timeout=60, **kwargs)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Direct tools — single backend call, no LLM intent classification
# ---------------------------------------------------------------------------


@mcp.tool()
def list_businesses() -> list[dict]:
    """List every business that has ingested reviews, with its business_id and name.

    Call this first when the user asks about a business by name, or asks how many
    businesses there are — the other tools only operate on one business_id at a
    time and don't enumerate businesses themselves."""
    return _request("GET", "/api/reviews/businesses")


@mcp.tool()
def search_reviews(query: str, business_id: Optional[str] = None, top_k: int = 5) -> str:
    """Search customer reviews using semantic similarity (pgvector HNSW + cross-encoder rerank)."""
    business_id = _resolve_business_id(business_id)
    data = _request(
        "POST",
        "/api/agent/tools/search",
        json={"query": query, "business_id": business_id, "top_k": top_k},
    )
    return data["result"]


@mcp.tool()
def get_sentiment_summary(business_id: Optional[str] = None, platform: Optional[str] = None) -> str:
    """Get sentiment distribution, average rating, and platform breakdown for a business."""
    business_id = _resolve_business_id(business_id)
    params = {"business_id": business_id}
    if platform:
        params["platform"] = platform
    data = _request("GET", "/api/agent/tools/sentiment-summary", params=params)
    return data["result"]


@mcp.tool()
def trigger_ingestion(platform: str, business_url: str, business_id: Optional[str] = None) -> str:
    """Queue a Celery job to fetch reviews from Google/Reddit/Facebook into the background worker."""
    business_id = _resolve_business_id(business_id)
    data = _request(
        "POST",
        "/api/agent/tools/ingest",
        json={"platform": platform, "business_id": business_id, "business_url": business_url},
    )
    return data["result"]


# ---------------------------------------------------------------------------
# Agent graph tools — route through LangGraph intent classification, support
# multi-turn conversations and the ingestion human-in-the-loop pause/resume
# ---------------------------------------------------------------------------


@mcp.tool()
def ask_agent(question: str, business_id: Optional[str] = None, thread_id: Optional[str] = None) -> dict:
    """Ask the full multi-agent system a question. Routes to RAG, insight, or ingestion
    based on intent. If the answer requires ingestion approval, the response will have
    pending_approval=True — call approve_ingestion or reject_ingestion with the returned
    thread_id next."""
    business_id = _resolve_business_id(business_id)
    payload = {"question": question, "business_id": business_id}
    if thread_id:
        payload["thread_id"] = thread_id
    return _request("POST", "/api/agent/ask", json=payload)


@mcp.tool()
def approve_ingestion(thread_id: str) -> dict:
    """Approve a paused ingestion request, dispatching the Celery task to fetch reviews."""
    return _request("POST", f"/api/agent/{thread_id}/approve")


@mcp.tool()
def reject_ingestion(thread_id: str) -> dict:
    """Reject and cancel a paused ingestion request."""
    return _request("POST", f"/api/agent/{thread_id}/reject")


if __name__ == "__main__":
    mcp.run()
