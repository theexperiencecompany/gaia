"""Behaviour tests for the MCP connection-test route's OAuth branch."""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
import pytest

pytestmark = pytest.mark.unit

_MODULE = "app.api.v1.endpoints.mcp"
REDIRECT_URI = "http://api/api/v1/mcp/oauth/callback"


def _oauth_probe_client() -> MagicMock:
    mcp_client = MagicMock(name="user_mcp_client")
    mcp_client.probe_connection = AsyncMock(
        return_value={"requires_auth": True, "auth_type": "oauth"}
    )
    mcp_client.update_integration_auth_status = AsyncMock()
    return mcp_client


class TestMCPConnectionTestOAuth:
    async def test_oauth_url_is_built_from_the_clients_token_store(
        self, client: AsyncClient
    ) -> None:
        mcp_client = _oauth_probe_client()
        resolved = MagicMock()
        resolved.mcp_config.server_url = "https://mcp.example.com/sse"
        with (
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.build_oauth_auth_url",
                new_callable=AsyncMock,
                return_value="https://auth.example.com/authorize",
            ) as build,
            patch(f"{_MODULE}.get_mcp_oauth_redirect_uri", return_value=REDIRECT_URI),
            patch(f"{_MODULE}.capture"),
        ):
            resp = await client.post("/api/v1/mcp/test/github")

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "requires_oauth",
            "oauth_url": "https://auth.example.com/authorize",
        }
        mcp_client.update_integration_auth_status.assert_awaited_once_with(
            "github", requires_auth=True, auth_type="oauth"
        )
        build.assert_awaited_once_with(
            mcp_client.token_store,
            integration_id="github",
            redirect_uri=REDIRECT_URI,
            redirect_path="/integrations",
        )

    async def test_oauth_url_build_failure_reports_failed(self, client: AsyncClient) -> None:
        mcp_client = _oauth_probe_client()
        resolved = MagicMock()
        resolved.mcp_config.server_url = "https://mcp.example.com/sse"
        with (
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(
                f"{_MODULE}.build_oauth_auth_url",
                new_callable=AsyncMock,
                side_effect=ValueError("no discovery"),
            ),
            patch(f"{_MODULE}.capture"),
        ):
            resp = await client.post("/api/v1/mcp/test/github")

        assert resp.json() == {"status": "failed", "error": "no discovery"}
