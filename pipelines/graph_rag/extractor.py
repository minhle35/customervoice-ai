"""GraphRAG indexing: LLM triple extraction + embedding-based entity resolution.

This is the extraction stage VectorRAG structurally doesn't have (see the
README's GraphRAG failure-taxonomy section) — every review is turned into
zero or more (subject, predicate, object) triples, and each subject/object
name is resolved against existing `entities` rows for the same business so
minor spelling/capitalization variants of the SAME name ("Waiter" vs
"waiter ") merge into one node instead of duplicating.

Deliberately does NOT merge different names that are merely
semantically-related (e.g. "Tom" and "the waiter") — see
ENTITY_RESOLUTION_SIMILARITY_THRESHOLD and the extraction prompt's
name-specificity rule below. The README's flagship GraphRAG example is
"Which staff members are linked to both praise and complaints?" — that
question is unanswerable if every staff member collapses into one generic
"waiter" node, which is exactly what a low similarity threshold combined
with a prompt that encourages generic names would cause.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
from app.models.graph_entity import Entity, EntityRelationship, EntityType
from app.models.review import Review

from pipelines.embeddings.generate_embeddings import generate_embedding

logger = get_logger(__name__)

# Cosine similarity above which a candidate entity name is merged into an
# existing node rather than creating a new one. See resolve_entity().
#
# Deliberately high (near-duplicate territory for e5 embeddings, not general
# semantic-similarity territory): the exact-canonical-name check above
# already handles true repeat mentions for free. This embedding fallback
# exists only to catch spelling/capitalization/phrasing variants of the
# SAME name that normalize() doesn't — not to cluster genuinely different
# names ("Tom" vs "the waiter") that happen to be topically related. A
# lower threshold here is exactly what would silently collapse distinct
# staff members into one node.
ENTITY_RESOLUTION_SIMILARITY_THRESHOLD = 0.90


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


class Triple(BaseModel):
    subject: str = Field(
        description=(
            "Short, consistent name of the source entity, e.g. 'waiter', "
            "'pho bo', 'parking lot'. Not a full sentence."
        )
    )
    subject_type: EntityType
    predicate: str = Field(
        description=(
            "Relationship expressed in the review, as a short snake_case "
            "verb phrase, e.g. 'praised_for', 'complained_about', 'served'"
        )
    )
    object: str = Field(description="Short, consistent name of the target entity")
    object_type: EntityType


class ExtractionResult(BaseModel):
    triples: list[Triple] = Field(default_factory=list)


_SYSTEM_PROMPT = """\
You are extracting a knowledge graph from a single customer review.

Identify entities mentioned in the review — staff members, dishes, service \
aspects (e.g. "parking", "wait time", "noise level"), locations, or other \
named things — and the relationships between them expressed in the text \
(e.g. "praised_for", "complained_about", "served", "recommended").

Rules:
- Only extract what the review actually states. Do not infer facts not present.
- If the review names a SPECIFIC person (e.g. "Tom", "Nguyen", "our server \
Maria"), use that specific name as the entity. Do NOT generalize it to a \
role like "waiter" — a business can have several waiters, and collapsing \
them all into one generic name makes it impossible to tell which one a \
review is actually about.
- Only use a short role/category name (e.g. "waiter", "manager", "chef") \
when the review gives NO specific name for that person — never as a \
default when a name is available.
- For non-person entities (dishes, service aspects, locations), keep names \
short and consistent (e.g. "parking lot", not "the parking lot behind the \
building").
- predicate must be a short snake_case verb phrase.
- If the review has nothing extractable, return an empty triples list.

