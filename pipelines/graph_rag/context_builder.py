"""Build a token-budgeted context string with citation markers from graph facts.

Mirrors pipelines/vector_rag/context_builder.py's shape exactly (same [N]
citation convention, same token-budget enforcement) so the two systems'
context strings are structurally comparable for the RAGAS/DeepEval judges,
even though the underlying evidence — graph relationships vs review chunks
— is completely different.
"""

from __future__ import annotations

from pipelines.graph_rag.retriever import GraphFact

# Rough approximation: 4 characters ≈ 1 token (good enough for budget enforcement)
_CHARS_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 2000


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def build_context(
    facts: list[GraphFact],
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> tuple[str, list[GraphFact]]:
    """Format graph facts into a numbered citation block for the LLM prompt.

    Each fact is wrapped with a [N] citation marker and serialized as a
    plain-language relationship statement. Facts are added in input order
    (retriever.retrieve() already ranked by hop_distance then confidence)
    until the token budget is exhausted.

    Returns:
        context_text: Multi-line string ready to be injected into the prompt.
        used_facts:   Subset of facts that fit within the budget (same order).

    Example output:
        [1] (relation=praised_for, hop=1)
        "waiter" praised_for "friendliness"
        Source review: "Our waiter Tom was incredibly friendly and checked
        on us several times."

        [2] (relation=complained_about, hop=1)
        "manager" complained_about "waiter"
        Source review: "The manager was rude when we complained."

    The source review line is what actually grounds the answer — the
    relationship statement alone ("waiter" praised_for "friendliness") is a
    lossy compression of it. Without the review text, the LLM (and any
    RAGAS/DeepEval judge scoring the answer) only ever sees the compressed
    triple, which understates what GraphRAG's retrieval actually found.
    """
    parts: list[str] = []
    used: list[GraphFact] = []
    tokens_used = 0

    for i, fact in enumerate(facts, start=1):
        meta = f"relation={fact.relation_type}, hop={fact.hop_distance}"
        statement = f'"{fact.source_name}" {fact.relation_type} "{fact.target_name}"'
        entry = f'[{i}] ({meta})\n{statement}\nSource review: "{fact.review_text}"'
        cost = _estimate_tokens(entry)

        if tokens_used + cost > token_budget:
            break

        parts.append(entry)
        used.append(fact)
        tokens_used += cost

    context_text = "\n\n".join(parts)
    return context_text, used
