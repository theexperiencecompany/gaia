"""
Integration tests for MCP OAuth client flow.

Tests the complete OAuth 2.1 authorization flow including:
- Server probing and auth detection
- OAuth discovery (RFC 9728 + RFC 8414)
- Dynamic Client Registration (RFC 7591)
- Authorization URL building with PKCE
- Token exchange with resource binding (RFC 8707)
- Token refresh
- Token revocation on disconnect
- Step-up authorization handling
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.models.oauth_models import MCPConfig
from app.services.mcp.mcp_client import (
    DCRNotSupportedException,
    MCPClient,
    StepUpAuthRequired,
)

from .conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_AUTH_SERVER_URL,
    MOCK_AUTHORIZATION_CODE,
    MOCK_CLIENT_ID,
    MOCK_CLIENT_SECRET,
    MOCK_INTEGRATION_ID,
    MOCK_REFRESH_TOKEN,
    MOCK_SERVER_URL,
    MOCK_USER_ID,
    MockOAuthServer,
    MockResponse,
    get_mock_authorization_server_metadata,
    get_mock_dcr_response,
    get_mock_protected_resource_metadata,
    get_mock_token_response,
    get_mock_www_authenticate_header,
)


# ==============================================================================
# MCPClient OAuth Discovery Tests
# ==============================================================================


class TestMCPClientProbe:
    """Tests for MCPClient.probe_connection method."""

    @pytest.fixture
    def mcp_client(self):
        """Create an MCPClient instance for testing."""
        return MCPClient(user_id=MOCK_USER_ID)

    @pytest.mark.asyncio
    async def test_probe_detects_oauth_required(self, mcp_client):
        """Should detect when OAuth is required."""
        www_auth = get_mock_www_authenticate_header(
            resource_metadata_url=f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource",
            scope="read write",
        )

        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.unauthorized(www_authenticate=www_auth)
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await mcp_client.probe_connection(MOCK_SERVER_URL)

        assert result["requires_auth"] is True
        assert result["auth_type"] == "oauth"
        assert "oauth_challenge" in result

    @pytest.mark.asyncio
    async def test_probe_detects_no_auth_required(self, mcp_client):
        """Should detect when no auth is required."""
        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.success({"status": "ok"})
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await mcp_client.probe_connection(MOCK_SERVER_URL)

        assert result["requires_auth"] is False
        assert result["auth_type"] == "none"

    @pytest.mark.asyncio
    async def test_probe_handles_connection_error(self, mcp_client):
        """Should handle connection errors gracefully."""
        with patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            result = await mcp_client.probe_connection(MOCK_SERVER_URL)

        assert result["requires_auth"] is False
        assert "error" in result


class TestMCPClientOAuthDiscovery:
    """Tests for MCPClient._discover_oauth_config method."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked token store."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.fixture
    def mcp_config(self):
        """Create a mock MCPConfig."""
        return MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
        )

    @pytest.mark.asyncio
    async def test_discovery_via_prm(self, mcp_client, mcp_config):
        """Should discover OAuth config via Protected Resource Metadata."""
        prm = get_mock_protected_resource_metadata()
        auth_metadata = get_mock_authorization_server_metadata()

        with (
            patch("app.utils.mcp_oauth_utils.httpx.AsyncClient") as mock_oauth_client,
            patch("app.services.mcp.mcp_client.extract_auth_challenge") as mock_extract,
            patch(
                "app.services.mcp.mcp_client.find_protected_resource_metadata"
            ) as mock_find_prm,
            patch(
                "app.services.mcp.mcp_client.fetch_protected_resource_metadata"
            ) as mock_fetch_prm,
            patch(
                "app.services.mcp.mcp_client.fetch_auth_server_metadata"
            ) as mock_fetch_auth,
            patch(
                "app.services.mcp.mcp_client.select_authorization_server"
            ) as mock_select_auth,
            patch("app.services.mcp.mcp_client.validate_oauth_endpoints"),
        ):
            # Mock extract_auth_challenge to return empty (no resource_metadata in header)
            mock_extract.return_value = {"scope": "read write"}

            # Mock find_protected_resource_metadata to return a URL
            mock_find_prm.return_value = (
                f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource"
            )

            # Mock fetch_protected_resource_metadata to return the PRM data
            mock_fetch_prm.return_value = prm

            # Mock select_authorization_server to return the auth server URL
            mock_select_auth.return_value = MOCK_AUTH_SERVER_URL

            # Mock fetch_auth_server_metadata to return auth metadata
            mock_fetch_auth.return_value = auth_metadata

            result = await mcp_client._discover_oauth_config(
                MOCK_INTEGRATION_ID, mcp_config
            )

        assert result["discovery_method"] == "rfc9728_prm"
        assert "authorization_endpoint" in result
        assert "token_endpoint" in result
        assert result["resource"] == MOCK_SERVER_URL

    @pytest.mark.asyncio
    async def test_discovery_caches_result(
        self, mcp_client, mcp_config, mock_token_store
    ):
        """Should cache discovery result."""
        cached_discovery = {
            "authorization_endpoint": f"{MOCK_AUTH_SERVER_URL}/authorize",
            "token_endpoint": f"{MOCK_AUTH_SERVER_URL}/token",
            "discovery_method": "cached",
        }
        mock_token_store.get_oauth_discovery.return_value = cached_discovery

        result = await mcp_client._discover_oauth_config(
            MOCK_INTEGRATION_ID, mcp_config
        )

        assert result == cached_discovery


