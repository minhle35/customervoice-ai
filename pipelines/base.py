"""Shared contract for pluggable RAG systems (VectorRAG, GraphRAG, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass
class RAGResult:
    answer: str
    # Grounding evidence as flat text — review chunks for VectorRAG, serialized
    # paths/triples for GraphRAG. Matches RAGAS's SingleTurnSample.retrieved_contexts.
    contexts: list[str]
    source_ids: list[UUID]
