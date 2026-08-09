"""Tests for app.constants.keys."""

from __future__ import annotations

from app.constants.keys import REQUEST_ID_KEY


class TestRequestIdKey:
    def test_value_is_the_composio_request_correlation_key(self) -> None:
        assert REQUEST_ID_KEY == "__composio_request_id__"
