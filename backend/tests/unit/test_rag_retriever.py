"""Unit tests for pipelines/rag/retriever.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from pipelines.rag.retriever import ReviewChunk, embed_query, rerank, retrieve


# ---------------------------------------------------------------------------
# embed_query
# ---------------------------------------------------------------------------


def test_encoder_singleton_not_reloaded():
    """_get_encoder() must return the same object on repeated calls (no reload)."""
    import pipelines.rag.retriever as mod

    original = mod._encoder
    try:
        with patch("pipelines.rag.retriever.SentenceTransformer") as MockST:
            MockST.return_value = MagicMock()
            mod._encoder = None
            first = mod._get_encoder()
            second = mod._get_encoder()
        assert first is second
        assert MockST.call_count == 1
    finally:
        mod._encoder = original


class TestEmbedQuery:
    def test_returns_list_of_floats(self):
        fake_vector = [0.1, 0.2, 0.3]
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: fake_vector)

        with patch("pipelines.rag.retriever._get_encoder", return_value=mock_model):
            result = embed_query("what do customers complain about?")

        assert result == fake_vector

    def test_uses_query_prefix(self):
        """requires 'query: ' prefix for retrieval queries."""
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.0])

        with patch("pipelines.rag.retriever._get_encoder", return_value=mock_model):
            embed_query("some question")

        call_args = mock_model.encode.call_args
        encoded_text = call_args[0][0]
        assert encoded_text.startswith("query: "), (
            f"Expected 'query: ' prefix, got: {encoded_text!r}"
        )

    def test_uses_normalize_embeddings(self):
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.0])

        with patch("pipelines.rag.retriever._get_encoder", return_value=mock_model):
            embed_query("test")

        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs.get("normalize_embeddings") is True

    def test_returns_plain_list_not_ndarray(self):
        """Output must be a Python list — str(ndarray) breaks the pgvector CAST syntax."""
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2, 0.3])

        with patch("pipelines.rag.retriever._get_encoder", return_value=mock_model):
            result = embed_query("test")

        assert isinstance(result, list)
        assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# retrieve
# ---------------------------------------------------------------------------


class TestRetrieve:
    def _make_row(
        self,
        review_id=None,
        content="great food",
        author="Alice",
        rating=4.5,
        sentiment_label="positive",
        platform="google",
        similarity_score=0.85,
    ):
        row = MagicMock()
        row.id = review_id or uuid.uuid4()
        row.content = content
        row.author = author
        row.rating = rating
        row.sentiment_label = sentiment_label
        row.platform = platform
        row.similarity_score = similarity_score
        return row

    def test_returns_review_chunks(self):
        row = self._make_row()
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]

        result = retrieve(db, [0.1, 0.2], "biz-1", top_k=5)

        assert len(result) == 1
        chunk = result[0]
        assert isinstance(chunk, ReviewChunk)
        assert chunk.review_id == row.id
        assert chunk.content == "great food"
        assert chunk.similarity_score == pytest.approx(0.85)

    def test_returns_empty_list_when_no_rows(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        result = retrieve(db, [0.1], "biz-1")

        assert result == []

    def test_passes_business_id_to_query(self):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        retrieve(db, [0.1], "my-restaurant", top_k=10)

        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["business_id"] == "my-restaurant"
        assert params["top_k"] == 10

    def test_handles_null_rating_and_author(self):
        row = self._make_row(rating=None, author=None, sentiment_label=None)
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [row]

        result = retrieve(db, [0.1], "biz-1")

        chunk = result[0]
        assert chunk.rating is None
        assert chunk.author is None
        assert chunk.sentiment_label is None

    def test_multiple_chunks_preserved_in_order(self):
        rows = [self._make_row(similarity_score=0.9 - i * 0.1) for i in range(3)]
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = rows

        result = retrieve(db, [0.1], "biz-1", top_k=3)

        assert len(result) == 3
        scores = [c.similarity_score for c in result]
        assert scores == pytest.approx([0.9, 0.8, 0.7])


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------


class TestRerank:
    def _make_chunk(self, content="text", similarity_score=0.8) -> ReviewChunk:
        return ReviewChunk(
            review_id=uuid.uuid4(),
            content=content,
            author="user",
            rating=4.0,
            sentiment_label="positive",
            platform="google",
            similarity_score=similarity_score,
        )

    def test_returns_top_k_chunks(self):
        chunks = [self._make_chunk() for _ in range(10)]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = list(range(10))  # scores 0..9

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            result = rerank("query", chunks, final_top_k=3)

        assert len(result) == 3

    def test_orders_by_rerank_score_descending(self):
        chunks = [self._make_chunk(content=f"chunk {i}") for i in range(5)]
        scores = [0.1, 0.9, 0.5, 0.3, 0.8]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = scores

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            result = rerank("query", chunks, final_top_k=5)

        result_scores = [c.rerank_score for c in result]
        assert result_scores == sorted(result_scores, reverse=True)

    def test_assigns_rerank_scores(self):
        chunks = [self._make_chunk() for _ in range(3)]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.7, 0.3, 0.9]

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            result = rerank("query", chunks, final_top_k=3)

        rerank_scores = sorted([c.rerank_score for c in result], reverse=True)
        assert rerank_scores == pytest.approx([0.9, 0.7, 0.3])

    def test_returns_empty_list_for_empty_input(self):
        result = rerank("query", [], final_top_k=5)
        assert result == []

    def test_respects_final_top_k_less_than_input(self):
        chunks = [self._make_chunk() for _ in range(20)]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = list(range(20))

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            result = rerank("query", chunks, final_top_k=5)

        assert len(result) == 5

    def test_returns_all_chunks_when_fewer_than_top_k(self):
        """When fewer chunks exist than final_top_k, return all — do not crash."""
        chunks = [self._make_chunk() for _ in range(2)]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.8, 0.3]

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            result = rerank("q", chunks, final_top_k=5)

        assert len(result) == 2

    def test_passes_query_document_pairs_to_cross_encoder(self):
        chunks = [self._make_chunk(content=f"doc {i}") for i in range(3)]
        mock_ce = MagicMock()
        mock_ce.predict.return_value = [0.5, 0.3, 0.8]

        with patch("pipelines.rag.retriever._get_cross_encoder", return_value=mock_ce):
            rerank("my query", chunks, final_top_k=3)

        pairs = mock_ce.predict.call_args[0][0]
        assert len(pairs) == 3
        assert all(p[0] == "my query" for p in pairs)
        assert [p[1] for p in pairs] == ["doc 0", "doc 1", "doc 2"]