class TestMCPClientBuildAuthUrl:
    """Tests for MCPClient.build_oauth_auth_url method."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_builds_auth_url_with_pkce(self, mcp_client, mock_token_store):
        """Should build authorization URL with PKCE parameters."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery

        # Mock the integration resolver
        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve"
        ) as mock_resolver:
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL,
                requires_auth=True,
                client_id=MOCK_CLIENT_ID,
            )
            mock_resolver.return_value = mock_result

            auth_url = await mcp_client.build_oauth_auth_url(
                integration_id=MOCK_INTEGRATION_ID,
                redirect_uri="https://api.example.com/callback",
            )

        # Verify URL structure
        assert f"{MOCK_AUTH_SERVER_URL}/authorize" in auth_url
        assert "client_id=" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "response_type=code" in auth_url
        assert "state=" in auth_url
        assert f"resource={MOCK_SERVER_URL}" in auth_url or "resource=" in auth_url

    @pytest.mark.asyncio
    async def test_uses_client_metadata_document_when_supported(
        self, mcp_client, mock_token_store
    ):
        """Should use client metadata document URL as client_id when supported."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["client_id_metadata_document_supported"] = True
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery

        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve"
        ) as mock_resolver:
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL,
                requires_auth=True,
                # No client_id configured - should use metadata document
            )
            mock_resolver.return_value = mock_result

            with patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="https://api.example.com",
            ):
                auth_url = await mcp_client.build_oauth_auth_url(
                    integration_id=MOCK_INTEGRATION_ID,
                    redirect_uri="https://api.example.com/callback",
                )

        # Verify client metadata document URL is used as client_id
        assert "client-metadata.json" in auth_url

    @pytest.mark.asyncio
    async def test_falls_back_to_dcr_on_localhost(self, mcp_client, mock_token_store):
        """Should fall back to DCR when running on localhost even if client metadata doc is supported."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["client_id_metadata_document_supported"] = True
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery

        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve"
        ) as mock_resolver:
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL,
                requires_auth=True,
            )
            mock_resolver.return_value = mock_result

            with patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="http://localhost:8000",  # Localhost!
            ):
                with patch.object(
                    mcp_client, "_register_client", new_callable=AsyncMock
                ) as mock_dcr:
                    mock_dcr.return_value = "dcr-client-id-123"

                    auth_url = await mcp_client.build_oauth_auth_url(
                        integration_id=MOCK_INTEGRATION_ID,
                        redirect_uri="http://localhost:8000/callback",
                    )

        # Verify DCR was called (fallback from client metadata doc)
        mock_dcr.assert_called_once()
        # Verify the DCR client_id is in the URL, not a metadata document URL
        assert "dcr-client-id-123" in auth_url
        assert "client-metadata.json" not in auth_url


