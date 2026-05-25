"""Unit tests for app/integrations/ — GoogleHandler and registry."""

from __future__ import annotations

import pytest

from app.integrations.google import GoogleHandler
from app.integrations.registry import SUPPORTED_PLATFORMS, get_handler


class TestGoogleHandlerDeriveBusinessId:
    def test_prefers_place_id_over_data_id(self, handlingGoogleReview):
        bid = handlingGoogleReview.derive_business_id(
            {"place_id": "ChIJ123", "data_id": "0xabc"}
        )
        assert bid == "ChIJ123"

    def test_falls_back_to_data_id_when_no_place_id(self, handlingGoogleReview):
        bid = handlingGoogleReview.derive_business_id({"data_id": "0xabc"})
        assert bid == "0xabc"

    def test_raises_when_both_missing(self, handlingGoogleReview):
        with pytest.raises(ValueError, match="place_id or data_id"):
            handlingGoogleReview.derive_business_id({})

    def test_raises_when_both_none(self, handlingGoogleReview):
        with pytest.raises(ValueError):
            handlingGoogleReview.derive_business_id({"place_id": None, "data_id": None})

    def test_raises_when_both_empty_string(self, handlingGoogleReview):
        with pytest.raises(ValueError):
            handlingGoogleReview.derive_business_id({"place_id": "", "data_id": ""})


class TestRegistry:
    def test_get_handler_google_returns_google_handler(self):
        assert isinstance(get_handler("google"), GoogleHandler)

    def test_get_handler_unsupported_raises_key_error(self):
        with pytest.raises(KeyError, match="tiktok"):
            get_handler("tiktok")

    def test_supported_platforms_contains_google(self):
        assert "google" in SUPPORTED_PLATFORMS

    def test_supported_platforms_is_frozenset(self):
        assert isinstance(SUPPORTED_PLATFORMS, frozenset)
