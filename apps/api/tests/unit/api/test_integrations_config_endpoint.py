"""Unit tests for the integrations config API endpoints.

Tests cover GET /config, DELETE /{integration_id},
and POST /connect/{integration_id}.  Service layer is mocked;
only HTTP status codes, response shapes, and error handling are verified.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.models.user_models import UserDocument
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.analytics_service import AnalyticsEvents

API = "/api/v1/integrations"


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


def _resolved(
    managed_by: str = "mcp",
    name: str = "TestInt",
    source: str = "platform",
    requires_auth: bool = False,
    provider: str | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.managed_by = managed_by
    mock.name = name
    mock.source = source
    mock.requires_auth = requires_auth
    if source == "platform":
        pi = MagicMock()
        pi.available = True
        pi.provider = provider
        mock.platform_integration = pi
    else:
        mock.platform_integration = None
    if managed_by == "mcp":
        mock.mcp_config = MagicMock()
        mock.mcp_config.requires_auth = requires_auth
        mock.mcp_config.server_url = "https://mcp.example.com"
    else:
        mock.mcp_config = None
    return mock


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
        """Config endpoint is public (no Depends(get_current_user)); the test verifies it doesn't 500."""
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


_MODULE = "app.api.v1.endpoints.integrations.config"
_VALID_UID = "507f1f77bcf86cd799439011"
_USER_EMAIL = "test@example.com"


def _connected(integration_id: str, name: str = "TestInt") -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(
        status="connected", integration_id=integration_id, name=name, tools_count=3
    )


def _redirect(integration_id: str, name: str) -> ConnectIntegrationResponse:
    return ConnectIntegrationResponse(
        status="redirect",
        integration_id=integration_id,
        name=name,
        redirect_url="https://oauth.example.com",
    )


def _error_body(integration_id: str, name: str, error: str) -> dict:
    return {
        "status": "error",
        "integrationId": integration_id,
        "name": name,
        "message": None,
        "toolsCount": None,
        "redirectUrl": None,
        "error": error,
    }


@contextmanager
def _current_user(test_app: FastAPI, user: dict) -> Iterator[None]:
    """Serve user from get_current_user for the duration of the block."""
    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        if original is None:
            test_app.dependency_overrides.pop(get_current_user, None)
        else:
            test_app.dependency_overrides[get_current_user] = original


