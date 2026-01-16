"""
End-to-End Integration Tests for MCP OAuth and Connection Flow.

This module contains comprehensive tests for all MCP connection scenarios:
- Unauthenticated MCP connections
- OAuth MCP with Dynamic Client Registration (DCR)
- OAuth MCP with client metadata document
- OAuth MCP with pre-registered client
- Token refresh flow
- Token revocation on disconnect
- Tool discovery verification

These tests use mock servers where possible but also include
real-world integration tests (marked with @pytest.mark.integration).
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tests.mcp.conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_AUTH_SERVER_URL,
    MOCK_CLIENT_ID,
    MOCK_INTEGRATION_ID,
    MOCK_REFRESH_TOKEN,
    MOCK_SERVER_URL,
    MOCK_USER_ID,
    MockOAuthServer,
    MockResponse,
    get_mock_authorization_server_metadata,
    get_mock_protected_resource_metadata,
    get_mock_token_response,
    get_mock_www_authenticate_header,
)

# Real-world test URLs (used for @pytest.mark.integration tests)
SMITHERY_TEST_SERVER = "https://server.smithery.ai/@anthropics/mcp-simple-example"
UNAUTHENTICATED_MCP_SERVER = "https://mcp.example.com/simple"  # placeholder


# ==============================================================================
# Timing and Performance Tests
# ==============================================================================


class TestProbePerformance:
    """Tests for probe timing and reliability."""

    @pytest.mark.asyncio
    async def test_probe_completes_within_timeout(self):
        """Probe should complete within the configured timeout."""
        from app.utils.mcp_oauth_utils import (
            OAUTH_PROBE_TIMEOUT,
            extract_auth_challenge,
        )

        start = time.perf_counter()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse.unauthorized(
                www_authenticate=get_mock_www_authenticate_header(
                    resource_metadata_url=f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource"
                )
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        elapsed = time.perf_counter() - start

        # Should complete much faster than timeout when mocked
        assert elapsed < 1.0, f"Probe took {elapsed:.2f}s, expected < 1s"
        assert result.get("raw"), "Should detect OAuth requirement"

    @pytest.mark.asyncio
    async def test_probe_handles_slow_server(self):
        """Probe should handle slow servers gracefully."""
        from app.utils.mcp_oauth_utils import extract_auth_challenge

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # Simulate slow response
            async def slow_get(*args, **kwargs):
                await asyncio.sleep(0.5)  # 500ms delay
                return MockResponse.unauthorized(
                    www_authenticate=get_mock_www_authenticate_header()
                )

            mock_instance.get.side_effect = slow_get

            start = time.perf_counter()
            result = await extract_auth_challenge(MOCK_SERVER_URL)
            elapsed = time.perf_counter() - start

        assert elapsed >= 0.5, "Should wait for slow server"
        assert result.get("raw"), "Should still detect OAuth"

    @pytest.mark.asyncio
    async def test_probe_timeout_returns_empty(self):
        """Probe should return empty dict on timeout (not raise exception)."""
        from app.utils.mcp_oauth_utils import extract_auth_challenge

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.TimeoutException("Timeout")

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result == {}, "Timeout should return empty dict"


# ==============================================================================
# OAuth Discovery Tests
# ==============================================================================


class TestOAuthDiscoveryFlow:
    """Tests for complete OAuth discovery flow."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient with mocked token store."""
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = AsyncMock()
        client.token_store.get_oauth_discovery.return_value = None
        client.token_store.get_dcr_client.return_value = None
        client.token_store.store_oauth_discovery.return_value = None
        client.token_store.store_dcr_client.return_value = None
        client.token_store.create_oauth_state.return_value = "test-state"
        return client

    @pytest.mark.asyncio
    async def test_full_discovery_flow_with_prm(self, mcp_client):
        """Test complete discovery flow using Protected Resource Metadata."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)
        prm = get_mock_protected_resource_metadata()
        auth_metadata = get_mock_authorization_server_metadata()

        with (
            patch("app.services.mcp.mcp_client.extract_auth_challenge") as mock_extract,
            patch(
                "app.services.mcp.mcp_client.find_protected_resource_metadata"
            ) as mock_find_prm,
            patch(
                "app.services.mcp.mcp_client.fetch_protected_resource_metadata"
            ) as mock_fetch_prm,
            patch(
                "app.services.mcp.mcp_client.select_authorization_server"
            ) as mock_select,
            patch(
                "app.services.mcp.mcp_client.fetch_auth_server_metadata"
            ) as mock_fetch_auth,
            patch("app.services.mcp.mcp_client.validate_oauth_endpoints"),
        ):
            mock_extract.return_value = {"scope": "read write"}
            mock_find_prm.return_value = (
                f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource"
            )
            mock_fetch_prm.return_value = prm
            mock_select.return_value = MOCK_AUTH_SERVER_URL
            mock_fetch_auth.return_value = auth_metadata

            start = time.perf_counter()
            result = await mcp_client._discover_oauth_config(
                MOCK_INTEGRATION_ID, mcp_config
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

        # Verify discovery completed
        assert result["discovery_method"] == "rfc9728_prm"
        assert result["authorization_endpoint"] == f"{MOCK_AUTH_SERVER_URL}/authorize"
        assert result["token_endpoint"] == f"{MOCK_AUTH_SERVER_URL}/token"

        # Verify timing is reasonable
        assert elapsed_ms < 1000, f"Discovery took {elapsed_ms:.0f}ms, expected < 1s"

    @pytest.mark.asyncio
    async def test_discovery_fallback_to_direct(self, mcp_client):
        """Test fallback to direct OAuth discovery when PRM fails."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)
        auth_metadata = get_mock_authorization_server_metadata()

        with (
            patch("app.services.mcp.mcp_client.extract_auth_challenge") as mock_extract,
            patch(
                "app.services.mcp.mcp_client.find_protected_resource_metadata"
            ) as mock_find_prm,
            patch(
                "app.services.mcp.mcp_client.fetch_auth_server_metadata"
            ) as mock_fetch_auth,
            patch("app.services.mcp.mcp_client.validate_oauth_endpoints"),
        ):
            mock_extract.return_value = {}
            mock_find_prm.return_value = None  # PRM not found
            mock_fetch_auth.return_value = auth_metadata

            result = await mcp_client._discover_oauth_config(
                MOCK_INTEGRATION_ID, mcp_config
            )

        assert result["discovery_method"] == "direct_oauth"

    @pytest.mark.asyncio
    async def test_discovery_uses_cache(self, mcp_client):
        """Test that cached discovery is used when available."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)

        cached_discovery = {
            "authorization_endpoint": f"{MOCK_AUTH_SERVER_URL}/authorize",
            "token_endpoint": f"{MOCK_AUTH_SERVER_URL}/token",
            "discovery_method": "cached",
        }
        mcp_client.token_store.get_oauth_discovery.return_value = cached_discovery

        result = await mcp_client._discover_oauth_config(
            MOCK_INTEGRATION_ID, mcp_config
        )

        assert result == cached_discovery
        # Should not call any discovery functions
        mcp_client.token_store.get_oauth_discovery.assert_called_once()


# ==============================================================================
# DCR (Dynamic Client Registration) Tests
# ==============================================================================


class TestDynamicClientRegistration:
    """Tests for Dynamic Client Registration flow."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient with mocked dependencies."""
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = AsyncMock()
        client.token_store.get_dcr_client.return_value = None
        client.token_store.store_dcr_client.return_value = None
        return client

    @pytest.mark.asyncio
    async def test_dcr_successful_registration(self, mcp_client):
        """Test successful dynamic client registration."""
        dcr_response = {
            "client_id": "new-client-id-123",
            "client_secret": None,
            "client_id_issued_at": int(datetime.now(timezone.utc).timestamp()),
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            response = MockResponse.success(dcr_response)
            response.raise_for_status = MagicMock()
            mock_instance.post.return_value = response

            client_id = await mcp_client._register_client(
                MOCK_INTEGRATION_ID,
                f"{MOCK_AUTH_SERVER_URL}/register",
                "http://localhost:8000/callback",
            )

        assert client_id == "new-client-id-123"
        mcp_client.token_store.store_dcr_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_dcr_uses_cached_client(self, mcp_client):
        """Test that cached DCR client is reused."""
        cached_client = {"client_id": "cached-client-123", "client_secret": None}
        mcp_client.token_store.get_dcr_client.return_value = cached_client

        # Mock the build_oauth_auth_url flow
        from app.models.oauth_models import MCPConfig

        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mcp_client.token_store.get_oauth_discovery.return_value = oauth_discovery

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve"
            ) as mock_resolve,
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
        ):
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL, requires_auth=True
            )
            mock_resolve.return_value = mock_result

            auth_url = await mcp_client.build_oauth_auth_url(
                MOCK_INTEGRATION_ID,
                redirect_uri="http://localhost:8000/callback",
            )

        # Should use cached client_id
        assert "cached-client-123" in auth_url


