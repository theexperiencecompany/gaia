"""Unit tests for the integrations config API endpoints.

Tests cover GET /config, DELETE /{integration_id},
and POST /connect/{integration_id}.  Service layer is mocked;
only HTTP status codes, response shapes, and error handling are verified.
"""

from contextlib import ExitStack
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

from httpx import AsyncClient
import pytest

from app.constants.integrations import NOT_SET_UP_ON_INSTANCE
from app.constants.log_tags import LogTag
from app.constants.mcp import MCP_OAUTH_CALLBACK_PATH
from app.models.user_models import UserDocument
from app.schemas.integrations.responses import ConnectIntegrationResponse
from app.services.composio.error_detail import AuthConfigNotFoundError
from app.services.connect_link_service import (
    ConnectLinkBinding,
    build_connect_link_url,
    resolve_and_consume_connect_code,
)
from app.services.mcp.mcp_token_store import oauth_browser_cookie, oauth_state_bound_to_browser
from shared.py.analytics import UserId
from shared.py.analytics.catalog.integrations import (
    IntegrationConnected,
    IntegrationConnectInitiated,
    IntegrationDisconnected,
)
from tests.conftest import FAKE_USER

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
    integration_id: str,
    managed_by: str = "mcp",
    name: str = "TestInt",
    source: str = "platform",
    requires_auth: bool = False,
    provider: str | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.integration_id = integration_id
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
            patch("app.api.v1.endpoints.integrations.config.capture") as mock_capture,
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 200
        mock_capture.assert_called_once_with(
            UserId(_VALID_UID), IntegrationDisconnected(integration_id="github")
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
_SERVICE = "app.services.integrations.integration_connection_service"
_COMPOSIO_404 = "Error code: 404 - {'error': {'message': 'Auth config not found', 'code': 302}}"
_VALID_UID = "507f1f77bcf86cd799439011"


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
        "accountLabel": None,
    }