Respond only with the structured JSON schema. Do not add explanations outside it.\
"""


def _build_extractor(settings: ServerSettings):
    """Build the structured-output runnable. Separate function so tests can
    patch it directly, mirroring pipelines/vector_rag/answer_generator.py's
    _build_chain seam."""
    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.0,
        max_tokens=800,
    )
    # method="json_schema": OpenRouter doesn't support tool-calling for every
    # model — same reasoning as agents/nodes/intent.py's classifier.
    return llm.with_structured_output(ExtractionResult, method="json_schema")


def extract_triples(review_text: str, settings: ServerSettings) -> list[Triple]:
    """LLM call: review text -> list of (subject, predicate, object) triples.

    Mirrors agents/nodes/intent.py's with_structured_output pattern: same
    fail-soft behavior — an unparseable result logs a warning and returns
    an empty list rather than raising, so one bad review doesn't abort a
    whole ingestion batch.
    """
    if not review_text.strip():
        return []

    extractor = _build_extractor(settings)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=review_text),
    ]
    try:
        result = extractor.invoke(messages)
    except Exception as exc:
        logger.warning(
            "Entity extraction returned unparseable result: %s", exc, exc_info=True
        )
        return []

    if not isinstance(result, ExtractionResult):
        logger.warning("Entity extraction returned unexpected type: %s", type(result))
        return []

    return result.triples


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    return " ".join(name.strip().lower().split())


def resolve_entity(
    db: Session,
    business_id: str,
    name: str,
    entity_type: EntityType,
) -> Entity:
    """Find-or-create an Entity for `name`, merging near-duplicates by embedding similarity.

    Exact canonical_name match is checked first (cheap, no LLM/embedding
    call needed on repeat mentions of the same entity). Otherwise, embeds
    the candidate name with the same generate_embedding() VectorRAG uses
    for review chunks (`passage:` prefix) and compares against existing
    entities for this business+type via pgvector cosine distance — this is
    the README's stated "embeddings for entity resolution" decision.

    Does not commit — caller controls the transaction so a whole review's
    triples land atomically.
    """
    canonical = _normalize(name)

    existing = (
        db.query(Entity)
        .filter(
            Entity.business_id == business_id,
            Entity.entity_type == entity_type,
            Entity.canonical_name == canonical,
        )
        .first()
    )
    if existing is not None:
        return existing

    embedding = generate_embedding(name)

    sql = text(
        """
        SELECT id, 1 - (name_embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM entities
        WHERE business_id = :business_id
          AND entity_type = :entity_type
          AND name_embedding IS NOT NULL
        ORDER BY name_embedding <=> CAST(:query_vec AS vector)
        LIMIT 1
        """
    )
    row = db.execute(
        sql,
        {
            "query_vec": str(embedding),
            "business_id": business_id,
            "entity_type": entity_type.value,
        },
    ).fetchone()

    if row is not None and row.similarity >= ENTITY_RESOLUTION_SIMILARITY_THRESHOLD:
        match = db.get(Entity, row.id)
        if match is not None:
            # Audit trail for embedding-based (non-exact) merges — the
            # riskier merge path, since it's not a literal string match.
            # Worth being able to inspect later when validating entity
            # resolution quality (e.g. for the Layer 3 entity_connectivity
            # diagnostic).
            logger.info(
                "Entity resolution: merged %r into existing entity %r "
                "(business_id=%s, type=%s, similarity=%.3f)",
                name,
                match.name,
                business_id,
                entity_type.value,
                row.similarity,
            )
            return match

    entity = Entity(
        business_id=business_id,
        name=name,
        entity_type=entity_type,
        canonical_name=canonical,
        name_embedding=embedding,
    )
    db.add(entity)
    db.flush()  # assign entity.id without committing
    return entity


# ---------------------------------------------------------------------------
# Per-review orchestration
# ---------------------------------------------------------------------------


def extract_and_persist(db: Session, review: Review, settings: ServerSettings) -> int:
    """Extract triples from one review and persist them as entities/relationships.

    Marks review.graph_extracted = True regardless of whether any triples
    were found (an empty review body is a legitimate zero-triple outcome,
    not a failure to retry). Returns the number of relationships stored.
    """
    triples = extract_triples(review.content, settings)

    for triple in triples:
        subject = resolve_entity(
            db, review.business_id, triple.subject, triple.subject_type
        )
        obj = resolve_entity(db, review.business_id, triple.object, triple.object_type)

        db.add(
            EntityRelationship(
                source_entity_id=subject.id,
                target_entity_id=obj.id,
                relation_type=triple.predicate,
                review_id=review.id,
            )
        )

    review.graph_extracted = True
    db.flush()
    return len(triples)