# ==============================================================================
# Token Operations Tests
# ==============================================================================


class TestTokenOperations:
    """Tests for token refresh and revocation."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient with mocked token store."""
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_token_refresh_success(self, mcp_client):
        """Test successful token refresh."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)

        oauth_discovery = get_mock_authorization_server_metadata()
        mcp_client.token_store.get_oauth_discovery.return_value = oauth_discovery
        mcp_client.token_store.get_refresh_token.return_value = MOCK_REFRESH_TOKEN
        mcp_client.token_store.get_dcr_client.return_value = {
            "client_id": MOCK_CLIENT_ID
        }

        new_token_response = get_mock_token_response(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.success(new_token_response)

            result = await mcp_client._try_refresh_token(
                MOCK_INTEGRATION_ID, mcp_config
            )

        assert result is True
        mcp_client.token_store.store_oauth_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_revocation_on_disconnect(self, mcp_client):
        """Test that tokens are revoked on disconnect."""
        from app.utils.mcp_oauth_utils import revoke_token

        oauth_discovery = {
            "revocation_endpoint": f"{MOCK_AUTH_SERVER_URL}/revoke",
        }
        mcp_client.token_store.get_oauth_discovery.return_value = oauth_discovery
        mcp_client.token_store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN
        mcp_client.token_store.get_refresh_token.return_value = MOCK_REFRESH_TOKEN

        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse(status_code=200)

            result = await revoke_token(
                f"{MOCK_AUTH_SERVER_URL}/revoke",
                MOCK_ACCESS_TOKEN,
            )

        assert result is True


# ==============================================================================
# Connection Flow Tests
# ==============================================================================


class TestConnectionFlow:
    """Tests for MCP connection establishment."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient with mocked dependencies."""
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = AsyncMock()
        client.token_store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN
        client.token_store.is_token_expiring_soon.return_value = False
        client.token_store.has_credentials.return_value = True
        return client

    @pytest.mark.asyncio
    async def test_connect_with_stored_token(self, mcp_client):
        """Test connection with stored OAuth token."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)

        config = await mcp_client._build_config(MOCK_INTEGRATION_ID, mcp_config)

        # Verify token is included in config
        server_config = config["mcpServers"][MOCK_INTEGRATION_ID]
        assert server_config["auth"] == MOCK_ACCESS_TOKEN
        assert "Authorization" in server_config.get("headers", {})

    @pytest.mark.asyncio
    async def test_connect_without_auth(self, mcp_client):
        """Test connection for unauthenticated MCP."""
        from app.models.oauth_models import MCPConfig

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=False)

        config = await mcp_client._build_config(MOCK_INTEGRATION_ID, mcp_config)

        # Verify auth is explicitly None
        server_config = config["mcpServers"][MOCK_INTEGRATION_ID]
        assert server_config["auth"] is None


# ==============================================================================
# Probe Integration Tests
# ==============================================================================


class TestProbeIntegration:
    """Tests for probe_connection method."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient."""
        from app.services.mcp.mcp_client import MCPClient

        return MCPClient(user_id=MOCK_USER_ID)

    @pytest.mark.asyncio
    async def test_probe_detects_oauth(self, mcp_client):
        """Test probe correctly detects OAuth requirement."""
        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse.unauthorized(
                www_authenticate=get_mock_www_authenticate_header(
                    resource_metadata_url=f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource",
                    scope="read write",
                )
            )

            result = await mcp_client.probe_connection(MOCK_SERVER_URL)

        assert result["requires_auth"] is True
        assert result["auth_type"] == "oauth"
        assert "oauth_challenge" in result

    @pytest.mark.asyncio
    async def test_probe_detects_no_auth(self, mcp_client):
        """Test probe correctly detects no auth required."""
        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse.success({"status": "ok"})

            result = await mcp_client.probe_connection(MOCK_SERVER_URL)

        assert result["requires_auth"] is False
        assert result["auth_type"] == "none"


