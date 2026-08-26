"""Unit tests for pipelines/graph_rag/extractor.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.graph_entity import Entity, EntityType
from pipelines.graph_rag.extractor import (
    ExtractionResult,
    Triple,
    extract_and_persist,
    extract_triples,
    resolve_entity,
)

_SETTINGS = MagicMock()


# ---------------------------------------------------------------------------
# extract_triples
# ---------------------------------------------------------------------------


class TestExtractTriples:
    def test_empty_text_returns_empty_list_without_calling_llm(self):
        fake_extractor = MagicMock()

        with patch(
            "pipelines.graph_rag.extractor._build_extractor",
            return_value=fake_extractor,
        ):
            result = extract_triples("   ", _SETTINGS)

        assert result == []
        fake_extractor.invoke.assert_not_called()

    def test_returns_triples_from_structured_result(self):
        triple = Triple(
            subject="waiter",
            subject_type=EntityType.staff,
            predicate="praised_for",
            object="friendliness",
            object_type=EntityType.other,
        )
        fake_extractor = MagicMock()
        fake_extractor.invoke.return_value = ExtractionResult(triples=[triple])

        with patch(
            "pipelines.graph_rag.extractor._build_extractor",
            return_value=fake_extractor,
        ):
            result = extract_triples("The waiter was so friendly!", _SETTINGS)

        assert result == [triple]

    def test_llm_exception_returns_empty_list(self):
        """A bad review shouldn't abort a whole extraction batch."""
        fake_extractor = MagicMock()
        fake_extractor.invoke.side_effect = RuntimeError("LLM unavailable")

        with patch(
            "pipelines.graph_rag.extractor._build_extractor",
            return_value=fake_extractor,
        ):
            result = extract_triples("some review", _SETTINGS)

        assert result == []

    def test_unexpected_return_type_returns_empty_list(self):
        fake_extractor = MagicMock()
        fake_extractor.invoke.return_value = "not a structured result"

        with patch(
            "pipelines.graph_rag.extractor._build_extractor",
            return_value=fake_extractor,
        ):
            result = extract_triples("some review", _SETTINGS)

        assert result == []


# ---------------------------------------------------------------------------
# resolve_entity
# ---------------------------------------------------------------------------


