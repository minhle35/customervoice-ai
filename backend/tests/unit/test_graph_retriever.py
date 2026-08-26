"""Unit tests for pipelines/graph_rag/retriever.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from pipelines.graph_rag.retriever import (
    GraphFact,
    QueryEntities,
    extract_query_entities,
    load_subgraph,
    local_search,
    match_entities,
    retrieve,
)

_SETTINGS = MagicMock()


def _make_fact(
    source_name="waiter",
    relation_type="praised_for",
    target_name="friendliness",
    review_text="Great service overall.",
    confidence=0.9,
    hop_distance=1,
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


# ---------------------------------------------------------------------------
# extract_query_entities
# ---------------------------------------------------------------------------


class TestExtractQueryEntities:
    def test_returns_entity_names_from_structured_result(self):
        fake_extractor = MagicMock()
        fake_extractor.invoke.return_value = QueryEntities(entity_names=["waiter"])

        with patch(
            "pipelines.graph_rag.retriever._build_query_entity_extractor",
            return_value=fake_extractor,
        ):
            result = extract_query_entities("What do people say about the waiter?", _SETTINGS)

        assert result == ["waiter"]

    def test_llm_exception_returns_empty_list(self):
        fake_extractor = MagicMock()
        fake_extractor.invoke.side_effect = RuntimeError("LLM down")

        with patch(
            "pipelines.graph_rag.retriever._build_query_entity_extractor",
            return_value=fake_extractor,
        ):
            result = extract_query_entities("some question", _SETTINGS)

        assert result == []

    def test_unexpected_type_returns_empty_list(self):
        fake_extractor = MagicMock()
        fake_extractor.invoke.return_value = "not structured"

        with patch(
            "pipelines.graph_rag.retriever._build_query_entity_extractor",
            return_value=fake_extractor,
        ):
            result = extract_query_entities("some question", _SETTINGS)

        assert result == []


# ---------------------------------------------------------------------------
# match_entities
# ---------------------------------------------------------------------------


class TestMatchEntities:
    def test_matches_above_threshold(self):
        entity_id = uuid.uuid4()
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            MagicMock(id=entity_id, similarity=0.9)
        ]

        with patch(
            "pipelines.graph_rag.retriever.embed_query", return_value=[0.1, 0.2]
        ):
            result = match_entities(db, "biz-1", ["waiter"])

        assert result == [str(entity_id)]

    def test_skips_below_threshold(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            MagicMock(id=uuid.uuid4(), similarity=0.2)
        ]

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=[0.1]):
            result = match_entities(db, "biz-1", ["something vague"])

        assert result == []

    def test_skips_no_rows(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=[0.1]):
            result = match_entities(db, "biz-1", ["nonexistent"])

        assert result == []

    def test_uses_query_prefix_embedding(self):
        """Query-side names embed via embed_query (query: prefix), not generate_embedding."""
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        with patch("pipelines.graph_rag.retriever.embed_query") as mock_embed_query:
            mock_embed_query.return_value = [0.1]
            match_entities(db, "biz-1", ["waiter"])

        mock_embed_query.assert_called_once_with("waiter")

    def test_returns_multiple_candidates_above_threshold_not_just_nearest(self):
        """Top-K, not top-1: several plausible matches can all seed traversal."""
        id_1, id_2, id_3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            MagicMock(id=id_1, similarity=0.9),
            MagicMock(id=id_2, similarity=0.7),
            MagicMock(id=id_3, similarity=0.3),  # below threshold
        ]

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=[0.1]):
            result = match_entities(db, "biz-1", ["staff"])

        assert set(result) == {str(id_1), str(id_2)}
        assert str(id_3) not in result

    def test_deduplicates_matches_across_names(self):
        """Two different query names matching the same entity shouldn't duplicate it."""
        entity_id = uuid.uuid4()
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            MagicMock(id=entity_id, similarity=0.9)
        ]

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=[0.1]):
            result = match_entities(db, "biz-1", ["waiter", "server"])

        assert result == [str(entity_id)]

    def test_passes_top_k_as_query_limit(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=[0.1]):
            match_entities(db, "biz-1", ["waiter"], top_k_per_name=5)

        params = db.execute.call_args[0][1]
        assert params["limit"] == 5


# ---------------------------------------------------------------------------
# load_subgraph
# ---------------------------------------------------------------------------


