"""API tests for POST /api/agent/ask — RAG intent path.

Uses the TestClient + real DB (rolled back per test). Both the intent
classifier and the RAG pipeline are mocked so these tests exercise routing,
state management, and HTTP contract without incurring LLM costs.

Patch targets:
  agents.nodes.intent.intent_node  — looked up fresh each time _get_graph() runs
  agents.nodes.rag.run_rag_pipeline — module-level import in rag_node
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

_RAG_INTENT = {
    "intent": "rag",
    "intent_confidence": 0.95,
    "intent_reasoning": "retrieval question",
}

_MOCK_ANSWER = "Customers love the food [1]."


@pytest.fixture()
def rag_client(client):
    """TestClient with intent classifier and RAG pipeline both mocked."""
    with patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT), \
         patch("agents.nodes.rag.run_rag_pipeline", return_value=(_MOCK_ANSWER, [])):
        yield client


class TestAskAgentRagIntent:
    def test_returns_200_with_answer(self, rag_client):
        """Full path: POST /api/agent/ask → intent=rag → answer returned."""
        resp = rag_client.post("/api/agent/ask", json={
            "question": "What do customers say about the food?",
            "business_id": "biz-test",
            "thread_id": "thread-abc",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"]
        assert data["pending_approval"] is False

    def test_echoes_thread_id(self, rag_client):
        """thread_id sent in the request must appear in the response."""
        resp = rag_client.post("/api/agent/ask", json={
            "question": "Any feedback on service?",
            "business_id": "biz-1",
            "thread_id": "my-session-id",
        })

        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "my-session-id"

    def test_no_reviews_graceful_response(self, client):
        """When no reviews exist, the agent should return a message — not 500."""
        no_reviews_msg = (
            "I don't have any reviews for this business yet. "
            "Please ingest some reviews first."
        )

        with patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT), \
             patch("agents.nodes.rag.run_rag_pipeline", return_value=(no_reviews_msg, [])):
            resp = client.post("/api/agent/ask", json={
                "question": "Tell me about the menu",
                "business_id": "non-existent-biz",
                "thread_id": "thread-xyz",
            })

        assert resp.status_code == 200
        assert resp.json()["answer"]

    def test_llm_error_returns_500(self, client):
        """If run_rag_pipeline raises, the endpoint must return HTTP 500."""
        with patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT), \
             patch(
                 "agents.nodes.rag.run_rag_pipeline",
                 side_effect=RuntimeError("LLM down"),
             ):
            resp = client.post("/api/agent/ask", json={
                "question": "question",
                "business_id": "biz",
                "thread_id": "t-err",
            })

        assert resp.status_code == 500