class TestResolveEntity:
    def test_exact_canonical_match_short_circuits_embedding(self):
        existing = Entity(
            id=uuid.uuid4(),
            business_id="biz-1",
            name="Waiter",
            entity_type=EntityType.staff,
            canonical_name="waiter",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        with patch("pipelines.graph_rag.extractor.generate_embedding") as mock_embed:
            result = resolve_entity(db, "biz-1", "Waiter", EntityType.staff)

        assert result is existing
        mock_embed.assert_not_called()
        db.add.assert_not_called()

    def test_similarity_match_above_threshold_reuses_entity(self):
        """Embedding fallback is meant to catch spelling/phrasing variants of
        the SAME name ("Tom" vs "tom "), not merge genuinely different names
        ("Tom" vs "waiter") just because they're topically related — see
        ENTITY_RESOLUTION_SIMILARITY_THRESHOLD's docstring."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        matched_id = uuid.uuid4()
        matched_entity = Entity(
            id=matched_id,
            business_id="biz-1",
            name="Tom",
            entity_type=EntityType.staff,
            canonical_name="tom",
        )
        row = MagicMock(id=matched_id, similarity=0.95)
        db.execute.return_value.fetchone.return_value = row
        db.get.return_value = matched_entity

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1, 0.2],
        ):
            result = resolve_entity(db, "biz-1", "TOM", EntityType.staff)

        assert result is matched_entity
        db.add.assert_not_called()

    def test_similarity_at_exactly_threshold_reuses_entity(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        matched_id = uuid.uuid4()
        matched_entity = Entity(id=matched_id, business_id="biz-1", name="Tom")
        row = MagicMock(id=matched_id, similarity=0.90)  # exactly at threshold
        db.execute.return_value.fetchone.return_value = row
        db.get.return_value = matched_entity

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1],
        ):
            result = resolve_entity(db, "biz-1", "Tom.", EntityType.staff)

        assert result is matched_entity

    def test_moderately_similar_generic_name_does_not_merge(self):
        """A name that's merely topically related — not a spelling variant of
        the SAME name — must NOT merge, even at a similarity that would have
        passed the old 0.85 threshold. This is the regression test for the
        "distinct staff members collapse into one 'waiter' node" bug."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        row = MagicMock(id=uuid.uuid4(), similarity=0.87)  # above old 0.85, below new 0.90
        db.execute.return_value.fetchone.return_value = row

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1],
        ):
            result = resolve_entity(db, "biz-1", "Tom", EntityType.staff)

        db.add.assert_called_once()
        assert result.name == "Tom"

    def test_embedding_merge_logs_audit_trail(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        matched_id = uuid.uuid4()
        matched_entity = Entity(id=matched_id, business_id="biz-1", name="Tom")
        row = MagicMock(id=matched_id, similarity=0.95)
        db.execute.return_value.fetchone.return_value = row
        db.get.return_value = matched_entity

        with (
            patch(
                "pipelines.graph_rag.extractor.generate_embedding",
                return_value=[0.1],
            ),
            patch("pipelines.graph_rag.extractor.logger") as mock_logger,
        ):
            resolve_entity(db, "biz-1", "TOM", EntityType.staff)

        mock_logger.info.assert_called_once()

    def test_no_match_creates_new_entity(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.execute.return_value.fetchone.return_value = None

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1, 0.2],
        ):
            result = resolve_entity(db, "biz-1", "Parking Lot", EntityType.location)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added is result
        assert result.business_id == "biz-1"
        assert result.name == "Parking Lot"
        assert result.canonical_name == "parking lot"
        assert result.entity_type == EntityType.location
        db.flush.assert_called_once()

    def test_below_threshold_similarity_creates_new_entity_not_reuse(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        row = MagicMock(id=uuid.uuid4(), similarity=0.5)  # below 0.85 threshold
        db.execute.return_value.fetchone.return_value = row

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1, 0.2],
        ):
            resolve_entity(db, "biz-1", "sommelier", EntityType.staff)

        db.add.assert_called_once()

    def test_canonical_name_normalizes_whitespace_and_case(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.execute.return_value.fetchone.return_value = None

        with patch(
            "pipelines.graph_rag.extractor.generate_embedding",
            return_value=[0.1],
        ):
            result = resolve_entity(db, "biz-1", "  The   Waiter  ", EntityType.staff)

        assert result.canonical_name == "the waiter"


# ---------------------------------------------------------------------------
# extract_and_persist
# ---------------------------------------------------------------------------


class TestExtractAndPersist:
    def _make_review(self):
        review = MagicMock()
        review.id = uuid.uuid4()
        review.business_id = "biz-1"
        review.content = "The waiter was great."
        review.graph_extracted = False
        return review

    def test_stores_relationship_per_triple_and_marks_extracted(self):
        review = self._make_review()
        db = MagicMock()
        triple = Triple(
            subject="waiter",
            subject_type=EntityType.staff,
            predicate="praised_for",
            object="friendliness",
            object_type=EntityType.other,
        )
        subject_entity = Entity(id=uuid.uuid4())
        object_entity = Entity(id=uuid.uuid4())

        with (
            patch(
                "pipelines.graph_rag.extractor.extract_triples",
                return_value=[triple],
            ),
            patch(
                "pipelines.graph_rag.extractor.resolve_entity",
                side_effect=[subject_entity, object_entity],
            ),
        ):
            count = extract_and_persist(db, review, _SETTINGS)

        assert count == 1
        assert review.graph_extracted is True
        db.add.assert_called_once()
        added_relationship = db.add.call_args[0][0]
        assert added_relationship.source_entity_id == subject_entity.id
        assert added_relationship.target_entity_id == object_entity.id
        assert added_relationship.relation_type == "praised_for"
        assert added_relationship.review_id == review.id

    def test_zero_triples_still_marks_extracted(self):
        review = self._make_review()
        db = MagicMock()

        with patch(
            "pipelines.graph_rag.extractor.extract_triples", return_value=[]
        ):
            count = extract_and_persist(db, review, _SETTINGS)

        assert count == 0
        assert review.graph_extracted is True
        db.add.assert_not_called()
