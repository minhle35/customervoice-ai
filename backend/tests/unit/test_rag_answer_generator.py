"""Unit tests for pipelines/rag/answer_generator.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from pipelines.rag.answer_generator import generate_answer
from pipelines.rag.retriever import ReviewChunk


def _make_chunk(content: str = "The service was excellent.", rerank_score: float = 0.9) -> ReviewChunk:
    return ReviewChunk(
        review_id=uuid.uuid4(),
        content=content,
        author="Tester",
        rating=5.0,
        sentiment_label="positive",
        platform="google",
        similarity_score=0.85,
        rerank_score=rerank_score,
    )


_LLM_KWARGS = dict(
    api_key="test-key",
    base_url="https://api.example.com/v1",
    model="test-model",
)


class TestGenerateAnswer:
    def test_returns_answer_and_used_chunks(self):
        chunks = [_make_chunk()]
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Great service according to [1]."

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain):
            answer, used = generate_answer("How is the service?", chunks, **_LLM_KWARGS)

        assert answer == "Great service according to [1]."
        assert len(used) == 1

    def test_passes_question_to_chain(self):
        chunks = [_make_chunk()]
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Some answer."

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain):
            generate_answer("What is the waiting time?", chunks, **_LLM_KWARGS)

        invoke_kwargs = fake_chain.invoke.call_args[0][0]
        assert invoke_kwargs["question"] == "What is the waiting time?"

    def test_passes_context_to_chain(self):
        chunks = [_make_chunk(content="Waited 30 minutes for food")]
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Long wait [1]."

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain):
            generate_answer("Wait time?", chunks, **_LLM_KWARGS)

        invoke_kwargs = fake_chain.invoke.call_args[0][0]
        assert "Waited 30 minutes for food" in invoke_kwargs["context"]

    def test_empty_chunks_returns_fallback_message(self):
        answer, used = generate_answer("Any question?", [], **_LLM_KWARGS)

        assert "couldn't find" in answer.lower() or "no" in answer.lower()
        assert used == []

    def test_empty_chunks_does_not_call_llm(self):
        fake_chain = MagicMock()

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain):
            generate_answer("Any question?", [], **_LLM_KWARGS)

        fake_chain.invoke.assert_not_called()

    def test_token_budget_limits_used_chunks(self):
        """With a tiny budget, only the first chunk should fit."""
        chunks = [_make_chunk(content="x" * 400) for _ in range(5)]
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Answer based on [1]."

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain):
            _, used = generate_answer("question", chunks, token_budget=150, **_LLM_KWARGS)

        assert len(used) == 1

    def test_builds_chain_with_correct_credentials(self):
        chunks = [_make_chunk()]
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "ok"

        with patch("pipelines.rag.answer_generator._build_chain", return_value=fake_chain) as mock_build:
            generate_answer("q", chunks, api_key="my-key", base_url="https://x.com", model="gpt-x")

        mock_build.assert_called_once_with(
            api_key="my-key", base_url="https://x.com", model="gpt-x"
        )