class TestMCPClientTokenExchange:
    """Tests for MCPClient.handle_oauth_callback method."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_exchanges_code_for_tokens(self, mcp_client, mock_token_store):
        """Should exchange authorization code for tokens."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery
        mock_token_store.verify_oauth_state.return_value = (True, "test-code-verifier")
        mock_token_store.get_dcr_client.return_value = {
            "client_id": MOCK_CLIENT_ID,
        }

        token_response = get_mock_token_response()

        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve"
        ) as mock_resolver:
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL,
                requires_auth=True,
            )
            mock_resolver.return_value = mock_result

            with patch("httpx.AsyncClient") as mock_http:
                mock_instance = AsyncMock()
                mock_http.return_value.__aenter__.return_value = mock_instance
                mock_instance.post.return_value = MockResponse.success(token_response)

                # Mock connect to avoid actual MCP connection
                with patch.object(mcp_client, "connect", return_value=[]):
                    await mcp_client.handle_oauth_callback(
                        integration_id=MOCK_INTEGRATION_ID,
                        code=MOCK_AUTHORIZATION_CODE,
                        state="test-state",
                        redirect_uri="https://api.example.com/callback",
                    )

        # Verify tokens were stored
        mock_token_store.store_oauth_tokens.assert_called_once()
        call_args = mock_token_store.store_oauth_tokens.call_args
        assert call_args.kwargs["access_token"] == MOCK_ACCESS_TOKEN
        assert call_args.kwargs["refresh_token"] == MOCK_REFRESH_TOKEN

    @pytest.mark.asyncio
    async def test_handles_invalid_state(self, mcp_client, mock_token_store):
        """Should reject invalid OAuth state."""
        mock_token_store.verify_oauth_state.return_value = (False, None)

        with pytest.raises(ValueError) as exc_info:
            await mcp_client.handle_oauth_callback(
                integration_id=MOCK_INTEGRATION_ID,
                code=MOCK_AUTHORIZATION_CODE,
                state="invalid-state",
                redirect_uri="https://api.example.com/callback",
            )

        assert "state" in str(exc_info.value).lower()


