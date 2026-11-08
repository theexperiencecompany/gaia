"""Unit tests for app/api/v1/dependencies/google_scope_dependencies.py."""

from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.dependencies.google_scope_dependencies import require_integration
from app.constants.error_codes import INTEGRATION_NOT_CONNECTED
from app.models.user_models import AuthenticatedUser
from app.schemas.errors import ErrorEnvelope
from app.utils.errors import IntegrationNotConnectedError

_MODULE = "app.api.v1.dependencies.google_scope_dependencies"


class TestRequireIntegration:
    async def test_a_missing_connection_is_the_one_typed_not_connected_error(self) -> None:
        """The web reads code, toolkit and integration_id off the envelope it renders to."""
        dependency = require_integration("gmail")

        with (
            patch(f"{_MODULE}.check_integration_status", AsyncMock(return_value=False)),
            pytest.raises(IntegrationNotConnectedError) as raised,
        ):
            await dependency(user=AuthenticatedUser(user_id="user_1"))

        envelope = ErrorEnvelope.from_app_error(raised.value)
        assert raised.value.status_code == 403
        assert (envelope.code, envelope.toolkit, envelope.integration_id) == (
            INTEGRATION_NOT_CONNECTED,
            "gmail",
            "gmail",
        )
        assert envelope.message == "Gmail is not connected. Reconnect it to continue."
        assert envelope.why == "The integration has no connected account"

    async def test_a_connected_integration_passes_the_user_through(self) -> None:
        dependency = require_integration("gmail")
        user = AuthenticatedUser(user_id="user_1")

        with patch(
            f"{_MODULE}.check_integration_status", AsyncMock(return_value=True)
        ) as check_status:
            assert await dependency(user=user) is user

        check_status.assert_awaited_once_with("gmail", "user_1")
