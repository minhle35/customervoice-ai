"""Unit tests for agents/nodes/rag.py — the RAG orchestration node.

rag_node delegates to run_rag_pipeline from app.services.rag_service.
All patches target agents.nodes.rag.run_rag_pipeline, not the individual
pipeline functions (embed_query / retrieve / rerank / generate_answer).
"""

from __future__ import annotations

import uuid
from unittest.mock import ANY, MagicMock, patch

import pytest

from agents.nodes.rag import rag_node
from agents.state import AgentState
from langchain_core.messages import AIMessage, HumanMessage


def _make_state(
    question: str = "What do customers say?",
    business_id: str = "biz-1",
) -> AgentState:
    return AgentState(
        messages=[HumanMessage(content=question)],
        business_id=business_id,
        thread_id="thread-1",
        intent="rag",
        intent_confidence=0.95,
        intent_reasoning="retrieval question",
        pending_ingestion=None,
        approved=None,
    )


class TestRagNode:
    def test_returns_ai_message(self, mock_settings):
        """rag_node must append an AIMessage to the messages list."""
        state = _make_state()
        fake_id = uuid.uuid4()

        with patch(
            "agents.nodes.rag.run_rag_pipeline",
            return_value=("Great food [1].", [fake_id]),
        ):
            result = rag_node(state, db=MagicMock(), settings=mock_settings)

        assert any(isinstance(m, AIMessage) for m in result["messages"])
        assert result["messages"][-1].content == "Great food [1]."

    def test_no_human_message_returns_fallback(self, mock_settings):
        """When there is no HumanMessage in state, return a safe fallback."""
        state = AgentState(
            messages=[],
            business_id="biz-1",
            thread_id="thread-1",
            intent="rag",
            intent_confidence=0.9,
            intent_reasoning="r",
            pending_ingestion=None,
            approved=None,
        )

        result = rag_node(state, db=MagicMock(), settings=mock_settings)

        assert any(isinstance(m, AIMessage) for m in result["messages"])
        assert result["messages"][-1].content  # non-empty

    def test_no_reviews_returns_graceful_message(self, mock_settings):
        """When run_rag_pipeline signals no reviews, the answer is still returned."""
        state = _make_state()
        no_reviews_msg = (
            "I don't have any reviews for this business yet. "
            "Please ingest some reviews first."
        )

        with patch(
            "agents.nodes.rag.run_rag_pipeline",
            return_value=(no_reviews_msg, []),
        ):
            result = rag_node(state, db=MagicMock(), settings=mock_settings)

        answer_text = result["messages"][-1].content.lower()
        assert "reviews" in answer_text or "ingest" in answer_text

    def test_uses_business_id_from_state(self, mock_settings):
        """run_rag_pipeline must be called with the business_id from AgentState."""
        state = _make_state(business_id="specific-biz-123")

        with patch(
            "agents.nodes.rag.run_rag_pipeline",
            return_value=("Answer.", []),
        ) as mock_pipeline:
            rag_node(state, db=MagicMock(), settings=mock_settings)

        mock_pipeline.assert_called_once_with(
            db=ANY,
            question=ANY,
            business_id="specific-biz-123",
        )
