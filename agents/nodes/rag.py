"""RAG agent node — answers specific questions grounded in customer reviews.

Wraps the existing two-stage retrieval pipeline (pgvector HNSW → cross-encoder
re-rank → LLM answer with citations) as a LangGraph node. This node runs when
the intent classifier routes "rag" queries here.

The system prompt enforces:
  - Grounding: only use provided review excerpts, never invent facts
  - Citation format: [1][2][3] markers linking answers to source reviews
  - Tone: concise, actionable language for business owners
"""

from __future__ import annotations

import sys
from pathlib import Path
from agents.state import AgentState
from app.config import ServerSettings
from app.services.rag_service import run_rag_pipeline
from sqlalchemy.orm import Session


from langchain_core.messages import AIMessage, HumanMessage

_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in [str(_ROOT), str(_BACKEND)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def rag_node(state: AgentState, db: Session, settings: ServerSettings) -> dict:
    """Run the full RAG pipeline and return a cited answer as an AI message.

    Pipeline:
      embed query → pgvector HNSW retrieve-20 → cross-encoder rerank-5
      → token-budgeted context builder → LangChain LCEL answer chain

    The answer is appended to the message history so the checkpointer can
    persist the full conversation across requests.
    """
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if not last_human:
        return {
            "messages": [AIMessage(content="I didn't receive a question to answer.")]
        }

    question = str(last_human.content)
    business_id = state["business_id"]

    answer, _source_ids = run_rag_pipeline(
        db=db,
        question=question,
        business_id=business_id,
    )

    return {"messages": [AIMessage(content=answer)]}
