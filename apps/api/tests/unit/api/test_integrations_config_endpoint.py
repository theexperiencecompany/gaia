"""Unit tests for the integrations config API endpoints.

Tests cover GET /config, DELETE /{integration_id},
and POST /connect/{integration_id}.  Service layer is mocked;
only HTTP status codes, response shapes, and error handling are verified.
"""

from typing import ClassVar
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
import pytest

from app.api.v1.endpoints.integrations import config as config_endpoint
from app.schemas.integrations.requests import ConnectIntegrationRequest
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.analytics_service import AnalyticsEvents
from tests.helpers import captured_wide_event

API = "/api/v1/integrations"
_MODULE = "app.api.v1.endpoints.integrations.config"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_item(
    iid: str = "github",
    name: str = "GitHub",
    managed_by: str = "composio",
) -> dict:
    return {
        "id": iid,
        "name": name,
        "description": "GitHub integration",
        "category": "developer",
        "provider": iid,
        "available": True,
        "is_special": False,
        "display_priority": 0,
        "included_integrations": [],
        "is_featured": False,
        "managed_by": managed_by,
        "auth_type": "oauth",
        "source": "platform",
        "slug": iid,
    }


# ===========================================================================
# GET /integrations/config
# ===========================================================================


class TestGetIntegrationsConfig:
    async def test_config_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import IntegrationsConfigResponse

        mock_response = IntegrationsConfigResponse(integrations=[_config_item()])  # type: ignore[list-item]  # fixture returns a raw dict where IntegrationConfigItem is expected
        with patch(
            "app.api.v1.endpoints.integrations.config.build_integrations_config",
            return_value=mock_response,
        ):
            resp = await client.get(f"{API}/config")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["integrations"]) == 1

    async def test_config_requires_auth(self, unauthed_client: AsyncClient) -> None:
        """Config endpoint is public (no Depends(get_current_user)), but the
        test still verifies it doesn't 500."""
        from app.schemas.integrations.responses import IntegrationsConfigResponse

        mock_response = IntegrationsConfigResponse(integrations=[])
        with patch(
            "app.api.v1.endpoints.integrations.config.build_integrations_config",
            return_value=mock_response,
        ):
            resp = await unauthed_client.get(f"{API}/config")
        # Config endpoint has no auth dependency — should succeed
        assert resp.status_code == 200


# ===========================================================================
# DELETE /integrations/{integration_id}
# ===========================================================================


