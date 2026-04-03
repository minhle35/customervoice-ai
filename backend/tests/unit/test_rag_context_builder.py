"""Unit tests for pipelines/rag/context_builder.py."""

from __future__ import annotations

import uuid

from pipelines.rag.context_builder import _estimate_tokens, build_context
from pipelines.rag.retriever import ReviewChunk


def _make_chunk(
    content: str = "The food was great!",
    author: str | None = "Alice",
    rating: float | None = 4.5,
    sentiment_label: str | None = "positive",
    platform: str = "google",
    rerank_score: float = 0.9,
) -> ReviewChunk:
    return ReviewChunk(
        review_id=uuid.uuid4(),
        content=content,
        author=author,
        rating=rating,
        sentiment_label=sentiment_label,
        platform=platform,
        similarity_score=0.8,
        rerank_score=rerank_score,
    )


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 1  # max(1, 0)

    def test_approx_four_chars_per_token(self):
        text = "a" * 400
        assert _estimate_tokens(text) == 100


class TestBuildContext:
    def test_returns_tuple_of_string_and_list(self):
        chunks = [_make_chunk()]
        ctx, used = build_context(chunks)
        assert isinstance(ctx, str)
        assert isinstance(used, list)

    def test_single_chunk_has_citation_marker(self):
        chunks = [_make_chunk(content="Amazing broth")]
        ctx, used = build_context(chunks)
        assert "[1]" in ctx
        assert "Amazing broth" in ctx
        assert len(used) == 1

    def test_multiple_chunks_numbered_sequentially(self):
        chunks = [_make_chunk(content=f"Review {i}") for i in range(3)]
        ctx, used = build_context(chunks)
        for i in range(1, 4):
            assert f"[{i}]" in ctx
        assert len(used) == 3

    def test_includes_platform_in_metadata(self):
        chunks = [_make_chunk(platform="reddit")]
        ctx, _ = build_context(chunks)
        assert "platform=reddit" in ctx

    def test_includes_rating_in_metadata(self):
        chunks = [_make_chunk(rating=3.5)]
        ctx, _ = build_context(chunks)
        assert "rating=3.5/5" in ctx

    def test_includes_sentiment_in_metadata(self):
        chunks = [_make_chunk(sentiment_label="negative")]
        ctx, _ = build_context(chunks)
        assert "sentiment=negative" in ctx

    def test_includes_author_in_metadata(self):
        chunks = [_make_chunk(author="Nguyen Van A")]
        ctx, _ = build_context(chunks)
        assert "author=Nguyen Van A" in ctx

    def test_skips_none_author(self):
        chunks = [_make_chunk(author=None)]
        ctx, _ = build_context(chunks)
        assert "author=" not in ctx

    def test_skips_none_rating(self):
        chunks = [_make_chunk(rating=None)]
        ctx, _ = build_context(chunks)
        assert "rating=" not in ctx

    def test_empty_chunks_returns_empty_context(self):
        ctx, used = build_context([])
        assert ctx == ""
        assert used == []

    def test_token_budget_respected(self):
        """Chunks that would exceed the budget are excluded."""
        # Each review is 400 chars ≈ 100 tokens. Budget = 150 → only first fits.
        long_content = "x" * 400
        chunks = [_make_chunk(content=long_content) for _ in range(5)]
        ctx, used = build_context(chunks, token_budget=150)
        assert len(used) == 1

    def test_all_chunks_fit_within_generous_budget(self):
        chunks = [_make_chunk(content="short review") for _ in range(5)]
        _, used = build_context(chunks, token_budget=10000)
        assert len(used) == 5

    def test_chunks_separated_by_double_newline(self):
        chunks = [_make_chunk(content="Review A"), _make_chunk(content="Review B")]
        ctx, _ = build_context(chunks, token_budget=10000)
        assert "\n\n" in ctx

    def test_used_chunks_match_context_count(self):
        long_content = "y" * 800
        chunks = [_make_chunk(content=long_content) for _ in range(10)]
        ctx, used = build_context(chunks, token_budget=300)
        # Count [N] markers in context
        marker_count = sum(1 for i in range(1, 11) if f"[{i}]" in ctx)
        assert len(used) == marker_count