class TestConnectIntegration:
    async def test_connect_mcp_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="mcp")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=_connected("test-mcp"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture_context_event") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "connected",
            "integrationId": "test-mcp",
            "name": "TestInt",
            "message": None,
            "toolsCount": 3,
            "redirectUrl": None,
            "error": None,
        }
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            integration_id="test-mcp",
            integration_name="TestInt",
            requires_auth=False,
            redirect_path="/integrations",
            server_url="https://mcp.example.com",
            is_platform=True,
            bearer_token=None,
        )
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "test-mcp", "managed_by": "mcp"},
        )
        mock_log.set.assert_any_call(
            integration_name="TestInt",
            integration={
                "id": "test-mcp",
                "managed_by": "mcp",
                "auth_type": "none",
                "provider": "test-mcp",
            },
        )
        mock_log.set.assert_any_call(outcome="success")

    async def test_connect_custom_mcp_with_bearer_token(self, client: AsyncClient) -> None:
        """A user-added OAuth MCP server is not a platform one; bearer token and redirect path pass through."""
        resolved = _resolved(managed_by="mcp", source="custom", requires_auth=True)
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=_redirect("my-mcp", "TestInt"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture_context_event") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/my-mcp",
                json={"redirect_path": "/settings", "bearer_token": "tok-1"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            integration_id="my-mcp",
            integration_name="TestInt",
            requires_auth=True,
            redirect_path="/settings",
            server_url="https://mcp.example.com",
            is_platform=False,
            bearer_token="tok-1",
        )
        # OAuth-managed connects complete at their callback, not here.
        mock_capture.assert_not_called()
        mock_log.set.assert_any_call(
            integration_name="TestInt",
            integration={
                "id": "my-mcp",
                "managed_by": "mcp",
                "auth_type": "oauth2",
                "provider": "my-mcp",
            },
        )

    async def test_connect_composio_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="composio", name="GitHub", provider="GITHUB")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_composio_integration",
                new_callable=AsyncMock,
                return_value=_redirect("github", "GitHub"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture_context_event") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/github",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "redirect",
            "integrationId": "github",
            "name": "GitHub",
            "message": None,
            "toolsCount": None,
            "redirectUrl": "https://oauth.example.com",
            "error": None,
        }
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            integration_id="github",
            integration_name="GitHub",
            provider="GITHUB",
            redirect_path="/integrations",
        )
        # OAuth-managed connects complete at their callback, not here.
        mock_capture.assert_not_called()
        mock_log.set.assert_any_call(
            integration_name="GitHub",
            integration={
                "id": "github",
                "managed_by": "composio",
                "auth_type": "oauth2",
                "provider": "GITHUB",
            },
        )
        mock_log.set.assert_any_call(outcome="success")

    async def test_connect_self_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="self", name="Google Calendar", provider="GCAL")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_self_integration",
                new_callable=AsyncMock,
                return_value=_redirect("gcal", "Google Calendar"),
            ) as mock_connect,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/gcal",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            user_email=_USER_EMAIL,
            integration_id="gcal",
            integration_name="Google Calendar",
            provider="GCAL",
            redirect_path="/integrations",
        )
        mock_log.set.assert_any_call(
            integration_name="Google Calendar",
            integration={
                "id": "gcal",
                "managed_by": "self",
                "auth_type": "oauth2",
                "provider": "GCAL",
            },
        )
        mock_log.set.assert_any_call(outcome="success")

    async def test_connect_self_without_an_email_sends_an_empty_one(
        self, test_app: FastAPI, client: AsyncClient
    ) -> None:
        resolved = _resolved(managed_by="self", name="Google Calendar", provider="GCAL")
        with (
            _current_user(test_app, {"user_id": _VALID_UID}),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_self_integration",
                new_callable=AsyncMock,
                return_value=_redirect("gcal", "Google Calendar"),
            ) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/gcal",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            user_email="",
            integration_id="gcal",
            integration_name="Google Calendar",
            provider="GCAL",
            redirect_path="/integrations",
        )

    async def test_connect_not_found(self, client: AsyncClient) -> None:
        with patch(
            f"{_MODULE}.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                f"{API}/connect/nonexistent",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"message": "Integration nonexistent not found"}

    async def test_connect_unavailable_platform(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="mcp")
        resolved.platform_integration.available = False
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_MODULE}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/unavailable",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body(
            "unavailable", "TestInt", "Integration unavailable is not available yet"
        )
        mock_connect.assert_not_awaited()

    async def test_connect_composio_no_provider(self, client: AsyncClient) -> None:
        """Catch a provider-less platform row's 400 in connect's error boundary; respond 200 error."""
        resolved = _resolved(managed_by="composio", name="GitHub", provider=None)
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_composio_integration", new_callable=AsyncMock
            ) as mock_connect,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body("noprov", "GitHub", "400: Provider not configured")
        mock_connect.assert_not_awaited()
        mock_log.set.assert_any_call(integration={"id": "noprov", "status": "error"})
        assert call(outcome="success") not in mock_log.set.call_args_list

    async def test_connect_self_no_provider(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="self", name="Google Calendar", provider=None)
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_MODULE}.connect_self_integration", new_callable=AsyncMock) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body(
            "noprov", "Google Calendar", "400: Provider not configured"
        )
        mock_connect.assert_not_awaited()

    async def test_connect_unsupported_type(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="unknown", source="custom")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/weird",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body(
            "weird", "TestInt", "Unsupported integration type: unknown"
        )
        mock_log.set.assert_any_call(
            integration_name="TestInt",
            integration={
                "id": "weird",
                "managed_by": "unknown",
                "auth_type": None,
                "provider": "weird",
            },
        )

    async def test_connect_service_exception(self, client: AsyncClient) -> None:
        """When the connect function itself raises, the endpoint returns error status, not 500."""
        resolved = _resolved(managed_by="mcp")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("conn failed"),
            ),
            patch(f"{_MODULE}.capture_context_event") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body("test-mcp", "TestInt", "conn failed")
        mock_capture.assert_not_called()
        mock_log.set.assert_any_call(integration={"id": "test-mcp", "status": "error"})
        assert call(outcome="success") not in mock_log.set.call_args_list

    async def test_connect_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/connect/github",
            json={"redirect_path": "/integrations"},
        )
        assert resp.status_code == 401


class TestConnectLinkEndpoint:
    """The login-free connect link: self-authenticating, redirects into OAuth."""

    async def test_valid_token_redirects_to_oauth(self, client: AsyncClient) -> None:
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(_VALID_UID, "notion"),
            ),
            patch(
                f"{_MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == "https://oauth.example/go"

    async def test_invalid_token_redirects_to_error(self, client: AsyncClient) -> None:
        with patch(
            f"{_MODULE}.resolve_and_consume_connect_code",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.get(f"{API}/connect-link?code=bad", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "connect_error=invalid_or_expired_link" in resp.headers["location"]

    async def test_works_without_login(self, unauthed_client: AsyncClient) -> None:
        """A logged-out user reaches it (not 401) and is sent into OAuth — identity comes from the single-use code, not a session."""
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(_VALID_UID, "notion"),
            ),
            patch(
                f"{_MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
        ):
            resp = await unauthed_client.get(
                f"{API}/connect-link?code=somecode", follow_redirects=False
            )
        assert resp.status_code != 401
        assert resp.headers["location"] == "https://oauth.example/go"
