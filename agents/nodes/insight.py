"""Insight agent node — answers trend and aggregation questions.

Handles queries like:
  "How is our overall sentiment?"
  "Which platform has the most negative reviews?"
  "What topics come up most often?"

Unlike the RAG node (which retrieves specific review text), this node:
  1. Calls get_sentiment_summary tool to pull aggregated stats from PostgreSQL
  2. Queries the DB directly for topic frequency (demonstrates raw SQL)
  3. Feeds the structured data to the LLM for a plain-language summary

The system prompt is structured to produce:
  - A one-line headline sentiment verdict
  - A platform breakdown section
  - A top-topics section
  - One actionable recommendation

This is "structured prompts for accurate LLM outputs" at the response level —
the prompt constrains the shape of the answer, not just the input schema.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from agents.state import AgentState
from agents.tools import build_tools
from app.config import ServerSettings
from app.models.review import Review

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


_SYSTEM_PROMPT = """\
You are a customer insights analyst. You will receive aggregated review statistics
and a list of frequently mentioned topics for a business.

Produce a structured insight report with exactly these sections:

## Overall Sentiment
One sentence verdict on how the business is perceived.

## Platform Breakdown
One bullet per platform showing sentiment split and volume.

## Top Topics Customers Mention
Up to 5 bullet points — most frequent topics, whether positive or negative.

## Recommendation
One specific, actionable thing the business should do based on this data.

Use plain language. Be direct. Business owners read this to make decisions.\
"""


def _get_top_topics(db: Session, business_id: str, top_n: int = 10) -> list[str]:
    """Pull all topics arrays from processed reviews and rank by frequency.

    topics is stored as a JSON array column in PostgreSQL.
    This demonstrates: relational DB query → Python aggregation → LLM input.
    """
    rows = (
        db.execute(
            select(Review.topics).where(
                Review.business_id == business_id,
                Review.is_processed == True,  # noqa: E712
                Review.topics.is_not(None),
            )
        )
        .scalars()
        .all()
    )

    counter: Counter = Counter()
    for topics_val in rows:
        if not topics_val:
            continue
        # topics is stored as JSON list or comma-separated string depending on DB driver
        if isinstance(topics_val, list):
            items = topics_val
        else:
            try:
                items = json.loads(topics_val)
            except (json.JSONDecodeError, TypeError):
                items = [str(topics_val)]
        counter.update(t.strip().lower() for t in items if t)

    return [topic for topic, _ in counter.most_common(top_n)]


def insight_node(state: AgentState, db: Session, settings: ServerSettings) -> dict:
    """Generate a structured insight report grounded in DB statistics."""
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    question = str(last_human.content) if last_human else "Give me an insights summary."
    business_id = state["business_id"]

    # Get sentiment summary via the shared tool (reuses the same query logic)
    tools = build_tools(db, business_id, settings)
    sentiment_tool = next(t for t in tools if t.name == "get_sentiment_summary")
    sentiment_data: str = sentiment_tool.invoke({})

    # Get top topics from DB
    top_topics = _get_top_topics(db, business_id)
    topics_str = ", ".join(top_topics) if top_topics else "No topics extracted yet."

    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.3,
        max_tokens=1000,
    )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"User question: {question}\n\n"
                f"--- SENTIMENT STATISTICS ---\n{sentiment_data}\n\n"
                f"--- TOP TOPICS ---\n{topics_str}"
            )
        ),
    ]
    answer: str = llm.invoke(messages).content  # type: ignore[assignment]

    return {"messages": [AIMessage(content=answer)]}