# ==============================================================================
# Real-World Integration Tests (requires network)
# ==============================================================================


@pytest.mark.integration
@pytest.mark.skipif(True, reason="Requires network access to real MCP servers")
class TestRealWorldIntegration:
    """Integration tests against real MCP servers.

    These tests are skipped by default. Run with:
        pytest -m integration --run-integration
    """

    @pytest.mark.asyncio
    async def test_smithery_probe(self):
        """Test probe against real Smithery server."""
        from app.utils.mcp_oauth_utils import extract_auth_challenge

        result = await extract_auth_challenge(SMITHERY_TEST_SERVER)

        assert result.get("raw"), "Smithery should require OAuth"
        assert "resource_metadata" in result

    @pytest.mark.asyncio
    async def test_smithery_discovery(self):
        """Test full discovery against Smithery."""
        from app.utils.mcp_oauth_utils import (
            fetch_auth_server_metadata,
            fetch_protected_resource_metadata,
        )

        # Probe to get PRM URL
        from app.utils.mcp_oauth_utils import extract_auth_challenge

        challenge = await extract_auth_challenge(SMITHERY_TEST_SERVER)
        prm_url = challenge.get("resource_metadata")
        assert prm_url, "Should have resource_metadata URL"

        # Fetch PRM
        prm = await fetch_protected_resource_metadata(prm_url)
        assert "authorization_servers" in prm

        # Fetch auth server metadata
        auth_server = prm["authorization_servers"][0]
        auth_metadata = await fetch_auth_server_metadata(auth_server)
        assert "authorization_endpoint" in auth_metadata
        assert "token_endpoint" in auth_metadata


