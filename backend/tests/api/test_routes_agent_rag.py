"""API tests for POST /api/agent/ask — RAG intent path.

Uses the TestClient with a mocked DB session (no Docker/Postgres required —
`db` is never actually queried once the intent classifier and RAG pipeline
are mocked below). Routing, request validation, and the HTTP contract are
still exercised for real.

Patch targets:
  agents.nodes.intent.intent_node  — looked up fresh each time _get_graph() runs
  agents.nodes.rag.run_rag_pipeline — module-level import in rag_node
  app.api.routes_agent.check_in_scope — scope guard, mocked in_scope=True
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.database.database import get_db
from app.main import app
from app.services.scope_guard import ScopeCheck
from fastapi.testclient import TestClient

_RAG_INTENT = {
    "intent": "rag",
    "intent_confidence": 0.95,
    "intent_reasoning": "retrieval question",
}

_MOCK_ANSWER = "Customers love the food [1]."


@pytest.fixture()
def client():
    """TestClient with a mocked DB session — shadows conftest's Docker-backed one."""
    app.dependency_overrides[get_db] = lambda: MagicMock()
    in_scope = ScopeCheck(in_scope=True, reason="test — scope guard mocked")
    with patch("app.api.routes_agent.check_in_scope", return_value=in_scope):
        yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def rag_client(client):
    """TestClient with intent classifier and RAG pipeline both mocked."""
    with (
        patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT),
        patch("agents.nodes.rag.run_rag_pipeline", return_value=(_MOCK_ANSWER, [])),
    ):
        yield client


class TestAskAgentRagIntent:
    def test_returns_200_with_answer(self, rag_client):
        """Full path: POST /api/agent/ask → intent=rag → answer returned."""
        resp = rag_client.post(
            "/api/agent/ask",
            json={
                "question": "What do customers say about the food?",
                "business_id": "biz-test",
                "thread_id": "thread-abc",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert data["answer"]
        assert data["pending_approval"] is False

    def test_echoes_thread_id(self, rag_client):
        """thread_id sent in the request must appear in the response."""
        resp = rag_client.post(
            "/api/agent/ask",
            json={
                "question": "Any feedback on service?",
                "business_id": "biz-1",
                "thread_id": "my-session-id",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "my-session-id"

    def test_no_reviews_graceful_response(self, client):
        """When no reviews exist, the agent should return a message — not 500."""
        no_reviews_msg = (
            "I don't have any reviews for this business yet. "
            "Please ingest some reviews first."
        )

        with (
            patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT),
            patch(
                "agents.nodes.rag.run_rag_pipeline", return_value=(no_reviews_msg, [])
            ),
        ):
            resp = client.post(
                "/api/agent/ask",
                json={
                    "question": "Tell me about the menu",
                    "business_id": "non-existent-biz",
                    "thread_id": "thread-xyz",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["answer"]

    def test_llm_error_returns_500(self, client):
        """If run_rag_pipeline raises, the endpoint must return HTTP 500."""
        with (
            patch("agents.nodes.intent.intent_node", return_value=_RAG_INTENT),
            patch(
                "agents.nodes.rag.run_rag_pipeline",
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            resp = client.post(
                "/api/agent/ask",
                json={
                    "question": "question",
                    "business_id": "biz",
                    "thread_id": "t-err",
                },
            )

        assert resp.status_code == 500
