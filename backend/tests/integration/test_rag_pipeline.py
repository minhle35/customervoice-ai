"""Integration tests for the RAG retrieval pipeline — real pgvector DB.

These tests validate what unit tests cannot: that the actual SQL query works
correctly against a real pgvector instance. Only the embedding model and
cross-encoder are mocked; the DB, pgvector operator (=>), HNSW index, and
the JOIN between review_embeddings and reviews are all real.

Requires: Docker DB running with pgvector extension.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.embedding import ReviewEmbedding
from app.services.review_service import ReviewService
from pipelines.vector_rag.context_builder import build_context
from pipelines.vector_rag.retriever import embed_query, rerank, retrieve
from tests.conftest import make_review_create


def _insert_embedding(db, review_id, vec: list[float]) -> None:
    """Add a ReviewEmbedding directly via ORM (no commit) to stay within the rollback."""
    emb = ReviewEmbedding(review_id=review_id, embedding=vec, model="test")
    db.add(emb)
    db.flush()


class TestRetrieveRoundTrip:
    def test_returns_closest_vector(self, db):
        """The embedding closest to the query vector must rank first."""
        rs = ReviewService(db)

        r1 = rs.upsert_review(make_review_create(content="Excellent food", business_id="biz-A"))
        r2 = rs.upsert_review(make_review_create(
            platform_id="pid-2", content="Terrible service", business_id="biz-A"
        ))

        vec_r1 = [1.0] + [0.0] * 767      # unit vector in dim 0
        vec_r2 = [0.0, 1.0] + [0.0] * 766  # unit vector in dim 1
        query_vec = [0.99] + [0.0] * 767   # almost identical to vec_r1

        _insert_embedding(db, r1.id, vec_r1)
        _insert_embedding(db, r2.id, vec_r2)

        results = retrieve(db, query_vec, "biz-A", top_k=2)

        assert len(results) == 2
        assert results[0].review_id == r1.id
        assert results[0].similarity_score > results[1].similarity_score

    def test_excludes_other_businesses(self, db):
        """Reviews from a different business must never appear in results."""
        rs = ReviewService(db)

        r_a = rs.upsert_review(make_review_create(
            platform_id="pa", business_id="biz-A", content="Review A"
        ))
        r_b = rs.upsert_review(make_review_create(
            platform_id="pb", business_id="biz-B", content="Review B"
        ))

        identical_vec = [1.0] + [0.0] * 767
        _insert_embedding(db, r_a.id, identical_vec)
        _insert_embedding(db, r_b.id, identical_vec)

        results = retrieve(db, identical_vec, "biz-A", top_k=10)
        returned_ids = {r.review_id for r in results}

        assert r_a.id in returned_ids
        assert r_b.id not in returned_ids

    def test_respects_top_k(self, db):
        """retrieve() must return at most top_k results even when more exist."""
        rs = ReviewService(db)

        for i in range(10):
            r = rs.upsert_review(make_review_create(
                platform_id=f"topk-{i}",
                content=f"Review {i}",
                business_id="biz-topk",
            ))
            _insert_embedding(db, r.id, [float(i) / 10] + [0.0] * 767)

        results = retrieve(db, [0.5] + [0.0] * 767, "biz-topk", top_k=3)

        assert len(results) <= 3

    def test_empty_db_returns_empty_list(self, db):
        """No data for a business → empty list, no error."""
        results = retrieve(db, [0.1] * 768, "no-such-business", top_k=20)
        assert results == []

    def test_full_pipeline_no_llm(self, db):
        """embed(mocked) → retrieve(real pgvector) → rerank(mocked) → build_context."""
        rs = ReviewService(db)

        r = rs.upsert_review(make_review_create(
            platform_id="dim-sum-1",
            content="Amazing dim sum",
            business_id="biz-C",
        ))
        fake_vec = [0.5] * 768
        _insert_embedding(db, r.id, fake_vec)

        with patch("pipelines.vector_rag.retriever._get_encoder") as mock_enc, \
             patch("pipelines.vector_rag.retriever._get_cross_encoder") as mock_ce:

            mock_enc.return_value.encode.return_value = MagicMock(
                tolist=lambda: fake_vec
            )
            mock_ce.return_value.predict.return_value = [0.9]

            query_vec = embed_query("dim sum quality")
            candidates = retrieve(db, query_vec, "biz-C", top_k=20)
            reranked = rerank("dim sum quality", candidates, final_top_k=5)
            context, used = build_context(reranked)

        assert len(candidates) == 1
        assert len(reranked) == 1
        assert "Amazing dim sum" in context
        assert "[1]" in context
