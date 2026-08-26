"""Integration tests for the GraphRAG pipeline — real Postgres + pgvector.

Mirrors tests/integration/test_rag_pipeline.py's approach: only the
embedding model and LLM calls are mocked; the DB, pgvector cosine operator,
and the entities/entity_relationships JOINs are all real.

Requires: Docker DB running with pgvector extension.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import patch

from app.models.graph_entity import Entity, EntityRelationship, EntityType
from app.models.review import Review
from app.services.review_service import ReviewService

from pipelines.graph_rag.context_builder import build_context
from pipelines.graph_rag.retriever import (
    QueryEntities,
    load_subgraph,
    match_entities,
    retrieve,
)
from tests.conftest import make_review_create


def _insert_entity(
    db,
    business_id: str,
    name: str,
    embedding: list[float],
    entity_type=EntityType.staff,
) -> Entity:
    entity = Entity(
        business_id=business_id,
        name=name,
        entity_type=entity_type,
        canonical_name=name.lower(),
        name_embedding=embedding,
    )
    db.add(entity)
    db.flush()
    return entity


def _insert_relationship(
    db,
    source: Entity,
    target: Entity,
    review_id,
    relation_type: str,
    confidence: float = 1.0,
) -> EntityRelationship:
    rel = EntityRelationship(
        source_entity_id=source.id,
        target_entity_id=target.id,
        relation_type=relation_type,
        review_id=review_id,
        confidence=confidence,
    )
    db.add(rel)
    db.flush()
    return rel


class TestMatchEntitiesRoundTrip:
    def test_matches_closest_vector(self, db):
        vec_waiter = [1.0] + [0.0] * 767
        vec_dish = [0.0, 1.0] + [0.0] * 766
        query_vec = [0.99] + [0.0] * 767  # almost identical to vec_waiter

        _insert_entity(db, "biz-A", "waiter", vec_waiter)
        _insert_entity(db, "biz-A", "pho bo", vec_dish, entity_type=EntityType.dish)

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=query_vec):
            matched = match_entities(db, "biz-A", ["our waiter"])

        assert len(matched) == 1

    def test_excludes_other_businesses(self, db):
        vec = [1.0] + [0.0] * 767
        _insert_entity(db, "biz-A", "waiter", vec)
        entity_b = _insert_entity(db, "biz-B", "waiter", vec)

        with patch("pipelines.graph_rag.retriever.embed_query", return_value=vec):
            matched = match_entities(db, "biz-A", ["waiter"])

        assert str(entity_b.id) not in matched

    def test_below_threshold_returns_no_match(self, db):
        vec_a = [1.0] + [0.0] * 767
        orthogonal_query = [0.0, 1.0] + [0.0] * 766  # cosine similarity ~0
        _insert_entity(db, "biz-A", "waiter", vec_a)

        with patch(
            "pipelines.graph_rag.retriever.embed_query", return_value=orthogonal_query
        ):
            matched = match_entities(db, "biz-A", ["something unrelated"])

        assert matched == []

    def test_returns_multiple_candidates_above_threshold(self, db):
        """Real pgvector round-trip for the top-K fix — two distinct staff
        members close to the query vector should both seed traversal,
        not just whichever happens to be nearest."""
        query_vec = [1.0] + [0.0] * 767
        vec_close_1 = [0.99] + [0.01] + [0.0] * 766
        vec_close_2 = [0.98] + [0.0, 0.02] + [0.0] * 765
        vec_far = [0.0, 1.0] + [0.0] * 766

        close_1 = _insert_entity(db, "biz-A", "Tom", vec_close_1)
        close_2 = _insert_entity(db, "biz-A", "Nguyen", vec_close_2)
        _insert_entity(db, "biz-A", "unrelated", vec_far)

        with patch(
            "pipelines.graph_rag.retriever.embed_query", return_value=query_vec
        ):
            matched = match_entities(db, "biz-A", ["staff"])

        assert set(matched) == {str(close_1.id), str(close_2.id)}


class TestLoadSubgraphRoundTrip:
    def test_builds_graph_from_real_rows(self, db):
        rs_review = _make_review(db, "biz-A", "The waiter was great")
        waiter = _insert_entity(db, "biz-A", "waiter", [0.1] * 768)
        friendliness = _insert_entity(
            db, "biz-A", "friendliness", [0.2] * 768, entity_type=EntityType.other
        )
        _insert_relationship(db, waiter, friendliness, rs_review.id, "praised_for")

        graph = load_subgraph(db, "biz-A")

        assert graph.number_of_nodes() == 2
        assert graph.number_of_edges() == 1
        assert graph.nodes[str(waiter.id)]["name"] == "waiter"

    def test_excludes_other_businesses(self, db):
        review = _make_review(db, "biz-A", "review")
        a1 = _insert_entity(db, "biz-A", "e1", [0.1] * 768)
        a2 = _insert_entity(db, "biz-A", "e2", [0.2] * 768)
        _insert_relationship(db, a1, a2, review.id, "related_to")

        other_review = _make_review(db, "biz-B", "other review")
        b1 = _insert_entity(db, "biz-B", "e3", [0.3] * 768)
        b2 = _insert_entity(db, "biz-B", "e4", [0.4] * 768)
        _insert_relationship(db, b1, b2, other_review.id, "related_to")

        graph = load_subgraph(db, "biz-A")

        assert graph.number_of_nodes() == 2
        assert str(b1.id) not in graph
        assert str(b2.id) not in graph

    def test_empty_business_returns_empty_graph(self, db):
        graph = load_subgraph(db, "no-such-business")
        assert graph.number_of_nodes() == 0


class TestFullRetrieveNoLLM:
    def test_full_pipeline_round_trip(self, db):
        """extract_query_entities(mocked LLM) -> match_entities(real pgvector)
        -> load_subgraph(real SQL) -> local_search -> build_context."""
        review = _make_review(db, "biz-C", "The waiter was so friendly")
        vec = [0.5] * 768
        waiter = _insert_entity(db, "biz-C", "waiter", vec)
        friendliness = _insert_entity(
            db, "biz-C", "friendliness", vec, entity_type=EntityType.other
        )
        _insert_relationship(db, waiter, friendliness, review.id, "praised_for")

        with (
            patch(
                "pipelines.graph_rag.retriever._build_query_entity_extractor"
            ) as mock_build_extractor,
            patch("pipelines.graph_rag.retriever.embed_query", return_value=vec),
        ):
            mock_build_extractor.return_value.invoke.return_value = QueryEntities(
                entity_names=["waiter"]
            )
            facts = retrieve(db, "How is the waiter?", "biz-C", settings=None)

        assert len(facts) == 1
        assert facts[0].relation_type == "praised_for"
        # The actual review content must flow through the real JOIN in
        # load_subgraph, not just the compressed triple — this is what
        # fixes the lossy-evidence problem end-to-end, not just in mocks.
        assert facts[0].review_text == "The waiter was so friendly"

        context, used = build_context(facts)
        assert '"waiter" praised_for "friendliness"' in context
        assert "The waiter was so friendly" in context
        assert "Source review:" in context
        assert len(used) == 1


def _make_review(db, business_id: str, content: str) -> Review:
    return ReviewService(db).upsert_review(
        make_review_create(
            platform_id=f"pid-{business_id}-{content[:10]}",
            business_id=business_id,
            content=content,
        )
    )
