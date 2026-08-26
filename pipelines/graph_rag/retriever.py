"""GraphRAG retriever: query-entity matching + local graph traversal.

Local search only (README's accepted stretch: global/community-detection
search is deferred). The subgraph for a business is reloaded fresh from
Postgres on every query and traversed in-memory via networkx — no caching,
no persistent graph service. Accepted per the README's graph-storage
tradeoff: fine at this project's per-business scale (hundreds of reviews);
`load_subgraph` below is the one function that'd need to change to swap in
a real graph database later.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import networkx as nx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session

_ROOT = Path(__file__).parent.parent.parent
_BACKEND = _ROOT / "backend"
for _p in (str(_ROOT), str(_BACKEND)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.config import ServerSettings
from app.logger import get_logger

from pipelines.vector_rag.retriever import embed_query

logger = get_logger(__name__)

# Looser than extractor.py's ENTITY_RESOLUTION_SIMILARITY_THRESHOLD (0.85):
# a query mention ("the staff") is phrased more loosely than the canonical
# entity name it should match ("waiter"), so matching needs more headroom.
QUERY_ENTITY_MATCH_THRESHOLD = 0.55


# ---------------------------------------------------------------------------
# Data class — the GraphRAG equivalent of vector_rag's ReviewChunk
# ---------------------------------------------------------------------------


@dataclass
class GraphFact:
    """One traversed relationship, with provenance back to its source review.

    review_text carries the actual review content the relationship was
    extracted from — without it, the LLM (and RAGAS/DeepEval judges) only
    ever see the compressed triple ("waiter" praised_for "friendliness")
    and never the real evidence ("Our waiter Tom was incredibly friendly
    and checked on us several times"). That's a lossy-serialization problem,
    not a retrieval problem, and it would otherwise confound any VectorRAG
    vs GraphRAG comparison: a lower Faithfulness/ContextRecall score could
    mean "graph traversal picked worse evidence" or just "graph
    serialization discarded evidence that was actually there."
    """

    source_entity_id: UUID
    source_name: str
    relation_type: str
    target_entity_id: UUID
    target_name: str
    review_id: UUID
    review_text: str
    confidence: float
    hop_distance: int  # 1 = directly touches a query-matched entity


# ---------------------------------------------------------------------------
# Query-entity extraction
# ---------------------------------------------------------------------------


class QueryEntities(BaseModel):
    entity_names: list[str] = Field(
        default_factory=list,
        description=(
            "Short names of entities or topics the question is asking about "
            "(e.g. 'waiter', 'parking', 'pho bo'). Empty list if the question "
            "doesn't reference anything specific enough to name."
        ),
    )


_QUERY_ENTITY_SYSTEM_PROMPT = """\
Identify the entities or topics a customer-review question is asking about \
— staff members, dishes, service aspects, locations, or other named things.

Rules:
- Use short, consistent names, matching how they'd appear as a graph node \
(e.g. "waiter" not "the person who served us").
- If the question is too general to name anything specific (e.g. "How's the \
food overall?"), return an empty list.

Respond only with the structured JSON schema.\
"""


def _build_query_entity_extractor(settings: ServerSettings):
    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.0,
        max_tokens=200,
    )
    return llm.with_structured_output(QueryEntities, method="json_schema")


def extract_query_entities(question: str, settings: ServerSettings) -> list[str]:
    """LLM call: question -> candidate entity/topic names to seed traversal from."""
    extractor = _build_query_entity_extractor(settings)
    messages = [
        SystemMessage(content=_QUERY_ENTITY_SYSTEM_PROMPT),
        HumanMessage(content=question),
    ]
    try:
        result = extractor.invoke(messages)
    except Exception as exc:
        logger.warning(
            "Query entity extraction returned unparseable result: %s",
            exc,
            exc_info=True,
        )
        return []

    if not isinstance(result, QueryEntities):
        return []
    return result.entity_names


# ---------------------------------------------------------------------------
# Entity matching
# ---------------------------------------------------------------------------


QUERY_ENTITY_MATCH_TOP_K = 3


def match_entities(
    db: Session,
    business_id: str,
    entity_names: list[str],
    *,
    threshold: float = QUERY_ENTITY_MATCH_THRESHOLD,
    top_k_per_name: int = QUERY_ENTITY_MATCH_TOP_K,
) -> list[str]:
    """Embed each candidate name (query-side) and match against stored
    entities.name_embedding (passage-side) via cosine similarity — same
    asymmetric-embedding pattern VectorRAG uses (embed_query vs
    generate_embedding). Returns matched entity ids as strings (networkx
    node ids), deduplicated, skipping names with no match above threshold.

    Considers the top-`top_k_per_name` nearest candidates per name, not just
    the single nearest — with LIMIT 1, a query about "parking" at a business
    with no parking entity would still seed traversal from whatever's
    nearest (e.g. "service"), silently answering a different question. This
    doesn't eliminate that risk, but it stops "nearest, period" from being
    the sole criterion: multiple candidates can pass threshold and all seed
    traversal, rather than a single, possibly-mediocre one being forced through.
    """
    matched: list[str] = []
    seen: set[str] = set()
    sql = text(
        """
        SELECT id, 1 - (name_embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM entities
        WHERE business_id = :business_id
          AND name_embedding IS NOT NULL
        ORDER BY name_embedding <=> CAST(:query_vec AS vector)
        LIMIT :limit
        """
    )
    for name in entity_names:
        query_vec = embed_query(name)
        rows = db.execute(
            sql,
            {
                "query_vec": str(query_vec),
                "business_id": business_id,
                "limit": top_k_per_name,
            },
        ).fetchall()
        for row in rows:
            if row.similarity < threshold:
                continue
            entity_id = str(row.id)
            if entity_id not in seen:
                seen.add(entity_id)
                matched.append(entity_id)
    return matched


# ---------------------------------------------------------------------------
# Subgraph loading + local traversal
# ---------------------------------------------------------------------------


def load_subgraph(db: Session, business_id: str) -> nx.MultiDiGraph:
    """Load every entity_relationship for a business into an in-memory graph.

    The one function that'd need to change to swap networkx for a real graph
    database later (README's graph-storage tradeoff).
    """
    sql = text(
        """
        SELECT
            er.id AS relationship_id,
            er.source_entity_id, se.name AS source_name,
            er.target_entity_id, te.name AS target_name,
            er.relation_type, er.review_id, er.confidence,
            r.content AS review_content
        FROM entity_relationships er
        JOIN entities se ON se.id = er.source_entity_id
        JOIN entities te ON te.id = er.target_entity_id
        JOIN reviews r ON r.id = er.review_id
        WHERE se.business_id = :business_id
        """
    )
    rows = db.execute(sql, {"business_id": business_id}).fetchall()

    graph = nx.MultiDiGraph()
    for row in rows:
        source_id = str(row.source_entity_id)
        target_id = str(row.target_entity_id)
        graph.add_node(source_id, name=row.source_name)
        graph.add_node(target_id, name=row.target_name)
        graph.add_edge(
            source_id,
            target_id,
            key=str(row.relationship_id),
            relation_type=row.relation_type,
            review_id=row.review_id,
            review_content=row.review_content,
            confidence=row.confidence,
        )
    return graph


def local_search(
    graph: nx.MultiDiGraph, seed_ids: list[str], *, max_hops: int = 2
) -> list[GraphFact]:
    """BFS neighbor expansion from seed entities, following edges in both
    directions (a question about "the waiter" should surface both what the
    waiter was praised for AND what praised the waiter).
    """
    facts: list[GraphFact] = []
    visited_edges: set[tuple[str, str, str]] = set()
    seen_nodes: set[str] = set(seed_ids)
    frontier: set[str] = set(seed_ids)

    for hop in range(1, max_hops + 1):
        next_frontier: set[str] = set()
        for node in frontier:
            if node not in graph:
                continue

            for _, target, key, data in graph.out_edges(node, keys=True, data=True):
                edge_id = (node, target, key)
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                facts.append(
                    GraphFact(
                        source_entity_id=UUID(node),
                        source_name=graph.nodes[node]["name"],
                        relation_type=data["relation_type"],
                        target_entity_id=UUID(target),
                        target_name=graph.nodes[target]["name"],
                        review_id=data["review_id"],
                        review_text=data["review_content"],
                        confidence=data["confidence"],
                        hop_distance=hop,
                    )
                )
                if target not in seen_nodes:
                    next_frontier.add(target)
                    seen_nodes.add(target)

            for source, _, key, data in graph.in_edges(node, keys=True, data=True):
                edge_id = (source, node, key)
                if edge_id in visited_edges:
                    continue
                visited_edges.add(edge_id)
                facts.append(
                    GraphFact(
                        source_entity_id=UUID(source),
                        source_name=graph.nodes[source]["name"],
                        relation_type=data["relation_type"],
                        target_entity_id=UUID(node),
                        target_name=graph.nodes[node]["name"],
                        review_id=data["review_id"],
                        review_text=data["review_content"],
                        confidence=data["confidence"],
                        hop_distance=hop,
                    )
                )
                if source not in seen_nodes:
                    next_frontier.add(source)
                    seen_nodes.add(source)

        frontier = next_frontier
        if not frontier:
            break

    return facts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def retrieve(
    db: Session,
    question: str,
    business_id: str,
    settings: ServerSettings,
    *,
    max_hops: int = 2,
    top_k: int = 20,
) -> list[GraphFact]:
    """Full GraphRAG retrieval: extract query entities -> match to graph
    nodes -> load subgraph -> local traversal -> rank -> top_k.

    Ranked by hop_distance first (closer to what the question actually
    mentions is more relevant), then confidence. Returns [] if nothing in
    the question matched any known entity — the service layer treats that
    the same way vector_rag treats "no candidates" (an honest "not enough
    data" answer, not a crash).
    """
    query_entity_names = extract_query_entities(question, settings)
    if not query_entity_names:
        return []

    seed_ids = match_entities(db, business_id, query_entity_names)
    if not seed_ids:
        return []

    graph = load_subgraph(db, business_id)
    facts = local_search(graph, seed_ids, max_hops=max_hops)

    facts.sort(key=lambda f: (f.hop_distance, -f.confidence))
    return facts[:top_k]
