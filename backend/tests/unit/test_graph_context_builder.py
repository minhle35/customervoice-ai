"""Unit tests for pipelines/graph_rag/context_builder.py."""

from __future__ import annotations

import uuid

from pipelines.graph_rag.context_builder import _estimate_tokens, build_context
from pipelines.graph_rag.retriever import GraphFact


def _make_fact(
    source_name: str = "waiter",
    relation_type: str = "praised_for",
    target_name: str = "friendliness",
    review_text: str = "Our waiter was incredibly friendly.",
    confidence: float = 1.0,
    hop_distance: int = 1,
) -> GraphFact:
    return GraphFact(
        source_entity_id=uuid.uuid4(),
        source_name=source_name,
        relation_type=relation_type,
        target_entity_id=uuid.uuid4(),
        target_name=target_name,
        review_id=uuid.uuid4(),
        review_text=review_text,
        confidence=confidence,
        hop_distance=hop_distance,
    )


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 1

    def test_approx_four_chars_per_token(self):
        assert _estimate_tokens("a" * 400) == 100


class TestBuildContext:
    def test_returns_tuple_of_string_and_list(self):
        ctx, used = build_context([_make_fact()])
        assert isinstance(ctx, str)
        assert isinstance(used, list)

    def test_single_fact_has_citation_marker(self):
        ctx, used = build_context([_make_fact(source_name="waiter")])
        assert "[1]" in ctx
        assert '"waiter"' in ctx
        assert len(used) == 1

    def test_multiple_facts_numbered_sequentially(self):
        facts = [_make_fact(source_name=f"entity{i}") for i in range(3)]
        ctx, used = build_context(facts)
        for i in range(1, 4):
            assert f"[{i}]" in ctx
        assert len(used) == 3

    def test_includes_relation_type_in_metadata(self):
        ctx, _ = build_context([_make_fact(relation_type="complained_about")])
        assert "relation=complained_about" in ctx

    def test_includes_hop_distance_in_metadata(self):
        ctx, _ = build_context([_make_fact(hop_distance=2)])
        assert "hop=2" in ctx

    def test_statement_includes_source_relation_target(self):
        ctx, _ = build_context(
            [_make_fact(source_name="waiter", relation_type="served", target_name="pho")]
        )
        assert '"waiter" served "pho"' in ctx

    def test_includes_source_review_text(self):
        """The actual review text must reach the prompt, not just the compressed
        triple — otherwise the LLM only sees "waiter praised_for friendliness"
        and never "Our waiter Tom was incredibly friendly...", which understates
        what retrieval actually found and confounds any VectorRAG comparison."""
        ctx, _ = build_context(
            [_make_fact(review_text="Our waiter Tom was incredibly friendly.")]
        )
        assert "Our waiter Tom was incredibly friendly." in ctx
        assert "Source review:" in ctx

    def test_empty_facts_returns_empty_context(self):
        ctx, used = build_context([])
        assert ctx == ""
        assert used == []

    def test_token_budget_respected(self):
        long_name = "x" * 400
        facts = [_make_fact(source_name=long_name) for _ in range(5)]
        ctx, used = build_context(facts, token_budget=150)
        assert len(used) == 1

    def test_all_facts_fit_within_generous_budget(self):
        facts = [_make_fact() for _ in range(5)]
        _, used = build_context(facts, token_budget=10000)
        assert len(used) == 5

    def test_facts_separated_by_double_newline(self):
        facts = [_make_fact(source_name="a"), _make_fact(source_name="b")]
        ctx, _ = build_context(facts, token_budget=10000)
        assert "\n\n" in ctx

    def test_preserves_input_order(self):
        """build_context doesn't re-rank — retrieve() already ranked before calling it."""
        facts = [
            _make_fact(source_name="first", hop_distance=1),
            _make_fact(source_name="second", hop_distance=2),
        ]
        _, used = build_context(facts, token_budget=10000)
        assert [f.source_name for f in used] == ["first", "second"]