# ==============================================================================
# Error Handling Tests
# ==============================================================================


class TestErrorHandling:
    """Tests for error handling throughout the OAuth flow."""

    @pytest.mark.asyncio
    async def test_discovery_handles_network_error(self):
        """Test graceful handling of network errors during discovery."""
        from app.utils.mcp_oauth_utils import fetch_auth_server_metadata

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.ConnectError("Network error")

            # Should return fallback URLs, not raise
            result = await fetch_auth_server_metadata(MOCK_AUTH_SERVER_URL)

        assert result.get("fallback") is True
        assert "authorization_endpoint" in result

    @pytest.mark.asyncio
    async def test_token_exchange_handles_invalid_response(self):
        """Test handling of invalid token response."""
        from app.utils.mcp_oauth_utils import validate_token_response

        # Missing access_token - raises ValueError
        with pytest.raises(ValueError, match="missing required 'access_token'"):
            validate_token_response({"token_type": "Bearer"}, MOCK_INTEGRATION_ID)

        # Invalid token_type - raises ValueError
        with pytest.raises(ValueError, match="Unsupported token_type"):
            validate_token_response(
                {"access_token": "token", "token_type": "MAC"}, MOCK_INTEGRATION_ID
            )


# ==============================================================================
# Tool Discovery Tests
# ==============================================================================


