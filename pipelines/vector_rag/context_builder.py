"""Build a token-budgeted context string with citation markers from retrieved chunks."""

from __future__ import annotations

from pipelines.vector_rag.retriever import ReviewChunk

# Rough approximation: 4 characters ≈ 1 token (good enough for budget enforcement)
_CHARS_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 2000


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def build_context(
    chunks: list[ReviewChunk],
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> tuple[str, list[ReviewChunk]]:
    """Format chunks into a numbered citation block for the LLM prompt.

    Each chunk is wrapped with a [N] citation marker and metadata header.
    Chunks are added in order (highest rerank_score first) until the token
    budget is exhausted.

    Returns:
        context_text: Multi-line string ready to be injected into the prompt.
        used_chunks:  Subset of chunks that fit within the budget (same order).

    Example output:
        [1] (platform=google, rating=2.0/5, sentiment=negative, author=Nguyen Van A)
        The food was cold and the service was slow...

        [2] (platform=google, rating=5.0/5, sentiment=positive)
        Best pho in town! The broth is absolutely amazing...
    """
    parts: list[str] = []
    used: list[ReviewChunk] = []
    tokens_used = 0

    for i, chunk in enumerate(chunks, start=1):
        meta_parts: list[str] = []
        if chunk.platform:
            meta_parts.append(f"platform={chunk.platform}")
        if chunk.rating is not None:
            meta_parts.append(f"rating={chunk.rating}/5")
        if chunk.sentiment_label:
            meta_parts.append(f"sentiment={chunk.sentiment_label}")
        if chunk.author:
            meta_parts.append(f"author={chunk.author}")

        meta = ", ".join(meta_parts)
        entry = f"[{i}] ({meta})\n{chunk.content}"
        cost = _estimate_tokens(entry)

        if tokens_used + cost > token_budget:
            break

        parts.append(entry)
        used.append(chunk)
        tokens_used += cost

    context_text = "\n\n".join(parts)
    return context_text, used