class TestDisconnectIntegration:
    async def test_disconnect_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import IntegrationSuccessResponse

        mock_result = IntegrationSuccessResponse(  # type: ignore[call-arg]  # pydantic ignores the extra success kwarg at runtime
            success=True,
            message="Disconnected",
            integration_id="github",
        )
        with (
            patch(
                "app.api.v1.endpoints.integrations.config.disconnect_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
            patch("app.api.v1.endpoints.integrations.config.capture_context_event") as mock_capture,
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_DISCONNECTED, {"integration_id": "github"}
        )

    async def test_disconnect_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.config.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("Integration not found"),
        ):
            resp = await client.delete(f"{API}/nonexistent")
        assert resp.status_code == 404

    async def test_disconnect_no_active_account(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.config.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("No active connected account for github"),
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 400

    async def test_disconnect_generic_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.config.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=RuntimeError("unexpected"),
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 500

    async def test_disconnect_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/github")
        assert resp.status_code == 401


# ===========================================================================
# POST /integrations/connect/{integration_id}
# ===========================================================================


class TestConnectIntegration:
    """The endpoint is a thin pass-through now.

    Choosing a transport moved to ``connect_dispatch`` so the authenticated
    endpoint and the login-free connect-link path cannot drift apart; the
    per-transport behaviour is covered in
    ``tests/unit/services/integrations/test_connect_dispatch.py``. What is left
    to verify here is the HTTP contract.
    """

    async def test_passes_the_request_through_and_returns_the_result(
        self, client: AsyncClient
    ) -> None:
        from app.schemas.integrations.responses import ConnectIntegrationResponse

        result = ConnectIntegrationResponse(
            status="connected", integration_id="test-mcp", name="TestInt", tools_count=3
        )
        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=result,
        ) as dispatch:
            resp = await client.post(
                f"{API}/connect/test-mcp", json={"redirect_path": "/integrations"}
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "connected"
        assert body["toolsCount"] == 3
        kwargs = dispatch.await_args.kwargs
        assert kwargs["integration_id"] == "test-mcp"
        assert kwargs["redirect_path"] == "/integrations"

    async def test_forwards_a_pasted_secret(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import ConnectIntegrationResponse

        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=ConnectIntegrationResponse(
                status="connected", integration_id="gh", name="GitHub"
            ),
        ) as dispatch:
            await client.post(f"{API}/connect/gh", json={"bearer_token": "secret-value"})

        assert dispatch.await_args.kwargs["bearer_token"] == "secret-value"

    async def test_surfaces_a_pending_cli_connect(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import (
            CliConnectDetail,
            ConnectIntegrationResponse,
        )

        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=ConnectIntegrationResponse(
                status="pending",
                integration_id="stripe_link",
                name="Stripe Link",
                cli=CliConnectDetail(
                    phase="awaiting_approval", instructions="open https://link.test/d"
                ),
            ),
        ):
            resp = await client.post(f"{API}/connect/stripe_link", json={})

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "pending"
        assert body["cli"]["phase"] == "awaiting_approval"
        assert body["cli"]["instructions"] == "open https://link.test/d"

    async def test_unknown_integration_is_a_404(self, client: AsyncClient) -> None:
        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(f"{API}/connect/nope", json={})
        assert resp.status_code == 404

    async def test_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(f"{API}/connect/github", json={})
        assert resp.status_code == 401


class TestConnectIntegrationHandler:
    """The connect handler called directly, without the router in the way.

    The HTTP tests above prove the wire contract. These prove the two things
    the handler itself decides — which identity it acts for, and what it puts
    on the wide event — which the router's own error handling would otherwise
    flatten into an anonymous 400.
    """

    USER: ClassVar[dict[str, str]] = {
        "user_id": "507f1f77bcf86cd799439011",
        "email": "test@example.com",
    }

    async def _call(self, user: dict, **overrides: object) -> ConnectIntegrationResponse:
        request = ConnectIntegrationRequest(**overrides)  # type: ignore[arg-type]  # kwargs dict widens to object; the model validates the real types
        return await config_endpoint.connect_integration_endpoint(
            integration_id="stripe_link", request=request, user=user
        )

    async def test_acts_for_the_authenticated_user_and_their_email(self):
        # The dispatch keys the connection on this user id, and forwards the
        # email as the OAuth login hint. Reading either from the wrong claim
        # would connect an integration to the wrong account.
        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=ConnectIntegrationResponse(
                status="connected", integration_id="stripe_link", name="Stripe Link"
            ),
        ) as dispatch:
            await self._call(self.USER, redirect_path="/chat/7", bearer_token="paste-me")

        assert dispatch.await_args.kwargs == {
            "user_id": "507f1f77bcf86cd799439011",
            "integration_id": "stripe_link",
            "user_email": "test@example.com",
            "redirect_path": "/chat/7",
            "bearer_token": "paste-me",
        }

    async def test_a_token_carrying_no_user_id_is_refused_by_name(self):
        # A validated token with no subject claim is a broken session, not an
        # anonymous one; the message has to say so rather than fail as a
        # generic 400 the caller cannot diagnose.
        with pytest.raises(HTTPException) as exc_info:
            await self._call({"email": "test@example.com"})

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "User ID not found"

    async def test_an_unknown_user_id_claim_is_not_silently_accepted(self):
        # Reading the wrong claim name must fail closed. If it ever resolved to
        # something truthy, every connect would run as whatever that value is.
        with pytest.raises(HTTPException) as exc_info:
            await self._call({"userId": "507f1f77bcf86cd799439011"})

        assert exc_info.value.status_code == 400

    async def test_a_caller_with_no_email_still_connects(self):
        # Bot and connect-link users have no email claim. The login hint is
        # optional; requiring it would lock them out of every connect.
        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=ConnectIntegrationResponse(
                status="pending", integration_id="stripe_link", name="Stripe Link"
            ),
        ) as dispatch:
            await self._call({"user_id": "507f1f77bcf86cd799439011"})

        assert dispatch.await_args.kwargs["user_email"] == ""

    async def test_the_wide_event_names_the_operation_the_user_and_the_integration(self):
        # This is the only record tying a failed connect to who asked for it and
        # for what; the key names are the schema the log queries join on.
        with patch(
            f"{_MODULE}.initiate_integration_connection",
            new_callable=AsyncMock,
            return_value=ConnectIntegrationResponse(
                status="pending", integration_id="stripe_link", name="Stripe Link"
            ),
        ):
            async with captured_wide_event() as event:
                await self._call(self.USER)
                operation = event["operation"]

        assert operation == "connect_integration"
        assert event["integration_id"] == "stripe_link"
        assert event["user"] == {"id": "507f1f77bcf86cd799439011"}
        assert event["integration"] == {"id": "stripe_link"}

    async def test_an_unresolvable_integration_is_a_404_naming_it(self):
        with (
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=None,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await self._call(self.USER)

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Integration stripe_link not found"