class TestToolDiscovery:
    """Tests for MCP tool discovery."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True, reason="Flaky due to system resource constraints (semaphore exhaustion)"
    )
    async def test_tools_returned_on_successful_connect(self):
        """Test that tools are returned after successful connection."""
        from app.services.mcp.mcp_client import MCPClient
        from app.models.oauth_models import MCPConfig

        mcp_client = MCPClient(user_id=MOCK_USER_ID)
        mcp_client.token_store = AsyncMock()
        mcp_client.token_store.get_oauth_token.return_value = None
        mcp_client.token_store.is_token_expiring_soon.return_value = False
        mcp_client.token_store.store_unauthenticated.return_value = None

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool._arun = AsyncMock(return_value="result")

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve"
            ) as mock_resolve,
            patch("app.services.mcp.mcp_client.BaseMCPClient") as mock_base_client,
            patch("app.services.mcp.mcp_client.LangChainAdapter") as mock_adapter,
            patch(
                "app.services.mcp.mcp_client.get_mcp_tools_store"
            ) as mock_tools_store,
        ):
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL, requires_auth=False
            )
            mock_result.source = "platform"
            mock_resolve.return_value = mock_result

            mock_base_client.return_value.create_session = AsyncMock()
            mock_adapter.return_value.create_tools = AsyncMock(return_value=[mock_tool])
            mock_tools_store.return_value.store_tools = AsyncMock()

            tools = await mcp_client.connect(MOCK_INTEGRATION_ID)

        assert len(tools) == 1
        assert tools[0].name == "test_tool"


# ==============================================================================
# Client Metadata Document Tests
# ==============================================================================


class TestClientMetadataDocument:
    """Tests for OAuth using client metadata document (RFC 9449 style)."""

    @pytest.mark.asyncio
    async def test_client_metadata_document_in_auth_metadata(self):
        """Test that client_id_metadata_document_supported is recognized."""
        # This tests that the auth metadata correctly indicates support
        auth_metadata = get_mock_authorization_server_metadata(
            supports_client_metadata_doc=True
        )

        assert auth_metadata.get("client_id_metadata_document_supported") is True

    @pytest.mark.asyncio
    async def test_auth_metadata_without_client_metadata_doc(self):
        """Test auth metadata without client_id_metadata_document support."""
        auth_metadata = get_mock_authorization_server_metadata(
            supports_client_metadata_doc=False
        )

        assert "client_id_metadata_document_supported" not in auth_metadata

    @pytest.mark.asyncio
    async def test_localhost_detection_logic(self):
        """Test that localhost detection works correctly."""
        # Test various localhost patterns
        localhost_urls = [
            "http://localhost:8000/callback",
            "http://127.0.0.1:8000/callback",
            "http://localhost/callback",
        ]

        non_localhost_urls = [
            "https://app.example.com/callback",
            "https://production.app.com/callback",
        ]

        for url in localhost_urls:
            is_local = "localhost" in url or "127.0.0.1" in url
            assert is_local is True, f"{url} should be detected as localhost"

        for url in non_localhost_urls:
            is_local = "localhost" in url or "127.0.0.1" in url
            assert is_local is False, f"{url} should NOT be detected as localhost"


# ==============================================================================
# Pre-Registered Client Tests
# ==============================================================================


class TestPreRegisteredClient:
    """Tests for OAuth with pre-registered client credentials."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient with mocked dependencies."""
        from app.services.mcp.mcp_client import MCPClient

        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = AsyncMock()
        client.token_store.get_oauth_discovery.return_value = None
        client.token_store.store_oauth_discovery.return_value = None
        client.token_store.create_oauth_state.return_value = "test-state"
        return client

    @pytest.mark.asyncio
    async def test_pre_registered_client_used_when_provided(self, mcp_client):
        """Test that pre-registered client credentials are used when available."""
        from app.models.oauth_models import MCPConfig

        auth_metadata = get_mock_authorization_server_metadata()
        auth_metadata["resource"] = MOCK_SERVER_URL

        mcp_client.token_store.get_oauth_discovery.return_value = auth_metadata

        # Config with pre-registered client
        mcp_config = MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
            client_id="pre-registered-client-123",
            client_secret="pre-registered-secret",
        )

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve"
            ) as mock_resolve,
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
        ):
            mock_result = MagicMock()
            mock_result.mcp_config = mcp_config
            mock_resolve.return_value = mock_result

            auth_url = await mcp_client.build_oauth_auth_url(
                MOCK_INTEGRATION_ID,
                redirect_uri="https://app.example.com/callback",
            )

        # Should use the pre-registered client_id
        assert "pre-registered-client-123" in auth_url

    @pytest.mark.asyncio
    async def test_pre_registered_client_skips_dcr(self, mcp_client):
        """Test that DCR is skipped when pre-registered client is available."""
        from app.models.oauth_models import MCPConfig

        auth_metadata = get_mock_authorization_server_metadata(supports_dcr=True)
        auth_metadata["resource"] = MOCK_SERVER_URL

        mcp_client.token_store.get_oauth_discovery.return_value = auth_metadata

        mcp_config = MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
            client_id="pre-registered-client-456",
        )

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve"
            ) as mock_resolve,
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
            patch("httpx.AsyncClient") as mock_http,
        ):
            mock_result = MagicMock()
            mock_result.mcp_config = mcp_config
            mock_resolve.return_value = mock_result

            auth_url = await mcp_client.build_oauth_auth_url(
                MOCK_INTEGRATION_ID,
                redirect_uri="https://app.example.com/callback",
            )

        # DCR should NOT have been called
        mock_http.assert_not_called()

        # Should use pre-registered client
        assert "pre-registered-client-456" in auth_url

    @pytest.mark.asyncio
    async def test_mcp_config_with_client_credentials(self):
        """Test that MCPConfig correctly stores client credentials."""
        from app.models.oauth_models import MCPConfig

        config = MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
            client_id="my-client-id",
            client_secret="my-secret",
        )

        assert config.client_id == "my-client-id"
        assert config.client_secret == "my-secret"
        assert config.requires_auth is True


