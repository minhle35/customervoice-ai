"""Ingestion agent node — fetches new reviews with human-in-the-loop approval.

Flow:
  1. Parse platform + business URL from the user's message
  2. interrupt() — graph pauses here and serialises state to the checkpointer
  3. HTTP client calls POST /api/agent/{thread_id}/approve or /reject
  4. Graph resumes: if approved → dispatch Celery task; if rejected → cancel

Why interrupt() matters:
  - The graph is stateful across HTTP requests (checkpointer persists AgentState)
  - The user can approve/reject from a different browser session or device
  - This is the canonical LangGraph human-in-the-loop pattern

Multi-threading angle:
  - The Celery task dispatched here runs in a separate worker process
  - Redis acts as the message broker between FastAPI and the Celery worker
  - FastAPI, the agent graph, and the Celery worker are three separate threads/processes
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from agents.state import AgentState

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# Supported platforms and their display names
_PLATFORMS = {"google", "reddit", "facebook"}
_PLATFORM_ALIASES = {
    "google maps": "google",
    "google reviews": "google",
    "google": "google",
    "reddit": "reddit",
    "facebook": "facebook",
    "fb": "facebook",
}


def _parse_ingestion_request(query: str) -> tuple[str, str]:
    """Extract platform and business URL/name from a natural-language request.

    Returns (platform, business_identifier). Falls back to "google" and the
    full query string if parsing is ambiguous.
    """
    query_lower = query.lower()

    detected_platform = "google"
    for alias, canonical in _PLATFORM_ALIASES.items():
        if alias in query_lower:
            detected_platform = canonical
            break

    # Try to extract a URL first
    url_match = re.search(r"https?://\S+", query)
    if url_match:
        return detected_platform, url_match.group()

    # Strip common imperative phrases to get the business name
    clean = re.sub(
        r"(fetch|ingest|get|load|pull|scrape)\s+(reviews?\s+)?(from\s+)?"
        r"(google|reddit|facebook|google maps|google reviews)\s*(for\s+)?",
        "",
        query_lower,
    ).strip()

    business_identifier = clean or query
    return detected_platform, business_identifier


def ingestion_node(state: AgentState) -> dict:
    """Parse the ingestion request, pause for human approval, then dispatch.

    The interrupt() call serialises the current AgentState to the checkpointer
    (MemorySaver or PostgresSaver) and raises an exception that LangGraph catches.
    The graph is now paused. When the /approve or /reject endpoint calls
    graph.invoke(Command(resume=approved), config), execution resumes here
    with `approved` set to the value passed to Command(resume=...).
    """
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    query = str(last_human.content) if last_human else ""

    platform, business_identifier = _parse_ingestion_request(query)

    # Pause — graph serialises to checkpointer here.
    # The dict passed to interrupt() is surfaced to the caller via NodeInterrupt.
    approved: bool = interrupt(
        {
            "message": (
                f"About to ingest {platform.upper()} reviews for: '{business_identifier}'. "
                "Approve to start the background job, reject to cancel."
            ),
            "platform": platform,
            "business_identifier": business_identifier,
            "thread_id": state["thread_id"],
        }
    )

    if approved:
        # Dispatch Celery task — runs in a separate worker process (multi-threaded)
        from workers.tasks import ingest_platform  # noqa: PLC0415

        result = ingest_platform.delay(
            platform,
            state["business_id"],
            {"business_url": business_identifier},
        )
        response = (
            f"Ingestion job started for **{business_identifier}** on {platform.upper()}.\n"
            f"Task ID: `{result.id}`\n"
            "Reviews will be fetched, analysed with LLM sentiment classification, "
            "and embedded in the background. This usually takes 1–3 minutes."
        )
    else:
        response = "Ingestion cancelled. No data was fetched."

    return {
        "messages": [AIMessage(content=response)],
        "pending_ingestion": None,
        "approved": approved,
    }


def clarification_node(state: AgentState) -> dict:
    """Ask the user to clarify an ambiguous query."""
    return {
        "messages": [
            AIMessage(
                content=(
                    "I'm not sure what you'd like to do. Could you clarify?\n\n"
                    "I can help you with:\n"
                    "- **Answering questions** about customer reviews "
                    "(e.g. 'What do customers complain about most?')\n"
                    "- **Insights and trends** "
                    "(e.g. 'How is our overall sentiment on Google?')\n"
                    "- **Fetching new reviews** "
                    "(e.g. 'Ingest Google reviews for Café Central')"
                )
            )
        ]
    }
