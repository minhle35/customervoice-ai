"""
Tests for pipelines/ingestion/google_reviews_ingestion.py

Run from the backend/ directory:
    uv run pytest tests/test_google_reviews_ingestion.py -v
"""

from __future__ import annotations
from pipelines.ingestion.google_reviews_ingestion import (
    _parse_datetime,
    _stable_id,
    fetch_google_reviews,
)

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make project root importable so `pipelines.*` resolves
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# _stable_id
# ---------------------------------------------------------------------------


class TestStableId:
    def test_deterministic(self):
        assert _stable_id("alice", "2024-01-01", "great food") == _stable_id(
            "alice", "2024-01-01", "great food"
        )

    def test_different_inputs_give_different_ids(self):
        assert _stable_id("alice", "text") != _stable_id("bob", "text")

    def test_returns_32_char_hex(self):
        result = _stable_id("a", "b", "c")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_handles_none_parts(self):
        # Should not raise — None parts are coerced to ""
        result = _stable_id(None, "text", None)
        assert isinstance(result, str) and len(result) == 32


# ---------------------------------------------------------------------------
# _parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    def test_none_returns_none(self):
        assert _parse_datetime(None) is None

    def test_unix_timestamp_int(self):
        dt = _parse_datetime(0)
        assert dt == datetime(1970, 1, 1, tzinfo=timezone.utc)

    def test_unix_timestamp_float(self):
        dt = _parse_datetime(1_700_000_000.0)
        assert isinstance(dt, datetime)
        assert dt.tzinfo == timezone.utc

    def test_iso_string(self):
        dt = _parse_datetime("2024-06-15T12:00:00")
        assert dt == datetime(2024, 6, 15, 12, 0, 0)

    def test_invalid_string_returns_none(self):
        assert _parse_datetime("not-a-date") is None

    def test_unsupported_type_returns_none(self):
        assert _parse_datetime(["2024-01-01"]) is None


# ---------------------------------------------------------------------------
# fetch_google_reviews — happy path & edge cases
# ---------------------------------------------------------------------------

SERPAPI_RESPONSE = {
    "reviews": [
        {
            "review_id": "abc123",
            "user": "Alice",
            "snippet": "Amazing food and great service!",
            "rating": 5,
            "timestamp": 1_700_000_000,
        },
        {
            "review_id": "def456",
            "author": "Bob",
            "content": "Decent place, a bit pricey.",
            "rating": 3,
            "published_at": "2024-01-10T09:00:00",
        },
    ]
}


def _make_mock_response(payload: dict, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _mock_client(payload: dict):
    """Return a context-manager mock that yields a client returning payload."""
    mock_client = MagicMock()
    mock_client.get.return_value = _make_mock_response(payload)
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_client)
    cm.__exit__ = MagicMock(return_value=False)
    return cm, mock_client


class TestFetchGoogleReviews:
    def test_raises_when_no_api_key(self):
        with patch(
            "pipelines.ingestion.google_reviews_ingestion.get_settings"
        ) as mock_settings:
            mock_settings.return_value.google_reviews_api_key = None
            with pytest.raises(ValueError, match="GOOGLE_REVIEWS_API_KEY"):
                fetch_google_reviews("biz-1", {})

    def test_returns_list_of_review_create(self):
        cm, _ = _mock_client(SERPAPI_RESPONSE)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "The Grand Hotel"})

        assert len(reviews) == 2

    def test_maps_fields_correctly(self):
        cm, _ = _mock_client(SERPAPI_RESPONSE)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "The Grand Hotel"})

        r = reviews[0]
        assert r.platform_id == "abc123"
        assert r.author == "Alice"
        assert r.content == "Amazing food and great service!"
        assert r.rating == 5.0
        assert r.business_id == "biz-1"
        assert r.business_name == "The Grand Hotel"
        assert r.platform.value == "google"

    def test_fallback_author_fields(self):
        """Supports 'author' and 'user_name' in addition to 'user'."""
        payload = {
            "reviews": [
                {
                    "review_id": "r1",
                    "author": "Charlie",
                    "snippet": "Good",
                    "rating": 4,
                },
                {"review_id": "r2", "user_name": "Dana", "text": "Lovely", "rating": 5},
            ]
        }
        cm, _ = _mock_client(payload)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "Test Business"})

        assert reviews[0].author == "Charlie"
        assert reviews[1].author == "Dana"

    def test_fallback_content_fields(self):
        """Supports 'content' and 'text' in addition to 'snippet'."""
        payload = {
            "reviews": [
                {"review_id": "r1", "user": "Eve", "content": "Nice", "rating": 4},
                {"review_id": "r2", "user": "Frank", "text": "Loved it", "rating": 5},
            ]
        }
        cm, _ = _mock_client(payload)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "Test Business"})

        assert reviews[0].content == "Nice"
        assert reviews[1].content == "Loved it"

    def test_skips_empty_content(self):
        payload = {
            "reviews": [
                {"review_id": "r1", "user": "Ghost", "snippet": "   ", "rating": 3},
                {
                    "review_id": "r2",
                    "user": "Alice",
                    "snippet": "Real review",
                    "rating": 5,
                },
            ]
        }
        cm, _ = _mock_client(payload)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "Test Business"})

        assert len(reviews) == 1
        assert reviews[0].author == "Alice"

    def test_generates_stable_id_when_review_id_missing(self):
        payload = {
            "reviews": [
                {"user": "Anonymous", "snippet": "Good place", "rating": 4},
            ]
        }
        cm, _ = _mock_client(payload)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "Test Business"})

        assert len(reviews) == 1
        assert len(reviews[0].platform_id) == 32  # sha256 hex[:32]

    def test_none_rating_is_allowed(self):
        payload = {
            "reviews": [
                {
                    "review_id": "r1",
                    "user": "Alice",
                    "snippet": "Great!",
                    "rating": None,
                },
            ]
        }
        cm, _ = _mock_client(payload)
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {"place_name": "Test Business"})

        assert reviews[0].rating is None

    def test_empty_reviews_list(self):
        cm, _ = _mock_client({"reviews": []})
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "test-key"
            reviews = fetch_google_reviews("biz-1", {})

        assert reviews == []

    def test_serpapi_called_with_correct_params(self):
        cm, mock_client = _mock_client({"reviews": []})
        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "my-secret-key"
            fetch_google_reviews("biz-1", {"data_id": "place-xyz"})

        call_kwargs = mock_client.get.call_args
        params_sent = call_kwargs.kwargs.get("params") or call_kwargs.args[1]
        assert params_sent["engine"] == "google_maps_reviews"
        assert params_sent["api_key"] == "my-secret-key"
        assert params_sent["data_id"] == "place-xyz"

    def test_http_error_propagates(self):
        import httpx

        cm = MagicMock()
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_client.get.return_value = mock_resp
        cm.__enter__ = MagicMock(return_value=mock_client)
        cm.__exit__ = MagicMock(return_value=False)

        with (
            patch(
                "pipelines.ingestion.google_reviews_ingestion.get_settings"
            ) as mock_settings,
            patch(
                "pipelines.ingestion.google_reviews_ingestion.httpx.Client",
                return_value=cm,
            ),
        ):
            mock_settings.return_value.google_reviews_api_key = "bad-key"
            with pytest.raises(RuntimeError):
                fetch_google_reviews("biz-1", {})