class TestConnectIntegration:
    async def test_connect_mcp_success(self, client: AsyncClient) -> None:
        resolved = _resolved("test-mcp", managed_by="mcp")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_SERVICE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=_connected("test-mcp"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture") as mock_capture,
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
            "accountLabel": None,
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
            UserId(_VALID_UID),
            IntegrationConnected(integration_id="test-mcp", managed_by="mcp"),
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
        resolved = _resolved("my-mcp", managed_by="mcp", source="custom", requires_auth=True)
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_SERVICE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=_redirect("my-mcp", "TestInt"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture") as mock_capture,
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
        mock_capture.assert_called_once_with(
            UserId(_VALID_UID),
            IntegrationConnectInitiated(integration_id="my-mcp", managed_by="mcp"),
        )
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
        resolved = _resolved("github", managed_by="composio", name="GitHub", provider="GITHUB")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_SERVICE}.connect_composio_integration",
                new_callable=AsyncMock,
                return_value=_redirect("github", "GitHub"),
            ) as mock_connect,
            patch(f"{_MODULE}.capture") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/github",
                json={"redirect_path": "/integrations", "account_id": "ca_expired"},
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
            "accountLabel": None,
        }
        mock_connect.assert_awaited_once_with(
            user_id=_VALID_UID,
            integration_id="github",
            integration_name="GitHub",
            provider="GITHUB",
            redirect_path="/integrations",
            reconnect_account_id="ca_expired",
        )
        mock_capture.assert_called_once_with(
            UserId(_VALID_UID),
            IntegrationConnectInitiated(integration_id="github", managed_by="composio"),
        )
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
        resolved = _resolved("unavailable", managed_by="mcp")
        resolved.platform_integration.available = False
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_SERVICE}.connect_mcp_integration", new_callable=AsyncMock) as mock_connect,
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
        """A provider-less platform row answers a 200 error naming the missing provider."""
        resolved = _resolved("noprov", managed_by="composio", name="GitHub", provider=None)
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_SERVICE}.connect_composio_integration", new_callable=AsyncMock
            ) as mock_connect,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body("noprov", "GitHub", "Provider not configured")
        mock_connect.assert_not_awaited()
        mock_log.set.assert_any_call(outcome="error")
        assert call(outcome="success") not in mock_log.set.call_args_list

    async def test_connect_unsupported_type(self, client: AsyncClient) -> None:
        resolved = _resolved("weird", managed_by="unknown", source="custom")
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
        resolved = _resolved("test-mcp", managed_by="mcp")
        with (
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_SERVICE}.connect_mcp_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("conn failed"),
            ),
            patch(f"{_MODULE}.capture") as mock_capture,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body(
            "test-mcp", "TestInt", "Couldn't connect TestInt. Please try again."
        )
        mock_capture.assert_not_called()
        mock_log.set.assert_any_call(outcome="error")
        assert call(outcome="success") not in mock_log.set.call_args_list

    @pytest.mark.regression
    async def test_connect_composio_failure_answers_plain_copy(self, client: AsyncClient) -> None:
        """Regression for PR #1662: the route returned Composio's 404 dump as the toast text."""
        composio = MagicMock()
        composio.connect_account = AsyncMock(side_effect=RuntimeError(_COMPOSIO_404))
        with (
            patch(f"{_SERVICE}.auth_config_id_for", new_callable=AsyncMock, return_value="ac_1"),
            patch(f"{_SERVICE}.get_account_record", new_callable=AsyncMock, return_value=None),
            patch(f"{_SERVICE}.create_oauth_state", new_callable=AsyncMock, return_value="st"),
            patch(f"{_SERVICE}.update_user_integration_status", new_callable=AsyncMock),
            patch(f"{_SERVICE}.get_composio_service", return_value=composio),
            patch(f"{_SERVICE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/notion",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body(
            "notion", "Notion", "Couldn't connect Notion. Please try again."
        )
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["error"] == _COMPOSIO_404
        mock_log.set.assert_any_call(integration={"id": "notion", "status": "error"})

    async def test_connect_composio_missing_auth_config_says_not_set_up(
        self, client: AsyncClient
    ) -> None:
        composio = MagicMock()
        composio.connect_account = AsyncMock(side_effect=AuthConfigNotFoundError("Gmail", "ac_1"))
        with (
            patch(f"{_SERVICE}.auth_config_id_for", new_callable=AsyncMock, return_value="ac_1"),
            patch(f"{_SERVICE}.get_account_record", new_callable=AsyncMock, return_value=None),
            patch(f"{_SERVICE}.create_oauth_state", new_callable=AsyncMock, return_value="st"),
            patch(f"{_SERVICE}.update_user_integration_status", new_callable=AsyncMock),
            patch(f"{_SERVICE}.get_composio_service", return_value=composio),
            patch(f"{_SERVICE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/gmail",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == _error_body("gmail", "Gmail", f"Gmail {NOT_SET_UP_ON_INSTANCE}")
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Integration has no auth config in this Composio project",
            integration_id="gmail",
            auth_config_id="ac_1",
            user_id=FAKE_USER.user_id,
        )
        mock_log.set.assert_any_call(integration={"id": "gmail", "status": "not_set_up"})

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
                return_value=ConnectLinkBinding(
                    user_id=_VALID_UID, integration_id="notion", account_id=None
                ),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{_MODULE}.capture") as mock_capture,
        ):
            resp = await client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "https://oauth.example/go"
        mock_capture.assert_called_once_with(
            UserId(_VALID_UID),
            IntegrationConnectInitiated(integration_id="notion", source="connect_link"),
        )

    @pytest.mark.usefixtures("fake_redis")
    async def test_an_mcp_flow_is_bound_to_the_browser_that_opened_the_link(
        self, client: AsyncClient
    ) -> None:
        """Only this browser may finish it: a provider link sent elsewhere is refused at the callback."""
        state = "statetoken123"
        result = MagicMock(
            status="redirect",
            redirect_url=f"https://auth.resend.example/authorize?state={state}%3Aresend%3A%2Fintegrations",
            error=None,
        )
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=ConnectLinkBinding(
                    user_id=_VALID_UID, integration_id="resend", account_id=None
                ),
            ),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=_resolved("resend", managed_by="mcp"),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{_MODULE}.capture"),
        ):
            resp = await client.post(
                f"{API}/connect-link",
                data={"code": "somecode"},
                headers={"x-forwarded-proto": "https"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        cookie = resp.cookies.get(oauth_browser_cookie("resend"))
        assert cookie
        assert await oauth_state_bound_to_browser(state, cookie)
        set_cookie = resp.headers["set-cookie"].lower()
        assert "httponly" in set_cookie
        assert "samesite=lax" in set_cookie
        assert "secure" in set_cookie
        assert "max-age=600" in set_cookie
        assert f"path={MCP_OAUTH_CALLBACK_PATH}" in set_cookie

    async def test_a_reconnect_link_signs_its_account_back_in(self, client: AsyncClient) -> None:
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=ConnectLinkBinding(
                    user_id=_VALID_UID, integration_id="gmail", account_id="ca_work"
                ),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ) as initiate,
            patch(f"{_MODULE}.capture"),
        ):
            resp = await client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert resp.status_code == 303
        initiate.assert_awaited_once_with(
            _VALID_UID,
            ANY,
            redirect_path="/integrations",
            reconnect_account_id="ca_work",
        )
        assert initiate.call_args.args[1].integration_id == "gmail"

    async def test_a_code_bound_to_a_malformed_user_id_bounces_without_a_lookup(
        self, client: AsyncClient
    ) -> None:
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=ConnectLinkBinding(
                    user_id="not-an-object-id", integration_id="notion", account_id=None
                ),
            ),
            patch(f"{_MODULE}.user_repository.get", new_callable=AsyncMock) as get_user,
            patch(f"{_MODULE}.initiate_integration_connection", new_callable=AsyncMock) as initiate,
        ):
            resp = await client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert "connect_error=invalid_or_expired_link" in resp.headers["location"]
        get_user.assert_not_awaited()
        initiate.assert_not_awaited()

    async def test_a_link_to_an_unknown_integration_cannot_start(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=ConnectLinkBinding(
                    user_id=_VALID_UID, integration_id="gone", account_id=None
                ),
            ),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve", new_callable=AsyncMock, return_value=None
            ),
            patch(f"{_MODULE}.initiate_integration_connection", new_callable=AsyncMock) as initiate,
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert resp.status_code == 303
        assert "connect_error=could_not_start" in resp.headers["location"]
        initiate.assert_not_awaited()
        mock_log.set.assert_any_call(outcome="error")

    @pytest.mark.parametrize(
        ("status", "redirect_url"),
        [("redirect", None), ("error", "https://oauth.example/go")],
        ids=["no-url", "not-redirect"],
    )
    async def test_only_a_redirect_with_a_url_is_followed(
        self, client: AsyncClient, status: str, redirect_url: str | None
    ) -> None:
        binding = ConnectLinkBinding(user_id=_VALID_UID, integration_id="notion", account_id=None)
        answer = MagicMock(status=status, redirect_url=redirect_url, error="no")
        seams = {
            f"{_MODULE}.resolve_and_consume_connect_code": AsyncMock(return_value=binding),
            f"{_MODULE}.initiate_integration_connection": AsyncMock(return_value=answer),
        }
        with ExitStack() as stack:
            for target, replacement in seams.items():
                stack.enter_context(patch(target, replacement))
            capture = stack.enter_context(patch(f"{_MODULE}.capture"))
            resp = await client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert resp.status_code == 303
        assert "connect_error=could_not_start" in resp.headers["location"]
        capture.assert_not_called()

    async def test_invalid_token_redirects_to_error(self, client: AsyncClient) -> None:
        with patch(
            f"{_MODULE}.resolve_and_consume_connect_code",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                f"{API}/connect-link", data={"code": "bad"}, follow_redirects=False
            )
        assert resp.status_code == 303
        assert "connect_error=invalid_or_expired_link" in resp.headers["location"]

    @pytest.mark.regression
    async def test_get_does_not_spend_the_code(self, unauthed_client: AsyncClient) -> None:
        """Regression: Telegram's link-preview GET spent the single-use code before the user tapped it."""
        with patch(
            f"{_MODULE}.resolve_and_consume_connect_code",
            new_callable=AsyncMock,
            return_value=ConnectLinkBinding(
                user_id=_VALID_UID, integration_id="notion", account_id=None
            ),
        ) as mock_consume:
            resp = await unauthed_client.get(
                f"{API}/connect-link?code=somecode", follow_redirects=False
            )
        assert resp.status_code == 405
        mock_consume.assert_not_awaited()

    async def test_works_without_login(self, unauthed_client: AsyncClient) -> None:
        """A logged-out user reaches it (not 401) and is sent into OAuth — identity comes from the single-use code, not a session."""
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{_MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=ConnectLinkBinding(
                    user_id=_VALID_UID, integration_id="notion", account_id=None
                ),
            ),
            patch(
                f"{_MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
        ):
            resp = await unauthed_client.post(
                f"{API}/connect-link", data={"code": "somecode"}, follow_redirects=False
            )
        assert resp.status_code != 401
        assert resp.headers["location"] == "https://oauth.example/go"


