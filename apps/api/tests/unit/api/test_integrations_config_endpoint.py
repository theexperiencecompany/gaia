"""Unit tests for the integrations config API endpoints.

Covers GET /config, GET /me, GET /{integration_id}/tools, DELETE /{integration_id},
POST /connect/{integration_id}, and the login-free GET /connect-link. Service seams
are mocked; the endpoint's own branching, argument assembly, error mapping, and
redirect URLs run for real. Assertions pin exact response bodies, status codes,
service arguments, and wide-event log payloads.
"""

from collections.abc import Iterator
import contextlib
from unittest.mock import AsyncMock, MagicMock, call, patch

from bson.errors import InvalidId
from httpx import AsyncClient

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.auth import AUDIT_ACTOR_UNAUTHENTICATED
from app.constants.log_tags import LogTag
from app.models.user_models import UserDocument
from app.schemas.integrations.responses import (
    ConnectIntegrationResponse,
    IntegrationsConfigResponse,
    IntegrationSuccessResponse,
    IntegrationTool,
    IntegrationToolsResponse,
    MyIntegrationItem,
    MyIntegrationsResponse,
)

API = "/api/v1/integrations"
MODULE = "app.api.v1.endpoints.integrations.config"
FAKE_UID = "507f1f77bcf86cd799439011"
FRONTEND_URL = "https://app.example.com/"


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
    available: bool = True,
    server_url: str | None = "https://mcp.example.com",
    has_mcp_config: bool = True,
) -> MagicMock:
    mock = MagicMock()
    mock.managed_by = managed_by
    mock.name = name
    mock.source = source
    mock.requires_auth = requires_auth
    if source == "platform":
        pi = MagicMock()
        pi.available = available
        pi.provider = provider
        mock.platform_integration = pi
    else:
        mock.platform_integration = None
    if managed_by == "mcp" and has_mcp_config:
        mock.mcp_config = MagicMock()
        mock.mcp_config.requires_auth = requires_auth
        mock.mcp_config.server_url = server_url
    else:
        mock.mcp_config = None
    return mock


def _connect_error_url(reason: str) -> str:
    return f"{FRONTEND_URL.rstrip('/')}/integrations?connect_error={reason}"


@contextlib.contextmanager
def _override_current_user(test_app, user: dict) -> Iterator[None]:
    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        if original is None:
            test_app.dependency_overrides.pop(get_current_user, None)
        else:
            test_app.dependency_overrides[get_current_user] = original


# ===========================================================================
# GET /integrations/config
# ===========================================================================