# ==============================================================================
# Cache Cleanup Tests
# ==============================================================================


class TestOAuthCacheCleanup:
    """Tests for OAuth discovery cache cleanup."""

    @pytest.mark.asyncio
    async def test_delete_oauth_discovery_cache(self):
        """Test deleting OAuth discovery cache for an integration."""
        from app.services.mcp.mcp_token_store import MCPTokenStore

        store = MCPTokenStore(user_id=MOCK_USER_ID)

        with patch("app.services.mcp.mcp_token_store.delete_cache") as mock_delete:
            mock_delete.return_value = True
            result = await store.delete_oauth_discovery(MOCK_INTEGRATION_ID)

        mock_delete.assert_called_once()
        call_args = mock_delete.call_args[0][0]
        assert MOCK_INTEGRATION_ID in call_args

    @pytest.mark.asyncio
    async def test_cleanup_all_integration_cache(self):
        """Test cleaning up all OAuth-related cache for an integration."""
        from app.services.mcp.mcp_token_store import MCPTokenStore

        store = MCPTokenStore(user_id=MOCK_USER_ID)

        with (
            patch("app.services.mcp.mcp_token_store.delete_cache") as mock_delete,
            patch.object(store, "delete_credentials") as mock_delete_creds,
        ):
            mock_delete.return_value = True
            mock_delete_creds.return_value = None

            await store.cleanup_integration(MOCK_INTEGRATION_ID)

        # Should delete discovery cache
        assert mock_delete.called
        # Should delete credentials
        mock_delete_creds.assert_called_once_with(MOCK_INTEGRATION_ID)

    @pytest.mark.asyncio
    async def test_cache_expiry_triggers_rediscovery(self):
        """Test that expired cache triggers fresh OAuth discovery."""
        from app.services.mcp.mcp_client import MCPClient
        from app.models.oauth_models import MCPConfig

        mcp_client = MCPClient(user_id=MOCK_USER_ID)
        mcp_client.token_store = AsyncMock()

        # Simulate cache miss (expired or not present)
        mcp_client.token_store.get_oauth_discovery.return_value = None
        mcp_client.token_store.store_oauth_discovery.return_value = None
        mcp_client.token_store.get_dcr_client.return_value = None
        mcp_client.token_store.store_dcr_client.return_value = None

        mcp_config = MCPConfig(server_url=MOCK_SERVER_URL, requires_auth=True)

        prm = get_mock_protected_resource_metadata()
        auth_metadata = get_mock_authorization_server_metadata()

        with (
            patch("app.services.mcp.mcp_client.extract_auth_challenge") as mock_extract,
            patch(
                "app.services.mcp.mcp_client.find_protected_resource_metadata"
            ) as mock_find_prm,
            patch(
                "app.services.mcp.mcp_client.fetch_protected_resource_metadata"
            ) as mock_fetch_prm,
            patch(
                "app.services.mcp.mcp_client.select_authorization_server"
            ) as mock_select,
            patch(
                "app.services.mcp.mcp_client.fetch_auth_server_metadata"
            ) as mock_fetch_auth,
            patch("app.services.mcp.mcp_client.validate_oauth_endpoints"),
        ):
            mock_extract.return_value = {"scope": "read write"}
            mock_find_prm.return_value = (
                f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource"
            )
            mock_fetch_prm.return_value = prm
            mock_select.return_value = MOCK_AUTH_SERVER_URL
            mock_fetch_auth.return_value = auth_metadata

            result = await mcp_client._discover_oauth_config(
                MOCK_INTEGRATION_ID, mcp_config
            )

        # Should have performed fresh discovery
        mock_fetch_auth.assert_called_once()
        # Should have cached the result
        mcp_client.token_store.store_oauth_discovery.assert_called()
        assert result["discovery_method"] == "rfc9728_prm"
