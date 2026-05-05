"""Shared agent state — passed between every node in the LangGraph graph.

AgentState is a TypedDict, which means:
- LangGraph reads/writes it as a plain dict at runtime (no ORM overhead)
- `Annotated[list[BaseMessage], add_messages]` tells LangGraph to APPEND
  new messages rather than replace the whole list — standard chat pattern.
- All other fields are replaced on each node write.

Thread identity:
  thread_id  — one UUID per conversation session (used by LangGraph checkpointer
                to persist + resume state across HTTP requests)
  business_id — scopes all tool calls to a specific business's reviews
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # ------------------------------------------------------------------ #
    # Conversation history — append-only via add_messages reducer          #
    # ------------------------------------------------------------------ #
    messages: Annotated[list[BaseMessage], add_messages]

    # ------------------------------------------------------------------ #
    # Routing & session context                                            #
    # ------------------------------------------------------------------ #
    business_id: str
    thread_id: str

    # Set by the intent classifier node; drives conditional edges
    intent: Literal["rag", "insight", "ingestion", "clarification"] | None

    # ------------------------------------------------------------------ #
    # Human-in-the-loop handshake for ingestion                           #
    # ------------------------------------------------------------------ #
    # Populated by the ingestion node before it pauses for approval.
    # Contains: {"platform": str, "business_url": str}
    pending_ingestion: dict | None

    # Set to True/False by the /approve or /reject API endpoint,
    # then the graph resumes from the interrupt checkpoint.
    approved: bool | None
