"""LangGraph multi-agent graph — wires all nodes into a runnable workflow.

Architecture:
  START → intent_classifier → conditional_edge → rag / insight / ingestion / clarification → END

The intent classifier reads the user's message and writes `state["intent"]`.
The conditional edge routes to the appropriate specialist node.

Checkpointing (thread/session management):
  MemorySaver persists AgentState keyed by {"configurable": {"thread_id": <uuid>}}.
  This means:
    - Each conversation session has its own isolated state
    - The ingestion node can interrupt, the graph is serialised, and when the
      user approves via the HTTP endpoint, the graph resumes from exactly where
      it paused — even across different HTTP requests or server restarts
      (swap MemorySaver for PostgresSaver for true persistence).

Why this matters for the job application:
  - Multi-step reasoning: intent → specialist → answer (3-node pipeline)
  - Multi-agent roles: four distinct agents with different responsibilities
  - Human-in-the-loop: interrupt/resume pattern for ingestion approval
  - Stateful context management: thread_id scopes conversation history
  - Tool-use: agents call search_reviews / get_sentiment_summary / trigger_ingestion
"""

from __future__ import annotations

import sys
from pathlib import Path
from agents.nodes.ingestion import clarification_node, ingestion_node
from agents.nodes.insight import insight_node
from agents.nodes.intent import intent_node, route_intent
from agents.nodes.rag import rag_node
from agents.state import AgentState
from app.config import ServerSettings

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from sqlalchemy.orm import Session

_ROOT = Path(__file__).parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Graph factory — called once per request (db is request-scoped)
# ---------------------------------------------------------------------------


def build_graph(db: Session, settings: ServerSettings):
    """Compile the agent graph with node closures bound to this request's DB.

    Returns a CompiledStateGraph ready to invoke or stream.
    """
    builder = StateGraph(AgentState)

    # ---------------------------------------------------------------------- #
    # Nodes — each is a partial that captures db/settings from outer scope    #
    # ---------------------------------------------------------------------- #

    builder.add_node(
        "intent_classifier",
        lambda state: intent_node(state, settings),
    )
    builder.add_node(
        "rag",
        lambda state: rag_node(state, db, settings),
    )
    builder.add_node(
        "insight",
        lambda state: insight_node(state, db, settings),
    )
    builder.add_node(
        "ingestion",
        ingestion_node,  # HITL via interrupt() — no db needed until Celery dispatch
    )
    builder.add_node(
        "clarification",
        clarification_node,
    )

    # ---------------------------------------------------------------------- #
    # Edges                                                                   #
    # ---------------------------------------------------------------------- #

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

    # All specialist nodes terminate after one response
    for node in ("rag", "insight", "ingestion", "clarification"):
        builder.add_edge(node, END)

    # ---------------------------------------------------------------------- #
    # Checkpointer — persists state between HTTP requests per thread_id       #
    # ---------------------------------------------------------------------- #
    checkpointer = MemorySaver()

    return builder.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Public helpers — called by the FastAPI route
# ---------------------------------------------------------------------------


def run_agent(
    graph,
    question: str,
    business_id: str,
    thread_id: str,
) -> str:
    """Invoke the graph for a new user message.

    Returns the last AI message content, or a signal string if the graph
    paused at an interrupt (ingestion approval pending).
    """
    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages": [HumanMessage(content=question)],
        "business_id": business_id,
        "thread_id": thread_id,
        "intent": None,
        "pending_ingestion": None,
        "approved": None,
    }

    result = graph.invoke(initial_state, config)

    # Check if graph paused at an interrupt
    snapshot = graph.get_state(config)
    if snapshot.next:
        # Graph is paused — surface the interrupt payload to the caller
        interrupts = snapshot.tasks[0].interrupts if snapshot.tasks else []
        if interrupts:
            payload = interrupts[0].value
            return (
                f"__PENDING_APPROVAL__:{payload.get('message', 'Approval required.')}"
            )

    # Normal completion — return last AI message
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and not isinstance(msg, HumanMessage):
            return str(msg.content)

    return "I couldn't generate a response. Please try again."


def resume_agent(graph, thread_id: str, approved: bool) -> str:
    """Resume a graph paused at an ingestion interrupt.

    Called by POST /api/agent/{thread_id}/approve or /reject.
    Command(resume=approved) passes the approval decision back into the
    ingestion_node where interrupt() was called.
    """
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(Command(resume=approved), config)

    messages = result.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and not isinstance(msg, HumanMessage):
            return str(msg.content)

    return "Action completed."
