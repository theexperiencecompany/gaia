"""Unit tests for app/api/v1/dependencies/google_scope_dependencies.py."""

from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest

from app.api.v1.dependencies.google_scope_dependencies import require_integration
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED

_MODULE = "app.api.v1.dependencies.google_scope_dependencies"


class TestRequireIntegration:
    async def test_a_missing_connection_is_a_403_with_the_envelope_fields(self) -> None:
        """The web narrows on `code` and `toolkit` to offer the connect card."""
        dependency = require_integration("gmail")

        with (
            patch(f"{_MODULE}.check_integration_status", AsyncMock(return_value=False)),
            pytest.raises(HTTPException) as raised,
        ):
            await dependency(user={"user_id": "user_1"})

        assert raised.value.status_code == 403
        assert raised.value.detail == {
            "type": "integration",
            "code": INTEGRATION_NOT_CONNECTED,
            "toolkit": "gmail",
            "message": "Missing connection: Gmail. Please connect integrations in settings.",
        }

    async def test_a_connected_integration_passes_the_user_through(self) -> None:
        dependency = require_integration("gmail")
        user = {"user_id": "user_1"}

        with patch(f"{_MODULE}.check_integration_status", AsyncMock(return_value=True)):
            assert await dependency(user=user) is user
