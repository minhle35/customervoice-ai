"""GraphRAG orchestration: extract query entities → traverse graph → answer.

Mirrors pipelines/vector_rag/service.py's shape exactly — same signature,
same shared answer_generator, same RAGResult contract — so
pipelines/registry.py and the eval harness can swap between the two systems
without knowing which one they're calling.
"""

from __future__ import annotations

from app.config import ServerSettings
from sqlalchemy.orm import Session

from pipelines.answer_generator import generate_answer
from pipelines.base import GraphEdge, GraphNode, GraphRAGResult
from pipelines.graph_rag.context_builder import build_context
from pipelines.graph_rag.retriever import retrieve


def run(
    db: Session,
    question: str,
    business_id: str,
    *,
    settings: ServerSettings,
    retrieve_top_k: int = 20,
    rerank_top_k: int = 5,
    token_budget: int = 2000,
) -> GraphRAGResult:
    """Full GraphRAG pipeline: extract query entities → traverse → answer.

    Args:
        db:             SQLAlchemy session (injected via FastAPI dependency).
        question:       User's natural language question.
        business_id:    Filter the graph to this business.
        settings:       Server settings (OpenRouter credentials/model).
        retrieve_top_k: Max graph facts kept after ranking (mirrors VectorRAG's
                        retrieve_top_k so both systems accept the same call
                        signature; GraphRAG has no separate rerank stage, so
                        rerank_top_k is accepted but unused here).
        rerank_top_k:   Unused — present only for signature parity with
                        VectorRAG (see pipelines/registry.py).
        token_budget:   Max tokens allocated for graph-fact context in the
                        LLM prompt.
    """
    del rerank_top_k  # signature parity with vector_rag.run(); no rerank stage here

    facts = retrieve(db, question, business_id, settings, top_k=retrieve_top_k)

    if not facts:
        return GraphRAGResult(
            answer=(
                "I don't have enough graph data for this business yet, or "
                "your question doesn't reference anything I've indexed. "
                "Please ingest more reviews or ask about a specific person, "
                "dish, or aspect of the business."
            ),
            contexts=[],
            source_ids=[],
        )

    context_text, used_facts = build_context(facts, token_budget=token_budget)

    if not used_facts:
        return GraphRAGResult(
            answer="I couldn't find any relevant graph evidence to answer your question.",
            contexts=[],
            source_ids=[],
        )

    answer = generate_answer(
        question=question,
        context=context_text,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
    )

    nodes = {
        node_id: GraphNode(id=node_id)
        for fact in used_facts
        for node_id in (str(fact.source_entity_id), str(fact.target_entity_id))
    }
    edges = [
        GraphEdge(
            source=str(fact.source_entity_id),
            target=str(fact.target_entity_id),
            relation_type=fact.relation_type,
            review_id=fact.review_id,
            weight=fact.confidence,
        )
        for fact in used_facts
    ]

    return GraphRAGResult(
        answer=answer,
        # Includes review_text, not just the relationship statement — must
        # match what generate_answer() actually saw in context_text (built
        # from the same used_facts), or a RAGAS/DeepEval judge would score
        # faithfulness against evidence the LLM was never shown.
        contexts=[
            f'"{fact.source_name}" {fact.relation_type} "{fact.target_name}" '
            f'(source: "{fact.review_text}")'
            for fact in used_facts
        ],
        source_ids=[fact.review_id for fact in used_facts],
        nodes=list(nodes.values()),
        edges=edges,
    )