class TestLoadSubgraph:
    def test_builds_graph_from_rows(self):
        source_id, target_id, rel_id, review_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        row = MagicMock(
            relationship_id=rel_id,
            source_entity_id=source_id,
            source_name="waiter",
            target_entity_id=target_id,
            target_name="friendliness",
            relation_type="praised_for",
            review_id=review_id,
            review_content="Our waiter was incredibly friendly.",
            confidence=1.0,
        )
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]

        graph = load_subgraph(db, "biz-1")

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert graph.nodes[str(source_id)]["name"] == "waiter"
        assert graph.nodes[str(target_id)]["name"] == "friendliness"
        edge_data = graph.get_edge_data(str(source_id), str(target_id))
        edge_attrs = list(edge_data.values())[0]
        assert edge_attrs["relation_type"] == "praised_for"
        assert edge_attrs["review_content"] == "Our waiter was incredibly friendly."

    def test_empty_result_returns_empty_graph(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        graph = load_subgraph(db, "biz-1")

        assert graph.number_of_nodes() == 0
        assert graph.number_of_edges() == 0


# ---------------------------------------------------------------------------
# local_search
# ---------------------------------------------------------------------------


class TestLocalSearch:
    def setup_method(self):
        # local_search calls UUID(node) on every node id (production node ids
        # are always real UUID strings, from load_subgraph/match_entities) —
        # so the fixture graph needs real UUIDs too, not human-readable labels.
        self.node_a = str(uuid.uuid4())
        self.node_b = str(uuid.uuid4())
        self.node_c = str(uuid.uuid4())
        self.node_d = str(uuid.uuid4())

    def _make_graph(self):
        """A -[praised_for]-> B -[caused]-> C, plus D -[complained_about]-> A (incoming edge on A)."""
        review_id = uuid.uuid4()
        graph = nx.MultiDiGraph()
        graph.add_node(self.node_a, name="waiter")
        graph.add_node(self.node_b, name="friendliness")
        graph.add_node(self.node_c, name="good tips")
        graph.add_node(self.node_d, name="manager")
        graph.add_edge(
            self.node_a, self.node_b, key="e1", relation_type="praised_for",
            review_id=review_id, review_content="The waiter was so friendly.",
            confidence=1.0,
        )
        graph.add_edge(
            self.node_b, self.node_c, key="e2", relation_type="caused",
            review_id=review_id, review_content="That friendliness earned good tips.",
            confidence=0.8,
        )
        graph.add_edge(
            self.node_d, self.node_a, key="e3", relation_type="complained_about",
            review_id=review_id, review_content="The manager complained about the waiter.",
            confidence=0.6,
        )
        return graph

    def test_one_hop_from_seed(self):
        graph = self._make_graph()
        facts = local_search(graph, [self.node_a], max_hops=1)

        relation_types = {f.relation_type for f in facts}
        # both the outgoing (A->B) and incoming (D->A) edge on seed A
        assert relation_types == {"praised_for", "complained_about"}
        assert all(f.hop_distance == 1 for f in facts)

    def test_two_hops_reaches_second_degree_neighbor(self):
        graph = self._make_graph()
        facts = local_search(graph, [self.node_a], max_hops=2)

        relation_types = {f.relation_type for f in facts}
        assert "caused" in relation_types
        caused_fact = next(f for f in facts if f.relation_type == "caused")
        assert caused_fact.hop_distance == 2

    def test_no_duplicate_edges_when_seed_revisited(self):
        graph = self._make_graph()
        facts = local_search(graph, [self.node_a, self.node_b], max_hops=2)

        edge_keys = [(f.source_name, f.relation_type, f.target_name) for f in facts]
        assert len(edge_keys) == len(set(edge_keys))

    def test_seed_not_in_graph_returns_no_facts_for_it(self):
        graph = self._make_graph()
        facts = local_search(graph, [str(uuid.uuid4())], max_hops=2)
        assert facts == []

    def test_field_values_populated_correctly(self):
        graph = self._make_graph()
        facts = local_search(graph, [self.node_a], max_hops=1)

        praised = next(f for f in facts if f.relation_type == "praised_for")
        assert praised.source_name == "waiter"
        assert praised.target_name == "friendliness"
        assert praised.review_text == "The waiter was so friendly."
        assert isinstance(praised, GraphFact)


# ---------------------------------------------------------------------------
# retrieve (orchestration)
# ---------------------------------------------------------------------------


class TestRetrieve:
    def test_returns_empty_when_no_query_entities(self):
        db = MagicMock()
        with patch(
            "pipelines.graph_rag.retriever.extract_query_entities", return_value=[]
        ):
            result = retrieve(db, "any question", "biz-1", _SETTINGS)
        assert result == []

    def test_returns_empty_when_no_entities_matched(self):
        db = MagicMock()
        with (
            patch(
                "pipelines.graph_rag.retriever.extract_query_entities",
                return_value=["waiter"],
            ),
            patch(
                "pipelines.graph_rag.retriever.match_entities", return_value=[]
            ),
        ):
            result = retrieve(db, "How's the waiter?", "biz-1", _SETTINGS)
        assert result == []

    def test_ranks_by_hop_distance_then_confidence(self):
        db = MagicMock()
        far_fact = _make_fact(source_name="x", target_name="y", confidence=0.99, hop_distance=2)
        near_low_conf = _make_fact(source_name="a", target_name="b", confidence=0.5, hop_distance=1)
        near_high_conf = _make_fact(source_name="c", target_name="d", confidence=0.9, hop_distance=1)

        with (
            patch(
                "pipelines.graph_rag.retriever.extract_query_entities",
                return_value=["waiter"],
            ),
            patch(
                "pipelines.graph_rag.retriever.match_entities",
                return_value=["seed-1"],
            ),
            patch("pipelines.graph_rag.retriever.load_subgraph"),
            patch(
                "pipelines.graph_rag.retriever.local_search",
                return_value=[far_fact, near_low_conf, near_high_conf],
            ),
        ):
            result = retrieve(db, "question", "biz-1", _SETTINGS)

        assert result == [near_high_conf, near_low_conf, far_fact]

    def test_respects_top_k(self):
        db = MagicMock()
        facts = [_make_fact(source_name=f"s{i}", target_name=f"t{i}") for i in range(10)]

        with (
            patch(
                "pipelines.graph_rag.retriever.extract_query_entities",
                return_value=["waiter"],
            ),
            patch(
                "pipelines.graph_rag.retriever.match_entities",
                return_value=["seed-1"],
            ),
            patch("pipelines.graph_rag.retriever.load_subgraph"),
            patch("pipelines.graph_rag.retriever.local_search", return_value=facts),
        ):
            result = retrieve(db, "question", "biz-1", _SETTINGS, top_k=3)

        assert len(result) == 3