class TestMCPClientTokenRefresh:
    """Tests for MCPClient._try_refresh_token method."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_refreshes_token_successfully(self, mcp_client, mock_token_store):
        """Should refresh token using refresh_token grant."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["resource"] = MOCK_SERVER_URL
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery
        mock_token_store.get_refresh_token.return_value = MOCK_REFRESH_TOKEN
        mock_token_store.get_dcr_client.return_value = {
            "client_id": MOCK_CLIENT_ID,
        }

        new_token_response = get_mock_token_response(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
        )

        mcp_config = MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
        )

        with patch("httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_http.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.success(new_token_response)

            result = await mcp_client._try_refresh_token(
                MOCK_INTEGRATION_ID, mcp_config
            )

        assert result is True
        mock_token_store.store_oauth_tokens.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_fails_without_refresh_token(
        self, mcp_client, mock_token_store
    ):
        """Should return False when no refresh token is available."""
        mock_token_store.get_refresh_token.return_value = None

        mcp_config = MCPConfig(
            server_url=MOCK_SERVER_URL,
            requires_auth=True,
        )

        result = await mcp_client._try_refresh_token(MOCK_INTEGRATION_ID, mcp_config)

        assert result is False


class TestMCPClientDisconnect:
    """Tests for MCPClient.disconnect method with token revocation."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_revokes_tokens_on_disconnect(self, mcp_client, mock_token_store):
        """Should revoke tokens at authorization server on disconnect."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["revocation_endpoint"] = f"{MOCK_AUTH_SERVER_URL}/revoke"
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery
        mock_token_store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN
        mock_token_store.get_refresh_token.return_value = MOCK_REFRESH_TOKEN

        with patch(
            "app.services.mcp.mcp_client.revoke_token", new_callable=AsyncMock
        ) as mock_revoke:
            mock_revoke.return_value = True

            with patch("app.db.redis.delete_cache", new_callable=AsyncMock):
                await mcp_client.disconnect(MOCK_INTEGRATION_ID)

        # Should revoke both refresh and access tokens
        assert mock_revoke.call_count == 2
        mock_token_store.delete_credentials.assert_called_once_with(MOCK_INTEGRATION_ID)

    @pytest.mark.asyncio
    async def test_disconnect_continues_on_revocation_failure(
        self, mcp_client, mock_token_store
    ):
        """Should continue disconnect even if revocation fails."""
        oauth_discovery = get_mock_authorization_server_metadata()
        oauth_discovery["revocation_endpoint"] = f"{MOCK_AUTH_SERVER_URL}/revoke"
        mock_token_store.get_oauth_discovery.return_value = oauth_discovery
        mock_token_store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN

        with patch(
            "app.services.mcp.mcp_client.revoke_token", new_callable=AsyncMock
        ) as mock_revoke:
            mock_revoke.side_effect = Exception("Revocation failed")

            with patch("app.db.redis.delete_cache", new_callable=AsyncMock):
                # Should not raise
                await mcp_client.disconnect(MOCK_INTEGRATION_ID)

        # Credentials should still be deleted
        mock_token_store.delete_credentials.assert_called_once()


class TestMCPClientDCR:
    """Tests for Dynamic Client Registration."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_successful_dcr(self, mcp_client, mock_token_store):
        """Should successfully register client via DCR."""
        dcr_response = get_mock_dcr_response()

        with patch("httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_http.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.success(dcr_response)

            client_id = await mcp_client._register_client(
                MOCK_INTEGRATION_ID,
                f"{MOCK_AUTH_SERVER_URL}/register",
                "https://api.example.com/callback",
            )

        assert client_id == dcr_response["client_id"]
        mock_token_store.store_dcr_client.assert_called_once()

    @pytest.mark.asyncio
    async def test_dcr_not_supported(self, mcp_client):
        """Should raise DCRNotSupportedException for 403/404/405."""
        with patch("httpx.AsyncClient") as mock_http:
            mock_instance = AsyncMock()
            mock_http.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.error(404, "not_found")

            with pytest.raises(DCRNotSupportedException):
                await mcp_client._register_client(
                    MOCK_INTEGRATION_ID,
                    f"{MOCK_AUTH_SERVER_URL}/register",
                    "https://api.example.com/callback",
                )


class TestStepUpAuthorization:
    """Tests for step-up authorization (403 insufficient_scope)."""

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked dependencies."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_detects_insufficient_scope(self, mcp_client, mock_token_store):
        """Should raise StepUpAuthRequired for 403 insufficient_scope."""
        mock_token_store.get_oauth_token.return_value = MOCK_ACCESS_TOKEN

        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve"
        ) as mock_resolver:
            mock_result = MagicMock()
            mock_result.mcp_config = MCPConfig(
                server_url=MOCK_SERVER_URL,
                requires_auth=True,
            )
            mock_result.source = "platform"
            mock_resolver.return_value = mock_result

            with patch("app.services.mcp.mcp_client.BaseMCPClient") as mock_base_client:
                # Simulate 403 insufficient_scope error (matching what the code checks for)
                mock_base_client.return_value.create_session.side_effect = Exception(
                    '403 Forbidden: insufficient_scope, scope="admin write"'
                )

                with pytest.raises(StepUpAuthRequired) as exc_info:
                    await mcp_client.connect(MOCK_INTEGRATION_ID)

        assert exc_info.value.integration_id == MOCK_INTEGRATION_ID
        assert "admin" in exc_info.value.required_scopes


# ==============================================================================
# End-to-End OAuth Flow Tests with Mock Server
# ==============================================================================


class TestEndToEndOAuthFlow:
    """End-to-end tests using MockOAuthServer."""

    @pytest.fixture
    def oauth_server(self):
        """Create a mock OAuth server."""
        return MockOAuthServer()

    @pytest.fixture
    def mcp_client(self, mock_token_store):
        """Create an MCPClient with mocked token store."""
        client = MCPClient(user_id=MOCK_USER_ID)
        client.token_store = mock_token_store
        return client

    @pytest.mark.asyncio
    async def test_complete_oauth_flow(
        self, oauth_server, mcp_client, mock_token_store
    ):
        """Test complete OAuth 2.1 flow from discovery to token exchange."""
        # Step 1: Probe returns 401 requiring auth
        probe_response = oauth_server.handle_request("GET", MOCK_SERVER_URL)
        assert probe_response.status_code == 401

        # Step 2: Discover protected resource metadata
        prm_response = oauth_server.handle_request(
            "GET", f"{MOCK_SERVER_URL}/.well-known/oauth-protected-resource"
        )
        assert prm_response.status_code == 200
        prm = prm_response.json()
        assert "authorization_servers" in prm

        # Step 3: Discover authorization server metadata
        auth_metadata_response = oauth_server.handle_request(
            "GET", f"{MOCK_AUTH_SERVER_URL}/.well-known/oauth-authorization-server"
        )
        assert auth_metadata_response.status_code == 200
        auth_metadata = auth_metadata_response.json()
        assert "authorization_endpoint" in auth_metadata

        # Step 4: Register client via DCR
        dcr_response = oauth_server.handle_request(
            "POST",
            f"{MOCK_AUTH_SERVER_URL}/register",
            json={
                "client_name": "Test Client",
                "redirect_uris": ["https://api.example.com/callback"],
            },
        )
        assert dcr_response.status_code == 200
        dcr_data = dcr_response.json()
        client_id = dcr_data["client_id"]

        # Step 5: Create authorization code (simulating user authorization)
        code_verifier = "test-code-verifier-12345678901234567890123456789012"
        import base64
        import hashlib

        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )

        auth_code = oauth_server.create_authorization_code(
            client_id=client_id,
            redirect_uri="https://api.example.com/callback",
            code_challenge=code_challenge,
        )

        # Step 6: Exchange code for tokens
        token_response = oauth_server.handle_request(
            "POST",
            f"{MOCK_AUTH_SERVER_URL}/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": client_id,
                "redirect_uri": "https://api.example.com/callback",
                "code_verifier": code_verifier,
            },
        )
        assert token_response.status_code == 200
        tokens = token_response.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

        # Step 7: Verify token via introspection
        introspect_response = oauth_server.handle_request(
            "POST",
            f"{MOCK_AUTH_SERVER_URL}/introspect",
            data={"token": tokens["access_token"]},
        )
        assert introspect_response.status_code == 200
        introspection = introspect_response.json()
        assert introspection["active"] is True

        # Step 8: Revoke token
        revoke_response = oauth_server.handle_request(
            "POST",
            f"{MOCK_AUTH_SERVER_URL}/revoke",
            data={"token": tokens["access_token"]},
        )
        assert revoke_response.status_code == 200

        # Step 9: Verify token is revoked
        introspect_response = oauth_server.handle_request(
            "POST",
            f"{MOCK_AUTH_SERVER_URL}/introspect",
            data={"token": tokens["access_token"]},
        )
        introspection = introspect_response.json()
        assert introspection["active"] is False
