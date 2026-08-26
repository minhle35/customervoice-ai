"""Unit tests for pipelines/answer_generator.py — shared by VectorRAG and GraphRAG.

Deliberately has no dependency on ReviewChunk or GraphFact: generate_answer
takes a plain pre-built context string, so these tests only ever pass plain
strings, proving the function really is system-agnostic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipelines.answer_generator import generate_answer

_LLM_KWARGS = {
    "api_key": "test-key",
    "base_url": "https://api.example.com/v1",
    "model": "test-model",
}


class TestGenerateAnswer:
    def test_returns_llm_answer(self):
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Great service according to [1]."

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            answer = generate_answer(
                "How is the service?", "[1] Service was excellent.", **_LLM_KWARGS
            )

        assert answer == "Great service according to [1]."

    def test_passes_question_and_context_to_chain(self):
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "Some answer."

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            generate_answer(
                "What is the wait time?", "[1] Waited 30 minutes.", **_LLM_KWARGS
            )

        invoke_kwargs = fake_chain.invoke.call_args[0][0]
        assert invoke_kwargs["question"] == "What is the wait time?"
        assert invoke_kwargs["context"] == "[1] Waited 30 minutes."

    def test_empty_context_returns_fallback_without_calling_llm(self):
        fake_chain = MagicMock()

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            answer = generate_answer("Any question?", "", **_LLM_KWARGS)

        assert "couldn't find" in answer.lower()
        fake_chain.invoke.assert_not_called()

    def test_blank_context_treated_as_empty(self):
        fake_chain = MagicMock()

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            answer = generate_answer("Any question?", "   \n  ", **_LLM_KWARGS)

        assert "couldn't find" in answer.lower()
        fake_chain.invoke.assert_not_called()

    def test_llm_exception_propagates(self):
        fake_chain = MagicMock()
        fake_chain.invoke.side_effect = RuntimeError("LLM unavailable")

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            with pytest.raises(RuntimeError, match="LLM unavailable"):
                generate_answer("q", "[1] some evidence", **_LLM_KWARGS)

    def test_builds_chain_with_correct_credentials(self):
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "ok"

        with patch(
            "pipelines.answer_generator._build_chain", return_value=fake_chain
        ) as mock_build:
            generate_answer(
                "q",
                "[1] evidence",
                api_key="my-key",
                base_url="https://x.com",
                model="gpt-x",
            )

        mock_build.assert_called_once_with(
            api_key="my-key", base_url="https://x.com", model="gpt-x"
        )

    def test_works_with_graph_style_context_text(self):
        """Same function, GraphRAG-shaped context — proves genericity."""
        fake_chain = MagicMock()
        fake_chain.invoke.return_value = "The waiter was praised for friendliness [1]."
        graph_context = (
            '[1] (relation=praised_for, hop=1)\n"waiter" praised_for "friendliness"'
        )

        with patch("pipelines.answer_generator._build_chain", return_value=fake_chain):
            answer = generate_answer("How is the waiter?", graph_context, **_LLM_KWARGS)

        assert answer == "The waiter was praised for friendliness [1]."
