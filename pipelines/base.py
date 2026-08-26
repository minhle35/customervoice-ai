"""Shared contract for pluggable RAG systems (VectorRAG, GraphRAG, ...)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class RAGResult:
    answer: str
    # Grounding evidence as flat text — review chunks for VectorRAG, serialized
    # paths/triples for GraphRAG. Matches RAGAS's SingleTurnSample.retrieved_contexts.
    contexts: list[str]
    source_ids: list[UUID]


@dataclass
class ChunkMetaData:
    score: float
    document_name: str
    page_number: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorRAGResult(RAGResult):
    """Adds vector-specific scores and chunk-level metadata.

    scores/chunk_metadata are parallel to contexts — index i in each list
    describes the same retrieved chunk.
    """

    scores: list[float] = field(default_factory=list)
    chunk_metadata: list[ChunkMetaData] = field(default_factory=list)


@dataclass
class GraphNode:
    id: str


@dataclass
class GraphEdge:
    source: str
    target: str
    # Previously omitted — for a graph result, relation_type is the single
    # most informative attribute of an edge (what connects source to
    # target), and dropping it left visualization/debugging with only
    # source/target ids and a bare weight, no actual graph semantics. Made
    # required (no default) since an edge without it isn't meaningful.
    relation_type: str
    review_id: UUID | None = None
    weight: float | None = None


@dataclass
class GraphRAGResult(RAGResult):
    """Adds graph topology data for visualization or multi-hop debugging."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