class TestGetIntegrationsConfig:
    async def test_config_success(self, client: AsyncClient) -> None:
        mock_response = IntegrationsConfigResponse(integrations=[_config_item()])  # type: ignore[list-item]
        with (
            patch(
                f"{MODULE}.build_integrations_config",
                return_value=mock_response,
            ),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/config")

        assert resp.status_code == 200
        assert resp.json() == {
            "integrations": [
                {
                    "id": "github",
                    "name": "GitHub",
                    "description": "GitHub integration",
                    "category": "developer",
                    "provider": "github",
                    "available": True,
                    "isSpecial": False,
                    "displayPriority": 0,
                    "includedIntegrations": [],
                    "isFeatured": False,
                    "managedBy": "composio",
                    "authType": "oauth",
                    "requiresAuth": False,
                    "source": "platform",
                    "slug": "github",
                }
            ]
        }
        mock_log.set.assert_has_calls(
            [call(operation="get_integrations_config"), call(outcome="success")]
        )

    async def test_config_requires_auth(self, unauthed_client: AsyncClient) -> None:
        """Config endpoint is public (no auth dependency)."""
        mock_response = IntegrationsConfigResponse(integrations=[])
        with patch(
            f"{MODULE}.build_integrations_config",
            return_value=mock_response,
        ):
            resp = await unauthed_client.get(f"{API}/config")
        assert resp.status_code == 200
        assert resp.json() == {"integrations": []}


# ===========================================================================
# GET /integrations/me
# ===========================================================================


class TestGetMyIntegrations:
    async def test_me_success(self, client: AsyncClient) -> None:
        item = MyIntegrationItem(
            id="github",
            name="GitHub",
            description="GitHub integration",
            category="developer",
            source="platform",
            managed_by="composio",
            status="connected",
            tool_count=2,
        )
        with (
            patch(
                f"{MODULE}.get_my_integrations",
                new_callable=AsyncMock,
                return_value=MyIntegrationsResponse(integrations=[item], total=1),
            ) as mock_get,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/me")

        assert resp.status_code == 200
        assert resp.json() == {
            "integrations": [
                {
                    "id": "github",
                    "name": "GitHub",
                    "description": "GitHub integration",
                    "category": "developer",
                    "source": "platform",
                    "managedBy": "composio",
                    "status": "connected",
                    "requiresAuth": False,
                    "authType": None,
                    "isFeatured": False,
                    "displayPriority": 0,
                    "available": True,
                    "iconUrl": None,
                    "slug": None,
                    "toolCount": 2,
                    "isPublic": None,
                    "createdBy": None,
                    "publishedAt": None,
                    "cloneCount": 0,
                    "creator": None,
                }
            ],
            "total": 1,
        }
        mock_get.assert_awaited_once_with(FAKE_UID)
        mock_log.set.assert_has_calls(
            [
                call(operation="get_my_integrations", user={"id": FAKE_UID}),
                call(result_count=1, outcome="success"),
            ]
        )

    async def test_me_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/me")
        assert resp.status_code == 401


# ===========================================================================
# GET /integrations/{integration_id}/tools
# ===========================================================================


class TestGetIntegrationTools:
    async def test_tools_success(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.get_integration_tools",
                new_callable=AsyncMock,
                return_value=IntegrationToolsResponse(
                    integration_id="notion",
                    tools=[
                        IntegrationTool(
                            name="search",
                            description="Search Notion",
                            destructive=True,
                        )
                    ],
                    count=1,
                ),
            ) as mock_get,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/notion/tools")

        assert resp.status_code == 200
        assert resp.json() == {
            "integrationId": "notion",
            "tools": [{"name": "search", "description": "Search Notion", "destructive": True}],
            "count": 1,
        }
        mock_get.assert_awaited_once_with("notion", FAKE_UID)
        mock_log.set.assert_has_calls(
            [
                call(operation="get_integration_tools", integration={"id": "notion"}),
                call(result_count=1, outcome="success"),
            ]
        )

    async def test_tools_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/notion/tools")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /integrations/{integration_id}
# ===========================================================================


class TestDisconnectIntegration:
    async def test_disconnect_success(self, client: AsyncClient) -> None:
        mock_result = IntegrationSuccessResponse(
            success=True,
            message="Disconnected",
            integration_id="github",  # type: ignore[call-arg]
        )
        with (
            patch(
                f"{MODULE}.disconnect_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_disconnect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.delete(f"{API}/github")

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "success",
            "message": "Disconnected",
            "integrationId": "github",
        }
        mock_disconnect.assert_awaited_once_with(FAKE_UID, "github")
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="disconnect_integration",
                    integration_id="github",
                    user={"id": FAKE_UID},
                    integration={"id": "github"},
                ),
                call(outcome="success"),
            ]
        )

    async def test_disconnect_not_found(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("Integration not found"),
        ):
            resp = await client.delete(f"{API}/nonexistent")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Integration not found"}

    async def test_disconnect_no_active_account(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("No active connected account for github"),
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 400
        assert resp.json() == {"detail": "No active connected account for github"}

    async def test_disconnect_message_with_both_markers_is_400(self, client: AsyncClient) -> None:
        """A not-found marker plus an account marker is an account problem, not 404."""
        with patch(
            f"{MODULE}.disconnect_integration",
            new_callable=AsyncMock,
            side_effect=ValueError("Integration not found in account list"),
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 400
        assert resp.json() == {"detail": "Integration not found in account list"}

    async def test_disconnect_generic_error(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.disconnect_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected"),
            ),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Failed to disconnect integration"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Error disconnecting integration",
            integration_id="github",
            user_id=FAKE_UID,
            error_type="RuntimeError",
            error="unexpected",
        )

    async def test_disconnect_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.delete(f"{API}/github")
        assert resp.status_code == 401


# ===========================================================================
# POST /integrations/connect/{integration_id}
# ===========================================================================


class TestConnectIntegration:
    async def test_connect_missing_user_id(self, test_app, client: AsyncClient) -> None:
        with (
            _override_current_user(test_app, {"email": "no-id@example.com"}),
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=_resolved(managed_by="mcp"),
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="connected",
                    integration_id="test-mcp",
                    name="TestInt",
                    tools_count=3,
                ),
            ),
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}

    async def test_connect_mcp_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="mcp", requires_auth=False)
        mock_result = ConnectIntegrationResponse(
            status="connected",
            integration_id="test-mcp",
            name="TestInt",
            tools_count=3,
        )
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ) as mock_resolve,
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
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
        mock_resolve.assert_awaited_once_with("test-mcp")
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="test-mcp",
            integration_name="TestInt",
            requires_auth=False,
            redirect_path="/integrations",
            server_url="https://mcp.example.com",
            is_platform=True,
            bearer_token=None,
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="test-mcp",
                    user={"id": FAKE_UID},
                    integration={"id": "test-mcp"},
                ),
                call(
                    integration_name="TestInt",
                    integration={
                        "id": "test-mcp",
                        "managed_by": "mcp",
                        "auth_type": "none",
                        "provider": "test-mcp",
                    },
                ),
                call(outcome="success"),
            ]
        )

    async def test_connect_mcp_requires_auth_sets_oauth2(self, client: AsyncClient) -> None:
        """requires_auth=True maps to auth_type=oauth2 in the wide event and is
        forwarded verbatim, and a platform provider is not masked by the id."""
        resolved = _resolved(
            managed_by="mcp",
            requires_auth=True,
            provider="GITHUB",
        )
        mock_result = ConnectIntegrationResponse(
            status="connected",
            integration_id="test-mcp",
            name="TestInt",
        )
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations", "bearer_token": "tok"},
            )

        assert resp.status_code == 200
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="test-mcp",
            integration_name="TestInt",
            requires_auth=True,
            redirect_path="/integrations",
            server_url="https://mcp.example.com",
            is_platform=True,
            bearer_token="tok",
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="test-mcp",
                    user={"id": FAKE_UID},
                    integration={"id": "test-mcp"},
                ),
                call(
                    integration_name="TestInt",
                    integration={
                        "id": "test-mcp",
                        "managed_by": "mcp",
                        "auth_type": "oauth2",
                        "provider": "GITHUB",
                    },
                ),
                call(outcome="success"),
            ]
        )

    async def test_connect_custom_mcp_without_config(self, client: AsyncClient) -> None:
        """A custom MCP integration has no mcp_config and is not platform-sourced."""
        resolved = _resolved(
            managed_by="mcp",
            name="My Server",
            source="custom",
            requires_auth=True,
            has_mcp_config=False,
        )
        mock_result = ConnectIntegrationResponse(
            status="connected",
            integration_id="myserver",
            name="My Server",
        )
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/myserver",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="myserver",
            integration_name="My Server",
            requires_auth=True,
            redirect_path="/integrations",
            server_url=None,
            is_platform=False,
            bearer_token=None,
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="myserver",
                    user={"id": FAKE_UID},
                    integration={"id": "myserver"},
                ),
                call(
                    integration_name="My Server",
                    integration={
                        "id": "myserver",
                        "managed_by": "mcp",
                        "auth_type": None,
                        "provider": "myserver",
                    },
                ),
                call(outcome="success"),
            ]
        )

    async def test_connect_composio_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="composio", name="GitHub", provider="GITHUB")
        mock_result = ConnectIntegrationResponse(
            status="redirect",
            integration_id="github",
            name="GitHub",
            redirect_url="https://oauth.example.com",
        )
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ) as mock_resolve,
            patch(
                f"{MODULE}.connect_composio_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
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
        mock_resolve.assert_awaited_once_with("github")
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="github",
            integration_name="GitHub",
            provider="GITHUB",
            redirect_path="/integrations",
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="github",
                    user={"id": FAKE_UID},
                    integration={"id": "github"},
                ),
                call(
                    integration_name="GitHub",
                    integration={
                        "id": "github",
                        "managed_by": "composio",
                        "auth_type": "oauth2",
                        "provider": "GITHUB",
                    },
                ),
                call(outcome="success"),
            ]
        )

    async def test_connect_self_success(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="self", name="Google Calendar", provider="GCAL")
        mock_result = ConnectIntegrationResponse(
            status="redirect",
            integration_id="gcal",
            name="Google Calendar",
            redirect_url="https://oauth.google.com",
        )
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ) as mock_resolve,
            patch(
                f"{MODULE}.connect_self_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/gcal",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"
        assert resp.json()["redirectUrl"] == "https://oauth.google.com"
        mock_resolve.assert_awaited_once_with("gcal")
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            user_email="test@example.com",
            integration_id="gcal",
            integration_name="Google Calendar",
            provider="GCAL",
            redirect_path="/integrations",
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="gcal",
                    user={"id": FAKE_UID},
                    integration={"id": "gcal"},
                ),
                call(
                    integration_name="Google Calendar",
                    integration={
                        "id": "gcal",
                        "managed_by": "self",
                        "auth_type": "oauth2",
                        "provider": "GCAL",
                    },
                ),
                call(outcome="success"),
            ]
        )

    async def test_connect_self_without_email(self, test_app, client: AsyncClient) -> None:
        """A user dict without an email still connects, passing an empty string."""
        resolved = _resolved(managed_by="self", name="Google Calendar", provider="GCAL")
        mock_result = ConnectIntegrationResponse(
            status="redirect",
            integration_id="gcal",
            name="Google Calendar",
            redirect_url="https://oauth.google.com",
        )
        with (
            _override_current_user(test_app, {"user_id": FAKE_UID}),
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_self_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/gcal",
                json={"redirect_path": "/integrations"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"
        mock_connect.assert_awaited_once_with(
            user_id=FAKE_UID,
            user_email="",
            integration_id="gcal",
            integration_name="Google Calendar",
            provider="GCAL",
            redirect_path="/integrations",
        )

    async def test_connect_not_found(self, client: AsyncClient) -> None:
        with patch(
            f"{MODULE}.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                f"{API}/connect/nonexistent",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Integration nonexistent not found"}

    async def test_connect_unavailable_platform(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="mcp", available=False)
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="connected",
                    integration_id="unavailable",
                    name="TestInt",
                ),
            ),
        ):
            resp = await client.post(
                f"{API}/connect/unavailable",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "error",
            "integrationId": "unavailable",
            "name": "TestInt",
            "message": None,
            "toolsCount": None,
            "redirectUrl": None,
            "error": "Integration unavailable is not available yet",
        }

    async def test_connect_platform_source_without_platform_integration(
        self, client: AsyncClient
    ) -> None:
        """A platform-sourced resolved with no platform_integration is not
        treated as unavailable — it proceeds to connect."""
        resolved = MagicMock()
        resolved.managed_by = "mcp"
        resolved.name = "TestInt"
        resolved.source = "platform"
        resolved.requires_auth = False
        resolved.platform_integration = None
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.requires_auth = False
        resolved.mcp_config.server_url = "https://mcp.example.com"
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="connected",
                    integration_id="edge",
                    name="TestInt",
                ),
            ) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/edge",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"
        mock_connect.assert_awaited_once()

    async def test_connect_composio_no_provider(self, client: AsyncClient) -> None:
        """Missing provider is an error response (the HTTPException(400) raised
        inside the try is caught and mapped to a status='error' body)."""
        resolved = _resolved(managed_by="composio", provider=None)
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_composio_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="redirect",
                    integration_id="noprov",
                    name="TestInt",
                    redirect_url="https://oauth.example.com",
                ),
            ) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "error",
            "integrationId": "noprov",
            "name": "TestInt",
            "message": None,
            "toolsCount": None,
            "redirectUrl": None,
            "error": "400: Provider not configured",
        }
        mock_connect.assert_not_awaited()

    async def test_connect_self_no_provider(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="self", provider=None)
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_self_integration",
                new_callable=AsyncMock,
                return_value=ConnectIntegrationResponse(
                    status="redirect",
                    integration_id="noprov",
                    name="TestInt",
                    redirect_url="https://oauth.example.com",
                ),
            ) as mock_connect,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "error",
            "integrationId": "noprov",
            "name": "TestInt",
            "message": None,
            "toolsCount": None,
            "redirectUrl": None,
            "error": "400: Provider not configured",
        }
        mock_connect.assert_not_awaited()

    async def test_connect_unsupported_type(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="unknown")
        with patch(
            f"{MODULE}.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ):
            resp = await client.post(
                f"{API}/connect/weird",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "error",
            "integrationId": "weird",
            "name": "TestInt",
            "message": None,
            "toolsCount": None,
            "redirectUrl": None,
            "error": "Unsupported integration type: unknown",
        }

    async def test_connect_service_exception(self, client: AsyncClient) -> None:
        """When the connect function itself raises, endpoint returns error
        status (not 500) with the exception message."""
        resolved = _resolved(managed_by="mcp")
        with (
            patch(
                f"{MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{MODULE}.connect_mcp_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("conn failed"),
            ),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "error",
            "integrationId": "test-mcp",
            "name": "TestInt",
            "message": None,
            "toolsCount": None,
            "redirectUrl": None,
            "error": "conn failed",
        }
        mock_log.error.assert_called_once_with(
            f"{LogTag.INTEGRATION} Failed to connect integration",
            integration_id="test-mcp",
            user_id=FAKE_UID,
            error_type="RuntimeError",
            error="conn failed",
        )
        mock_log.set.assert_has_calls(
            [
                call(
                    operation="connect_integration",
                    integration_id="test-mcp",
                    user={"id": FAKE_UID},
                    integration={"id": "test-mcp"},
                ),
                call(
                    integration_name="TestInt",
                    integration={
                        "id": "test-mcp",
                        "managed_by": "mcp",
                        "auth_type": "none",
                        "provider": "test-mcp",
                    },
                ),
                call(integration={"id": "test-mcp", "status": "error"}),
            ]
        )

    async def test_connect_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/connect/github",
            json={"redirect_path": "/integrations"},
        )
        assert resp.status_code == 401


