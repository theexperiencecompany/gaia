"""Unit tests for the MCP integration endpoints (app/api/v1/endpoints/mcp.py).

Covers the OAuth callback success path and its analytics capture.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.services.analytics_service import AnalyticsEvents

MCP_BASE = "/api/v1/mcp"
_MODULE = "app.api.v1.endpoints.mcp"


class TestMCPOAuthCallback:
    """GET /api/v1/mcp/oauth/callback"""

    async def test_oauth_callback_captures_connected_event(self, client: AsyncClient) -> None:
        mcp_client = MagicMock()
        mcp_client.handle_oauth_callback = AsyncMock()
        mcp_client.token_store = MagicMock()
        mcp_client.token_store.clear_excluded_scopes = AsyncMock()
        resolved = MagicMock()
        resolved.name = "GitHub"

        with (
            patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                new_callable=AsyncMock,
                return_value=resolved,
            ),
            patch(f"{_MODULE}.invalidate_user_integration_caches", new_callable=AsyncMock),
            patch(f"{_MODULE}.get_api_base_url", return_value="http://api"),
            patch(f"{_MODULE}.get_frontend_url", return_value="http://frontend"),
            patch(f"{_MODULE}.capture_context_event") as mock_capture,
        ):
            resp = await client.get(
                f"{MCP_BASE}/oauth/callback",
                params={"state": "tok:github:/integrations", "code": "code1"},
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "status=connected" in resp.headers["location"]
        mock_capture.assert_called_once_with(
            AnalyticsEvents.INTEGRATION_CONNECTED,
            {"integration_id": "github", "connection_method": "oauth"},
        )
