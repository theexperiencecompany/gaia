"""Unit tests for the integrations config API endpoints.

Tests cover GET /config, GET /status, DELETE /{integration_id},
and POST /connect/{integration_id}.  Service layer is mocked;
only HTTP status codes, response shapes, and error handling are verified.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

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
    available: bool = True,
    server_url: str | None = "https://mcp.example.com",
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
    if managed_by == "mcp":
        mock.mcp_config = MagicMock()
        mock.mcp_config.requires_auth = requires_auth
        mock.mcp_config.server_url = server_url
    else:
        mock.mcp_config = None
    return mock


# ===========================================================================
# GET /integrations/config
# ===========================================================================


@pytest.mark.unit
class TestGetIntegrationsConfig:
    async def test_config_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import IntegrationsConfigResponse

        mock_response = IntegrationsConfigResponse(integrations=[_config_item()])  # type: ignore[list-item]
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
# GET /integrations/status
# ===========================================================================


@pytest.mark.unit
class TestGetIntegrationsStatus:
    async def test_status_success(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.config.get_all_integrations_status",
            new_callable=AsyncMock,
            return_value={"github": True, "slack": False},
        ):
            resp = await client.get(f"{API}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["integrations"]) == 2

    async def test_status_service_error_returns_all_disconnected(
        self, client: AsyncClient
    ) -> None:
        """When get_all_integrations_status fails, endpoint returns all
        integrations as disconnected (not 500)."""
        with patch(
            "app.api.v1.endpoints.integrations.config.get_all_integrations_status",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB down"),
        ):
            resp = await client.get(f"{API}/status")
        assert resp.status_code == 200
        data = resp.json()
        # All returned items should have connected=False
        for item in data["integrations"]:
            assert item["connected"] is False

    async def test_status_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.get(f"{API}/status")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /integrations/{integration_id}
# ===========================================================================


@pytest.mark.unit
class TestDisconnectIntegration:
    async def test_disconnect_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import IntegrationSuccessResponse

        mock_result = IntegrationSuccessResponse(
            success=True,
            message="Disconnected",
            integration_id="github",  # type: ignore[call-arg]
        )
        with patch(
            "app.api.v1.endpoints.integrations.config.disconnect_integration",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = await client.delete(f"{API}/github")
        assert resp.status_code == 200

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


@pytest.mark.unit
class TestConnectIntegration:
    async def test_connect_mcp_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import ConnectIntegrationResponse

        resolved = _resolved(managed_by="mcp")
        mock_result = ConnectIntegrationResponse(
            status="connected",
            integration_id="test-mcp",
            name="TestInt",
            tools_count=3,
        )
        with (
            patch(
                "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.api.v1.endpoints.integrations.config.connect_mcp_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "connected"

    async def test_connect_composio_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import ConnectIntegrationResponse

        resolved = _resolved(managed_by="composio", provider="GITHUB")
        mock_result = ConnectIntegrationResponse(
            status="redirect",
            integration_id="github",
            name="GitHub",
            redirect_url="https://oauth.example.com",
        )
        with (
            patch(
                "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.api.v1.endpoints.integrations.config.connect_composio_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            resp = await client.post(
                f"{API}/connect/github",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "redirect"

    async def test_connect_self_success(self, client: AsyncClient) -> None:
        from app.schemas.integrations.responses import ConnectIntegrationResponse

        resolved = _resolved(managed_by="self", provider="GCAL")
        mock_result = ConnectIntegrationResponse(
            status="redirect",
            integration_id="gcal",
            name="Google Calendar",
            redirect_url="https://oauth.google.com",
        )
        with (
            patch(
                "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.api.v1.endpoints.integrations.config.connect_self_integration",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            resp = await client.post(
                f"{API}/connect/gcal",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200

    async def test_connect_not_found(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await client.post(
                f"{API}/connect/nonexistent",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 404

    async def test_connect_unavailable_platform(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="mcp", available=False)
        with patch(
            "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ):
            resp = await client.post(
                f"{API}/connect/unavailable",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "not available" in resp.json()["error"]

    async def test_connect_composio_no_provider(self, client: AsyncClient) -> None:
        """HTTPException(400) raised inside try is caught by outer except
        Exception handler, so response is 200 with status='error'."""
        resolved = _resolved(managed_by="composio", provider=None)
        with patch(
            "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    async def test_connect_self_no_provider(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="self", provider=None)
        with patch(
            "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ):
            resp = await client.post(
                f"{API}/connect/noprov",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    async def test_connect_unsupported_type(self, client: AsyncClient) -> None:
        resolved = _resolved(managed_by="unknown")
        with patch(
            "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
            new_callable=AsyncMock,
            return_value=resolved,
        ):
            resp = await client.post(
                f"{API}/connect/weird",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "Unsupported" in resp.json()["error"]

    async def test_connect_service_exception(self, client: AsyncClient) -> None:
        """When the connect function itself raises, endpoint returns error
        status (not 500)."""
        resolved = _resolved(managed_by="mcp")
        with (
            patch(
                "app.api.v1.endpoints.integrations.config.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                "app.api.v1.endpoints.integrations.config.connect_mcp_integration",
                new_callable=AsyncMock,
                side_effect=RuntimeError("conn failed"),
            ),
        ):
            resp = await client.post(
                f"{API}/connect/test-mcp",
                json={"redirect_path": "/integrations"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "conn failed" in data["error"]

    async def test_connect_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/connect/github",
            json={"redirect_path": "/integrations"},
        )
        assert resp.status_code == 401