# ===========================================================================
# GET /integrations/connect-link (login-free, self-authenticating)
# ===========================================================================


class TestConnectLinkEndpoint:
    """The login-free connect link: self-authenticating, redirects into OAuth."""

    async def test_valid_token_redirects_to_oauth(self, client: AsyncClient) -> None:
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ) as mock_resolve,
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ) as mock_get_user,
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ) as mock_initiate,
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "https://oauth.example/go"
        mock_resolve.assert_awaited_once_with("somecode")
        mock_get_user.assert_awaited_once_with(FAKE_UID)
        mock_initiate.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="notion",
            user_email="a@b.com",
            redirect_path="/integrations",
        )
        mock_log.set.assert_has_calls(
            [
                call(operation="connect_link"),
                call(user={"id": FAKE_UID}, integration={"id": "notion"}),
                call(outcome="redirect"),
            ]
        )
        mock_log.audit.assert_called_once_with(
            "connect link redeemed",
            actor=FAKE_UID,
            resource="notion",
        )

    async def test_invalid_token_redirects_to_error(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(f"{MODULE}.settings.FRONTEND_URL", FRONTEND_URL),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=bad", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == _connect_error_url("invalid_or_expired_link")
        mock_log.set.assert_has_calls([call(operation="connect_link"), call(outcome="rejected")])
        mock_log.warning.assert_called_once_with(
            f"{LogTag.INTEGRATION} Connect link redemption rejected",
            failure="unknown_or_consumed_code",
        )
        mock_log.audit.assert_called_once_with(
            "connect link redemption rejected",
            actor=AUDIT_ACTOR_UNAUTHENTICATED,
            reason="unknown_or_consumed_code",
        )

    async def test_error_url_strips_only_trailing_slashes(self, client: AsyncClient) -> None:
        """The connect-error URL strips trailing slashes from FRONTEND_URL and
        nothing else — a URL whose last path char is not a slash survives."""
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(f"{MODULE}.settings.FRONTEND_URL", "https://app.example.comX/"),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=bad", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == (
            "https://app.example.comX/integrations?connect_error=invalid_or_expired_link"
        )
        mock_log.set.assert_has_calls([call(operation="connect_link"), call(outcome="rejected")])

    async def test_malformed_user_id_redirects_to_error(self, client: AsyncClient) -> None:
        """A corrupt binding (user_id that is not a valid ObjectId) is bounced
        like any other bad code, with a distinct telemetry failure."""
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=("not-an-object-id", "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                side_effect=InvalidId("not-an-object-id"),
            ) as mock_get_user,
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
            ) as mock_initiate,
            patch(f"{MODULE}.settings.FRONTEND_URL", FRONTEND_URL),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=bad", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == _connect_error_url("invalid_or_expired_link")
        mock_get_user.assert_awaited_once_with("not-an-object-id")
        mock_initiate.assert_not_awaited()
        mock_log.set.assert_has_calls(
            [
                call(operation="connect_link"),
                call(user={"id": "not-an-object-id"}, integration={"id": "notion"}),
                call(outcome="rejected"),
            ]
        )
        mock_log.warning.assert_called_once_with(
            f"{LogTag.INTEGRATION} Connect link redemption rejected",
            failure="malformed_user_id",
            error_type="InvalidId",
        )
        mock_log.audit.assert_has_calls(
            [
                call("connect link redeemed", actor="not-an-object-id", resource="notion"),
                call(
                    "connect link redemption rejected",
                    actor="not-an-object-id",
                    resource="notion",
                    reason="malformed_user_id",
                    error_type="InvalidId",
                ),
            ]
        )

    async def test_no_user_doc_passes_empty_email(self, client: AsyncClient) -> None:
        """A code bound to a user with no user document still flows — with no
        email hint for the provider OAuth."""
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ) as mock_initiate,
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "https://oauth.example/go"
        mock_initiate.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="notion",
            user_email="",
            redirect_path="/integrations",
        )

    async def test_user_doc_without_email_passes_empty_hint(self, client: AsyncClient) -> None:
        """A user doc with no email means no OAuth login hint — empty string."""
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email=None),
            ),
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ) as mock_initiate,
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == "https://oauth.example/go"
        mock_initiate.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="notion",
            user_email="",
            redirect_path="/integrations",
        )

    async def test_no_redirect_url_redirects_to_error_page(self, client: AsyncClient) -> None:
        """A non-redirect result (e.g. connected) with no URL is an error."""
        result = MagicMock(status="connected", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ),
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ),
            patch(f"{MODULE}.settings.FRONTEND_URL", FRONTEND_URL),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == _connect_error_url("could_not_start")
        mock_log.set.assert_has_calls(
            [
                call(operation="connect_link"),
                call(user={"id": FAKE_UID}, integration={"id": "notion"}),
                call(outcome="error"),
            ]
        )

    async def test_initiate_returns_none_redirects_to_error_page(self, client: AsyncClient) -> None:
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ),
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(f"{MODULE}.settings.FRONTEND_URL", FRONTEND_URL),
            patch(f"{MODULE}.log", new=MagicMock()) as mock_log,
        ):
            resp = await client.get(f"{API}/connect-link?code=somecode", follow_redirects=False)

        assert resp.status_code == 307
        assert resp.headers["location"] == _connect_error_url("could_not_start")
        mock_log.set.assert_has_calls(
            [
                call(operation="connect_link"),
                call(user={"id": FAKE_UID}, integration={"id": "notion"}),
                call(outcome="error"),
            ]
        )

    async def test_works_without_login(self, unauthed_client: AsyncClient) -> None:
        """The whole point: a logged-out user reaches it (not 401) and is sent
        into OAuth — identity comes from the single-use code, not a session."""
        result = MagicMock(status="redirect", redirect_url="https://oauth.example/go", error=None)
        with (
            patch(
                f"{MODULE}.resolve_and_consume_connect_code",
                new_callable=AsyncMock,
                return_value=(FAKE_UID, "notion"),
            ),
            patch(
                f"{MODULE}.user_repository.get",
                new_callable=AsyncMock,
                return_value=UserDocument(email="a@b.com"),
            ),
            patch(
                f"{MODULE}.initiate_integration_connection",
                new_callable=AsyncMock,
                return_value=result,
            ) as mock_initiate,
        ):
            resp = await unauthed_client.get(
                f"{API}/connect-link?code=somecode", follow_redirects=False
            )
        assert resp.status_code == 307
        assert resp.headers["location"] == "https://oauth.example/go"
        mock_initiate.assert_awaited_once_with(
            user_id=FAKE_UID,
            integration_id="notion",
            user_email="a@b.com",
            redirect_path="/integrations",
        )
