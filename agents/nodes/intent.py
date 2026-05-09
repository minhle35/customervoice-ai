"""Intent classifier node — routes the user's message to the right agent.

This is the "structured prompts for accurate LLM outputs" pattern in action:
instead of asking the LLM to produce free-form text and parsing it with regex,
we use llm.with_structured_output(IntentClassification) which:
  1. Injects the Pydantic schema as a JSON schema constraint into the API call
  2. Guarantees the response conforms to the schema — no fallback parsing needed
  3. Raises a ValidationError if the model breaks the contract (testable)

Intent taxonomy:
  rag         — "what do customers say about X?" — retrieval question
  insight     — "how is our sentiment?" / "what are the trends?" — aggregation
  ingestion   — "fetch reviews from Google for café X" — data pipeline trigger
  clarification — ambiguous; agent asks a follow-up question
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from pydantic import SecretStr

_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agents.state import AgentState
from app.config import ServerSettings


# ---------------------------------------------------------------------------
# Structured output schema — the LLM must return exactly this shape
# ---------------------------------------------------------------------------


class IntentClassification(BaseModel):
    """Strict output schema for intent classification.

    The LLM cannot return free-form text — it must populate all three fields
    conforming to their types. `with_structured_output` enforces this via
    the provider's function-calling / JSON-schema API.
    """

    intent: Literal["rag", "insight", "ingestion", "clarification"] = Field(
        description=(
            "rag: user asks a specific question about review content. "
            "insight: user wants trends, summaries, or aggregated stats. "
            "ingestion: user wants to fetch/load new reviews from a platform. "
            "clarification: the query is too ambiguous to act on."
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in the classification, from 0.0 to 1.0",
    )
    reasoning: str = Field(
        description="One sentence explaining why this intent was chosen"
    )


_SYSTEM_PROMPT = """\
You are an intent classifier for a customer review intelligence system.
Classify the user's message into exactly one of these intents:

  rag         — The user asks a specific question about what customers say,
                e.g. "What do people complain about most?" or
                "Are there any reviews mentioning parking?"

  insight     — The user wants aggregated stats, trends, or summaries,
                e.g. "How is our overall sentiment?", "Which platform has
                the most negative reviews?", "Show me a summary."

  ingestion   — The user wants to load new reviews from an external platform,
                e.g. "Fetch Google reviews for Café Central",
                "Ingest reviews from Reddit for this business."

  clarification — The query is too vague or ambiguous to act on confidently.

Respond only with the structured JSON schema. Do not add explanations outside it.\
"""


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


def intent_node(state: AgentState, settings: ServerSettings) -> dict:
    """Classify the latest user message and write intent to state.

    Returns a partial state update — only `intent` is written. The graph's
    conditional edge reads `state["intent"]` to decide the next node.
    """
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    query = last_human.content if last_human else ""

    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.0,  # deterministic classification
    )

    # with_structured_output wraps the LLM call with JSON-schema enforcement
    classifier = llm.with_structured_output(IntentClassification)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]
    result: IntentClassification = classifier.invoke(messages)

    return {
        "intent": result.intent,
        "intent_confidence": result.confidence,
        "intent_reasoning": result.reasoning,
    }


# ---------------------------------------------------------------------------
# Routing function — read by conditional_edges in graph.py
# ---------------------------------------------------------------------------


def route_intent(state: AgentState) -> str:
    """Map state intent to node name. Called by add_conditional_edges."""
    return state.get("intent") or "clarification"