class TestConnectLinkPreview:
    @pytest.mark.usefixtures("fake_redis")
    async def test_a_live_link_names_the_integration_and_masked_account_without_spending_it(
        self, unauthed_client: AsyncClient
    ) -> None:
        url = await build_connect_link_url(_VALID_UID, "gmail")
        assert url is not None
        code = url.rsplit("/", 1)[1]
        with (
            patch(
                "app.services.connect_link_service.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="aryan@heygaia.io", name="Aryan"),
            ),
            patch(f"{_MODULE}.log") as mock_log,
        ):
            resp = await unauthed_client.post(f"{API}/connect-link/preview", json={"code": code})

        assert resp.status_code == 200
        body = resp.json()
        assert body["integration_id"] == "gmail"
        assert body["integration_name"] == "Gmail"
        assert body["account_email"] == "ar***@heygaia.io"
        assert await resolve_and_consume_connect_code(code) is not None
        mock_log.set.assert_called_with(outcome="success", integration={"id": "gmail"})

    @pytest.mark.usefixtures("fake_redis")
    async def test_a_dead_link_is_not_found(self, unauthed_client: AsyncClient) -> None:
        with patch(f"{_MODULE}.log") as mock_log:
            resp = await unauthed_client.post(f"{API}/connect-link/preview", json={"code": "nope"})

        assert resp.status_code == 404
        assert resp.json()["message"] == "invalid_or_expired_link"
        mock_log.set.assert_called_with(outcome="rejected")
