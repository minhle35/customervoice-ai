"""Unit tests for pipelines/graph_rag/service.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from pipelines.base import GraphRAGResult
from pipelines.graph_rag.retriever import GraphFact
from pipelines.graph_rag.service import run

_SETTINGS = MagicMock(
    openrouter_api_key="key",
    openrouter_base_url="https://api.example.com/v1",
    openrouter_chat_model="test-model",
)


def _make_fact(
    source_name="waiter",
    relation_type="praised_for",
    target_name="friendliness",
    review_text="Our waiter Tom was incredibly friendly.",
):
    return GraphFact(
        source_entity_id=uuid.uuid4(),
        source_name=source_name,
        relation_type=relation_type,
        target_entity_id=uuid.uuid4(),
        target_name=target_name,
        review_id=uuid.uuid4(),
        review_text=review_text,
        confidence=0.9,
        hop_distance=1,
    )


class TestGraphRagServiceRun:
    def test_no_facts_returns_honest_fallback_without_calling_llm(self):
        db = MagicMock()
        with (
            patch("pipelines.graph_rag.service.retrieve", return_value=[]),
            patch("pipelines.graph_rag.service.generate_answer") as mock_generate,
        ):
            result = run(db, "question", "biz-1", settings=_SETTINGS)

        assert isinstance(result, GraphRAGResult)
        assert result.contexts == []
        assert result.source_ids == []
        mock_generate.assert_not_called()

    def test_returns_grounded_answer_with_graph_result_shape(self):
        db = MagicMock()
        fact = _make_fact()

        with (
            patch("pipelines.graph_rag.service.retrieve", return_value=[fact]),
            patch(
                "pipelines.graph_rag.service.generate_answer",
                return_value="The waiter was praised for friendliness [1].",
            ),
        ):
            result = run(db, "How is the waiter?", "biz-1", settings=_SETTINGS)

        assert result.answer == "The waiter was praised for friendliness [1]."
        assert result.source_ids == [fact.review_id]
        # contexts must include the source review text, not just the
        # compressed triple — must match what generate_answer() actually saw.
        assert result.contexts == [
            '"waiter" praised_for "friendliness" '
            '(source: "Our waiter Tom was incredibly friendly.")'
        ]

    def test_populates_nodes_and_edges_for_topology_debugging(self):
        db = MagicMock()
        fact = _make_fact()

        with (
            patch("pipelines.graph_rag.service.retrieve", return_value=[fact]),
            patch("pipelines.graph_rag.service.generate_answer", return_value="answer"),
        ):
            result = run(db, "question", "biz-1", settings=_SETTINGS)

        node_ids = {n.id for n in result.nodes}
        assert node_ids == {str(fact.source_entity_id), str(fact.target_entity_id)}
        assert len(result.edges) == 1
        edge = result.edges[0]
        assert edge.source == str(fact.source_entity_id)
        assert edge.target == str(fact.target_entity_id)
        assert edge.relation_type == fact.relation_type
        assert edge.review_id == fact.review_id
        assert edge.weight == fact.confidence

    def test_passes_business_id_and_question_to_retrieve(self):
        db = MagicMock()
        with patch(
            "pipelines.graph_rag.service.retrieve", return_value=[]
        ) as mock_retrieve:
            run(db, "my question", "my-biz", settings=_SETTINGS, retrieve_top_k=7)

        args, kwargs = mock_retrieve.call_args
        assert args[0] is db
        assert args[1] == "my question"
        assert args[2] == "my-biz"
        assert kwargs["top_k"] == 7

    def test_accepts_rerank_top_k_for_signature_parity_but_ignores_it(self):
        """Must not raise TypeError — pipelines.registry calls both systems identically."""
        db = MagicMock()
        with patch("pipelines.graph_rag.service.retrieve", return_value=[]):
            result = run(
                db, "question", "biz-1", settings=_SETTINGS, rerank_top_k=5
            )
        assert isinstance(result, GraphRAGResult)

    def test_context_text_passed_to_generate_answer(self):
        db = MagicMock()
        fact = _make_fact()

        with (
            patch("pipelines.graph_rag.service.retrieve", return_value=[fact]),
            patch(
                "pipelines.graph_rag.service.generate_answer", return_value="answer"
            ) as mock_generate,
        ):
            run(db, "How is the waiter?", "biz-1", settings=_SETTINGS)

        call_kwargs = mock_generate.call_args.kwargs
        assert call_kwargs["question"] == "How is the waiter?"
        assert "[1]" in call_kwargs["context"]
        assert "waiter" in call_kwargs["context"]
        assert "Our waiter Tom was incredibly friendly." in call_kwargs["context"]
