"""Lookup table for pluggable RAG systems, keyed by short name."""

from __future__ import annotations

from collections.abc import Callable

from pipelines.base import RAGResult
from pipelines.graph_rag import service as graph_rag
from pipelines.vector_rag import service as vector_rag

RAG_SYSTEMS: dict[str, Callable[..., RAGResult]] = {
    "vector": vector_rag.run,
    "graph": graph_rag.run,
}


def get_rag_system(name: str) -> Callable[..., RAGResult]:
    try:
        return RAG_SYSTEMS[name]
    except KeyError:
        raise ValueError(
            f"Unknown RAG system '{name}'. Available: {list(RAG_SYSTEMS)}"
        ) from None
