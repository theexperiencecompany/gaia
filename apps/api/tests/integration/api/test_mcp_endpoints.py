"""Integration tests for MCP API endpoints.

Tests the routes mounted at /api/v1/mcp/:

  POST /api/v1/mcp/test/{integration_id}   – probe / connect an MCP server
  GET  /api/v1/mcp/oauth/callback           – handle OAuth code exchange

External I/O (MCPClient, IntegrationResolver, Redis, tool registry) is fully
mocked.  The real FastAPI app is used via ASGITransport so routing, request
validation, and auth enforcement are exercised for real.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared payload builders
# ---------------------------------------------------------------------------


def _make_resolved_integration(
    server_url: str = "http://mcp-server.test",  # NOSONAR
    requires_auth: bool = False,
    auth_type: str = "oauth",
):
    """Build a mock ResolvedIntegration object."""
    mock_resolved = MagicMock()
    mock_resolved.name = "Test Integration"
    mock_resolved.mcp_config = MagicMock()
    mock_resolved.mcp_config.server_url = server_url
    mock_resolved.mcp_config.requires_auth = requires_auth
    mock_resolved.mcp_config.auth_type = auth_type
    return mock_resolved


def _make_mcp_client(
    probe_result: dict | None = None,
    connect_tools: list | None = None,
    oauth_url: str = "https://oauth.provider.test/authorize",
    handle_oauth_tools: list | None = None,
):
    """Build a mock MCPClient instance."""
    client = MagicMock()
    client.probe_connection = AsyncMock(
        return_value=probe_result or {"requires_auth": False, "error": None}
    )
    client.connect = AsyncMock(return_value=connect_tools or [MagicMock(name="tool_a")])
    client.build_oauth_auth_url = AsyncMock(return_value=oauth_url)
    client.update_integration_auth_status = AsyncMock()
    client.handle_oauth_callback = AsyncMock(
        return_value=handle_oauth_tools or [MagicMock(name="tool_x")]
    )
    return client


# ---------------------------------------------------------------------------
# Test: POST /api/v1/mcp/test/{integration_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPTestConnectionEndpoint:
    """Tests for POST /api/v1/mcp/test/{integration_id}."""

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_connected(
        self,
        mock_invalidate,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} should return status=connected when probe succeeds."""
        mock_resolve.return_value = _make_resolved_integration(requires_auth=False)
        mock_client = _make_mcp_client(
            probe_result={"requires_auth": False, "error": None},
            connect_tools=[MagicMock(), MagicMock()],
        )
        mock_get_client.return_value = mock_client

        response = await test_client.post("/api/v1/mcp/test/my-integration")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["tools_count"] == 2

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_404_for_unknown_integration(
        self,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} should return 404 when integration not found."""
        mock_resolve.return_value = None  # integration does not exist
        mock_get_client.return_value = _make_mcp_client()

        response = await test_client.post("/api/v1/mcp/test/nonexistent-integration")

        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_404_when_no_mcp_config(
        self,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} returns 404 when resolved integration has no mcp_config."""
        resolved = MagicMock()
        resolved.mcp_config = None  # no MCP config on this integration
        mock_resolve.return_value = resolved
        mock_get_client.return_value = _make_mcp_client()

        response = await test_client.post("/api/v1/mcp/test/integration-without-mcp")

        assert response.status_code == 404

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_failed_on_probe_error(
        self,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} should return status=failed when probe has error."""
        mock_resolve.return_value = _make_resolved_integration()
        mock_client = _make_mcp_client(
            probe_result={"requires_auth": False, "error": "Connection refused"}
        )
        mock_get_client.return_value = mock_client

        response = await test_client.post("/api/v1/mcp/test/broken-integration")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_requires_oauth(
        self,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} returns status=requires_oauth when probe needs auth."""
        mock_resolve.return_value = _make_resolved_integration(requires_auth=True)
        mock_client = _make_mcp_client(
            probe_result={
                "requires_auth": True,
                "auth_type": "oauth",
                "error": None,
            },
            oauth_url="https://auth.provider.test/oauth/authorize?client_id=abc",
        )
        mock_get_client.return_value = mock_client

        response = await test_client.post("/api/v1/mcp/test/oauth-integration")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "requires_oauth"
        assert "oauth_url" in data
        assert data["oauth_url"].startswith("https://")

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_returns_failed_when_connect_raises(
        self,
        mock_invalidate,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """POST /api/v1/mcp/test/{id} returns status=failed when connect() raises."""
        mock_resolve.return_value = _make_resolved_integration(requires_auth=False)
        mock_client = _make_mcp_client(
            probe_result={"requires_auth": False, "error": None}
        )
        mock_client.connect = AsyncMock(side_effect=RuntimeError("Transport error"))
        mock_get_client.return_value = mock_client

        response = await test_client.post("/api/v1/mcp/test/unstable-integration")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data

    async def test_test_mcp_connection_requires_auth(self, unauthenticated_client):
        """POST /api/v1/mcp/test/{id} without auth must return 401."""
        response = await unauthenticated_client.post(
            "/api/v1/mcp/test/some-integration"
        )
        assert response.status_code == 401

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    async def test_connect_mcp_endpoint_calls_invalidate_cache_on_success(
        self,
        mock_resolve,
        mock_get_client,
        test_client,
        test_user,
    ):
        """On successful connect the endpoint must invalidate the MCP status cache."""
        mock_resolve.return_value = _make_resolved_integration(requires_auth=False)
        mock_client = _make_mcp_client(
            probe_result={"requires_auth": False, "error": None},
            connect_tools=[MagicMock()],
        )
        mock_get_client.return_value = mock_client

        with patch(
            "app.api.v1.endpoints.mcp.invalidate_mcp_status_cache",
            new_callable=AsyncMock,
        ) as mock_invalidate:
            await test_client.post("/api/v1/mcp/test/cache-check-integration")
            mock_invalidate.assert_awaited_once_with(str(test_user["user_id"]))


# ---------------------------------------------------------------------------
# Test: GET /api/v1/mcp/oauth/callback
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPOAuthCallbackEndpoint:
    """Tests for GET /api/v1/mcp/oauth/callback."""

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.get_tool_registry",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.delete_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_success_redirects(
        self,
        mock_frontend_url,
        mock_delete_cache,
        mock_get_registry,
        mock_invalidate,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """GET /api/v1/mcp/oauth/callback?code=X&state=Y should redirect on success."""
        mock_resolve.return_value = _make_resolved_integration()
        mock_resolve.return_value.name = "My MCP Integration"

        mock_client = _make_mcp_client(
            handle_oauth_tools=[MagicMock(name="tool1"), MagicMock(name="tool2")]
        )
        mock_get_client.return_value = mock_client

        # Mock the tool registry
        mock_registry = MagicMock()
        mock_registry.load_user_mcp_tools = AsyncMock()
        mock_get_registry.return_value = mock_registry

        # state format: "token:integration_id:redirect_path"
        state = "csrf-token-abc:test-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"code": "auth-code-xyz", "state": state},
            follow_redirects=False,
        )

        # Endpoint returns a RedirectResponse (3xx)
        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "status=connected" in location
        assert "test-integration" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_error_from_provider_redirects_with_error(
        self,
        mock_frontend_url,
        test_client,
    ):
        """GET /api/v1/mcp/oauth/callback with error param should redirect with error code."""
        state = "token-abc:my-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={
                "state": state,
                "error": "access_denied",
                "error_description": "User denied access",
            },
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "status=failed" in location
        assert "access_denied" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_invalid_state_format_redirects_with_error(
        self,
        mock_frontend_url,
        test_client,
    ):
        """GET /api/v1/mcp/oauth/callback with a malformed state redirects to error page."""
        # State with too few segments (missing integration_id)
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"state": "only-one-part", "code": "some-code"},
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "invalid_state" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_missing_code_redirects_with_error(
        self,
        mock_frontend_url,
        test_client,
    ):
        """GET /api/v1/mcp/oauth/callback without code param should redirect with missing_code."""
        state = "token-xyz:my-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"state": state},
            # no 'code' query param
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "missing_code" in location

    async def test_mcp_oauth_callback_requires_auth(self, unauthenticated_client):
        """GET /api/v1/mcp/oauth/callback without auth must return 401."""
        response = await unauthenticated_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"state": "token:integration:/integrations", "code": "abc"},
        )
        assert response.status_code == 401

    async def test_mcp_oauth_callback_missing_state_returns_422(self, test_client):
        """GET /api/v1/mcp/oauth/callback without required 'state' param returns 422."""
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"code": "auth-code-only"},  # 'state' is required by Query(...)
        )
        assert response.status_code == 422

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_handle_failure_redirects_with_error(
        self,
        mock_frontend_url,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """GET /api/v1/mcp/oauth/callback redirects to error page when handle_oauth_callback raises."""
        mock_resolve.return_value = _make_resolved_integration()
        mock_resolve.return_value.name = "Failing Integration"

        mock_client = _make_mcp_client()
        mock_client.handle_oauth_callback = AsyncMock(
            side_effect=ValueError("Invalid state token")
        )
        mock_get_client.return_value = mock_client

        state = "bad-token:failing-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"code": "some-code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        # The endpoint maps "state" errors to "invalid_state" error code
        assert "status=failed" in location
        assert "invalid_state" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_mcp_client",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.IntegrationResolver.resolve",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.invalidate_mcp_status_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.get_tool_registry",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.delete_cache",
        new_callable=AsyncMock,
    )
    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_uses_default_redirect_path(
        self,
        mock_frontend_url,
        mock_delete_cache,
        mock_get_registry,
        mock_invalidate,
        mock_resolve,
        mock_get_client,
        test_client,
    ):
        """Redirect path defaults to /integrations when not included in state."""
        mock_resolve.return_value = _make_resolved_integration()
        mock_resolve.return_value.name = "Some Integration"

        mock_client = _make_mcp_client(handle_oauth_tools=[MagicMock()])
        mock_get_client.return_value = mock_client

        mock_registry = MagicMock()
        mock_registry.load_user_mcp_tools = AsyncMock()
        mock_get_registry.return_value = mock_registry

        # State without redirect_path (only two parts)
        state = "token-xyz:some-integration"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        # Default redirect path is /integrations
        assert "/integrations" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_server_error_mapped_to_oauth_server_error(
        self,
        mock_frontend_url,
        test_client,
    ):
        """OAuth 'server_error' from provider is remapped to 'oauth_server_error' code."""
        state = "token:some-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={
                "state": state,
                "error": "server_error",
                "error_description": "Internal server error at provider",
            },
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "oauth_server_error" in location

    @patch(
        "app.api.v1.endpoints.mcp.get_frontend_url",
        return_value="http://frontend.test",  # NOSONAR
    )
    async def test_mcp_oauth_callback_unknown_error_uses_generic_code(
        self,
        mock_frontend_url,
        test_client,
    ):
        """Unknown OAuth error codes from provider fall back to 'authorization_failed'."""
        state = "token:some-integration:/integrations"
        response = await test_client.get(
            "/api/v1/mcp/oauth/callback",
            params={
                "state": state,
                "error": "some_bizarre_provider_specific_error",
            },
            follow_redirects=False,
        )

        assert response.status_code in (302, 307)
        location = response.headers.get("location", "")
        assert "authorization_failed" in location
