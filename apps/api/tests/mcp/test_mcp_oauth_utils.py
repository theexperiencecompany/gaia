"""
Unit tests for MCP OAuth utilities.

Tests cover:
- HTTPS URL validation
- OAuth endpoint validation
- WWW-Authenticate header parsing
- Protected Resource Metadata discovery
- Authorization Server Metadata discovery
- Token revocation
- Token introspection
- OAuth error response parsing
- JWT issuer validation
- PKCE validation
- Client metadata document URL generation
- Authorization server selection
"""

import base64
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.mcp_oauth_utils import (
    MCP_PROTOCOL_VERSION,
    OAuthDiscoveryError,
    OAuthSecurityError,
    extract_auth_challenge,
    fetch_auth_server_metadata,
    fetch_protected_resource_metadata,
    find_protected_resource_metadata,
    get_client_metadata_document_url,
    introspect_token,
    parse_oauth_error_response,
    revoke_token,
    select_authorization_server,
    validate_https_url,
    validate_jwt_issuer,
    validate_oauth_endpoints,
    validate_pkce_support,
    validate_token_response,
)

from .conftest import (
    MOCK_ACCESS_TOKEN,
    MOCK_AUTH_SERVER_URL,
    MOCK_CLIENT_ID,
    MOCK_SERVER_URL,
    MockResponse,
    generate_mock_jwt,
    get_mock_authorization_server_metadata,
    get_mock_introspection_response,
    get_mock_protected_resource_metadata,
    get_mock_www_authenticate_header,
)


# ==============================================================================
# HTTPS Validation Tests
# ==============================================================================


class TestValidateHttpsUrl:
    """Tests for validate_https_url function."""

    def test_valid_https_url(self):
        """HTTPS URLs should pass validation."""
        validate_https_url("https://example.com")
        validate_https_url("https://example.com:8443/path")
        validate_https_url("https://api.example.com/v1/oauth/token")

    def test_http_url_raises_error(self):
        """HTTP URLs should raise OAuthSecurityError."""
        with pytest.raises(OAuthSecurityError) as exc_info:
            validate_https_url("http://example.com", allow_localhost=False)
        assert "must use HTTPS" in str(exc_info.value)

    def test_localhost_http_allowed_by_default(self):
        """HTTP localhost should be allowed by default (development)."""
        validate_https_url("http://localhost:8000")
        validate_https_url("http://127.0.0.1:8000")
        validate_https_url("http://localhost/callback")

    def test_localhost_http_can_be_disallowed(self):
        """HTTP localhost can be disallowed."""
        with pytest.raises(OAuthSecurityError):
            validate_https_url("http://localhost:8000", allow_localhost=False)

    def test_ipv6_localhost_allowed(self):
        """IPv6 localhost should be allowed."""
        validate_https_url("http://[::1]:8000")


class TestValidateOAuthEndpoints:
    """Tests for validate_oauth_endpoints function."""

    def test_all_https_endpoints_pass(self):
        """All HTTPS endpoints should pass."""
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "revocation_endpoint": "https://auth.example.com/revoke",
            "introspection_endpoint": "https://auth.example.com/introspect",
            "issuer": "https://auth.example.com",
        }
        validate_oauth_endpoints(config)  # Should not raise

    def test_http_endpoint_raises_error(self):
        """HTTP endpoint should raise error."""
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "http://auth.example.com/token",  # HTTP!
        }
        with pytest.raises(OAuthSecurityError) as exc_info:
            validate_oauth_endpoints(config, allow_localhost=False)
        assert "token_endpoint" in str(exc_info.value)

    def test_missing_endpoints_are_skipped(self):
        """Missing endpoints should be skipped."""
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            # token_endpoint missing
        }
        validate_oauth_endpoints(config)  # Should not raise


# ==============================================================================
# WWW-Authenticate Header Parsing Tests
# ==============================================================================


class TestExtractAuthChallenge:
    """Tests for extract_auth_challenge function."""

    @pytest.mark.asyncio
    async def test_extracts_resource_metadata(self):
        """Should extract resource_metadata from WWW-Authenticate header."""
        www_auth = get_mock_www_authenticate_header(
            resource_metadata_url="https://mcp.example.com/.well-known/oauth-protected-resource"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.unauthorized(www_authenticate=www_auth)
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result["raw"] == www_auth
        assert "resource_metadata" in result
        assert "oauth-protected-resource" in result["resource_metadata"]

    @pytest.mark.asyncio
    async def test_extracts_scope(self):
        """Should extract scope from WWW-Authenticate header."""
        www_auth = get_mock_www_authenticate_header(scope="read write admin")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.unauthorized(www_authenticate=www_auth)
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result["scope"] == "read write admin"

    @pytest.mark.asyncio
    async def test_extracts_error_info(self):
        """Should extract error and error_description."""
        www_auth = get_mock_www_authenticate_header(
            error="invalid_token", error_description="Token has expired"
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.unauthorized(www_authenticate=www_auth)
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result["error"] == "invalid_token"
        assert result["error_description"] == "Token has expired"

    @pytest.mark.asyncio
    async def test_returns_empty_dict_for_non_401(self):
        """Should return empty dict for non-401 responses."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MockResponse.success({"status": "ok"})
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_dict_on_error(self):
        """Should return empty dict on non-connection errors (e.g., timeout)."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.TimeoutException("Request timed out")
            )

            result = await extract_auth_challenge(MOCK_SERVER_URL)

        assert result == {}

    @pytest.mark.asyncio
    async def test_raises_connect_error(self):
        """Should re-raise ConnectError so caller can handle appropriately."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

            with pytest.raises(httpx.ConnectError):
                await extract_auth_challenge(MOCK_SERVER_URL)


# ==============================================================================
# Metadata Discovery Tests
# ==============================================================================


class TestFindProtectedResourceMetadata:
    """Tests for find_protected_resource_metadata function."""

    @pytest.mark.asyncio
    async def test_finds_path_aware_metadata(self):
        """Should find path-aware metadata first."""
        prm_data = get_mock_protected_resource_metadata()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # First call (path-aware) succeeds
            mock_instance.get.return_value = MockResponse.success(prm_data)

            result = await find_protected_resource_metadata(
                "https://mcp.example.com/api/v1"
            )

        assert result is not None
        assert "oauth-protected-resource" in result

    @pytest.mark.asyncio
    async def test_falls_back_to_root_metadata(self):
        """Should fall back to root metadata if path-aware fails."""
        prm_data = get_mock_protected_resource_metadata()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # First call fails, second succeeds
            mock_instance.get.side_effect = [
                MockResponse.error(404, "not_found"),
                MockResponse.success(prm_data),
            ]

            result = await find_protected_resource_metadata(
                "https://mcp.example.com/api/v1"
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        """Should return None when metadata not found."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse.error(404, "not_found")

            result = await find_protected_resource_metadata(MOCK_SERVER_URL)

        assert result is None


class TestFetchAuthServerMetadata:
    """Tests for fetch_auth_server_metadata function."""

    @pytest.mark.asyncio
    async def test_fetches_oauth_metadata(self):
        """Should fetch OAuth authorization server metadata."""
        metadata = get_mock_authorization_server_metadata()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.return_value = MockResponse.success(metadata)

            result = await fetch_auth_server_metadata(MOCK_AUTH_SERVER_URL)

        assert result["issuer"] == MOCK_AUTH_SERVER_URL
        assert "authorization_endpoint" in result
        assert "token_endpoint" in result

    @pytest.mark.asyncio
    async def test_tries_oidc_discovery(self):
        """Should try OIDC discovery as fallback."""
        metadata = get_mock_authorization_server_metadata()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance

            # OAuth metadata fails, OIDC succeeds
            mock_instance.get.side_effect = [
                MockResponse.error(404, "not_found"),  # path-aware OAuth
                MockResponse.error(404, "not_found"),  # path-aware OIDC
                MockResponse.error(404, "not_found"),  # root OAuth
                MockResponse.success(metadata),  # root OIDC
            ]

            result = await fetch_auth_server_metadata(MOCK_AUTH_SERVER_URL)

        assert "authorization_endpoint" in result

    @pytest.mark.asyncio
    async def test_returns_fallback_urls_when_discovery_fails(self):
        """Should return fallback URLs when all discovery fails."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.get.side_effect = httpx.ConnectError("Connection refused")

            result = await fetch_auth_server_metadata(MOCK_AUTH_SERVER_URL)

        assert result["fallback"] is True
        assert result["authorization_endpoint"] == f"{MOCK_AUTH_SERVER_URL}/authorize"
        assert result["token_endpoint"] == f"{MOCK_AUTH_SERVER_URL}/token"
        assert result["registration_endpoint"] == f"{MOCK_AUTH_SERVER_URL}/register"


# ==============================================================================
# Token Operations Tests
# ==============================================================================


class TestRevokeToken:
    """Tests for revoke_token function."""

    @pytest.mark.asyncio
    async def test_successful_revocation(self):
        """Should return True on successful revocation."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse(status_code=200)

            result = await revoke_token(
                revocation_endpoint=f"{MOCK_AUTH_SERVER_URL}/revoke",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_revocation_with_client_credentials(self):
        """Should include client credentials in request."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse(status_code=200)

            await revoke_token(
                revocation_endpoint=f"{MOCK_AUTH_SERVER_URL}/revoke",
                token=MOCK_ACCESS_TOKEN,
                client_id=MOCK_CLIENT_ID,
                client_secret="test-secret",
            )

            # Verify Authorization header was set
            call_kwargs = mock_instance.post.call_args.kwargs
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_revocation_returns_false_on_error(self):
        """Should return False on server error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.error(500, "server_error")

            result = await revoke_token(
                revocation_endpoint=f"{MOCK_AUTH_SERVER_URL}/revoke",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is False

    @pytest.mark.asyncio
    async def test_revocation_handles_timeout(self):
        """Should return False on timeout."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.side_effect = httpx.TimeoutException("Timeout")

            result = await revoke_token(
                revocation_endpoint=f"{MOCK_AUTH_SERVER_URL}/revoke",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is False


class TestIntrospectToken:
    """Tests for introspect_token function."""

    @pytest.mark.asyncio
    async def test_active_token_introspection(self):
        """Should return introspection data for active token."""
        introspection_response = get_mock_introspection_response(active=True)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.success(
                introspection_response
            )

            result = await introspect_token(
                introspection_endpoint=f"{MOCK_AUTH_SERVER_URL}/introspect",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is not None
        assert result["active"] is True
        assert "scope" in result

    @pytest.mark.asyncio
    async def test_inactive_token_introspection(self):
        """Should return inactive status for revoked/expired token."""
        introspection_response = get_mock_introspection_response(active=False)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.success(
                introspection_response
            )

            result = await introspect_token(
                introspection_endpoint=f"{MOCK_AUTH_SERVER_URL}/introspect",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is not None
        assert result["active"] is False

    @pytest.mark.asyncio
    async def test_introspection_returns_none_on_error(self):
        """Should return None on error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_client.return_value.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = MockResponse.error(401, "unauthorized")

            result = await introspect_token(
                introspection_endpoint=f"{MOCK_AUTH_SERVER_URL}/introspect",
                token=MOCK_ACCESS_TOKEN,
            )

        assert result is None


# ==============================================================================
# Error Response Parsing Tests
# ==============================================================================


class TestParseOAuthErrorResponse:
    """Tests for parse_oauth_error_response function."""

    def test_parses_json_error(self):
        """Should parse JSON error response."""
        response = MockResponse.error(
            400,
            "invalid_grant",
            "The authorization code has expired",
        )

        result = parse_oauth_error_response(response)

        assert result["error"] == "invalid_grant"
        assert result["error_description"] == "The authorization code has expired"
        assert result["status_code"] == 400

    def test_parses_json_without_content_type(self):
        """Should try to parse JSON even without content-type header."""
        response = MockResponse(
            status_code=400,
            content=json.dumps({"error": "invalid_request"}).encode(),
            headers={},  # No content-type
        )

        result = parse_oauth_error_response(response)

        assert result["error"] == "invalid_request"

    def test_handles_non_json_response(self):
        """Should handle non-JSON error response."""
        response = MockResponse(
            status_code=500,
            content=b"Internal Server Error",
            headers={"content-type": "text/plain"},
        )

        result = parse_oauth_error_response(response)

        assert result["error"] == "unknown_error"
        assert "Internal Server Error" in result["error_description"]


# ==============================================================================
# Token Response Validation Tests
# ==============================================================================


class TestValidateTokenResponse:
    """Tests for validate_token_response function."""

    def test_valid_token_response(self):
        """Valid token response should pass."""
        tokens = {
            "access_token": MOCK_ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        validate_token_response(tokens, "test-integration")  # Should not raise

    def test_missing_access_token_raises(self):
        """Missing access_token should raise ValueError."""
        tokens = {"token_type": "Bearer"}
        with pytest.raises(ValueError) as exc_info:
            validate_token_response(tokens, "test-integration")
        assert "access_token" in str(exc_info.value)

    def test_missing_token_type_raises(self):
        """Missing token_type should raise ValueError."""
        tokens = {"access_token": MOCK_ACCESS_TOKEN}
        with pytest.raises(ValueError) as exc_info:
            validate_token_response(tokens, "test-integration")
        assert "token_type" in str(exc_info.value)

    def test_non_bearer_token_type_raises(self):
        """Non-Bearer token_type should raise ValueError."""
        tokens = {
            "access_token": MOCK_ACCESS_TOKEN,
            "token_type": "MAC",  # Not Bearer
        }
        with pytest.raises(ValueError) as exc_info:
            validate_token_response(tokens, "test-integration")
        assert "Bearer" in str(exc_info.value)


# ==============================================================================
# PKCE Validation Tests
# ==============================================================================


class TestValidatePkceSupport:
    """Tests for validate_pkce_support function."""

    def test_s256_support_passes(self):
        """S256 support should pass."""
        oauth_config = {"code_challenge_methods_supported": ["S256"]}
        validate_pkce_support(oauth_config, "test-integration")

    def test_s256_with_plain_passes(self):
        """S256 with plain support should pass."""
        oauth_config = {"code_challenge_methods_supported": ["plain", "S256"]}
        validate_pkce_support(oauth_config, "test-integration")

    def test_empty_methods_passes(self):
        """Empty/missing methods should pass (assume S256 support)."""
        validate_pkce_support({}, "test-integration")
        validate_pkce_support(
            {"code_challenge_methods_supported": []}, "test-integration"
        )

    def test_plain_only_raises(self):
        """Plain-only PKCE should raise ValueError."""
        oauth_config = {"code_challenge_methods_supported": ["plain"]}
        with pytest.raises(ValueError) as exc_info:
            validate_pkce_support(oauth_config, "test-integration")
        assert "insecure" in str(exc_info.value).lower()

    def test_no_s256_raises(self):
        """No S256 support should raise ValueError."""
        oauth_config = {"code_challenge_methods_supported": ["custom"]}
        with pytest.raises(ValueError) as exc_info:
            validate_pkce_support(oauth_config, "test-integration")
        assert "S256" in str(exc_info.value)


# ==============================================================================
# JWT Issuer Validation Tests
# ==============================================================================


class TestValidateJwtIssuer:
    """Tests for validate_jwt_issuer function."""

    def test_valid_issuer_returns_true(self):
        """Matching issuer should return True."""
        jwt = generate_mock_jwt(issuer=MOCK_AUTH_SERVER_URL)
        result = validate_jwt_issuer(jwt, MOCK_AUTH_SERVER_URL, "test-integration")
        assert result is True

    def test_mismatched_issuer_returns_false(self):
        """Mismatched issuer should return False."""
        jwt = generate_mock_jwt(issuer="https://other.example.com")
        result = validate_jwt_issuer(jwt, MOCK_AUTH_SERVER_URL, "test-integration")
        assert result is False

    def test_non_jwt_returns_true(self):
        """Non-JWT tokens should return True (can't validate)."""
        result = validate_jwt_issuer(
            "opaque-token", MOCK_AUTH_SERVER_URL, "test-integration"
        )
        assert result is True

    def test_malformed_jwt_returns_true(self):
        """Malformed JWT should return True (don't fail)."""
        result = validate_jwt_issuer(
            "invalid.jwt.token", MOCK_AUTH_SERVER_URL, "test-integration"
        )
        assert result is True


# ==============================================================================
# Authorization Server Selection Tests
# ==============================================================================


class TestSelectAuthorizationServer:
    """Tests for select_authorization_server function."""

    @pytest.mark.asyncio
    async def test_single_server_returns_that_server(self):
        """Single server should be returned."""
        result = await select_authorization_server([MOCK_AUTH_SERVER_URL])
        assert result == MOCK_AUTH_SERVER_URL

    @pytest.mark.asyncio
    async def test_multiple_servers_returns_first(self):
        """Multiple servers should return first by default."""
        servers = [MOCK_AUTH_SERVER_URL, "https://backup.example.com"]
        result = await select_authorization_server(servers)
        assert result == MOCK_AUTH_SERVER_URL

    @pytest.mark.asyncio
    async def test_preferred_server_is_selected(self):
        """Preferred server should be selected if available."""
        servers = [MOCK_AUTH_SERVER_URL, "https://preferred.example.com"]
        result = await select_authorization_server(
            servers, preferred_server="https://preferred.example.com"
        )
        assert result == "https://preferred.example.com"

    @pytest.mark.asyncio
    async def test_preferred_server_not_in_list_returns_first(self):
        """Non-existent preferred server should return first."""
        servers = [MOCK_AUTH_SERVER_URL, "https://backup.example.com"]
        result = await select_authorization_server(
            servers, preferred_server="https://nonexistent.example.com"
        )
        assert result == MOCK_AUTH_SERVER_URL

    @pytest.mark.asyncio
    async def test_empty_servers_raises(self):
        """Empty server list should raise OAuthDiscoveryError."""
        with pytest.raises(OAuthDiscoveryError):
            await select_authorization_server([])


# ==============================================================================
# Client Metadata Document URL Tests
# ==============================================================================


class TestGetClientMetadataDocumentUrl:
    """Tests for get_client_metadata_document_url function."""

    def test_generates_correct_url(self):
        """Should generate correct client metadata document URL."""
        result = get_client_metadata_document_url("https://api.example.com")
        assert result == "https://api.example.com/api/v1/oauth/client-metadata.json"

    def test_handles_trailing_slash(self):
        """Should handle trailing slash in base URL."""
        result = get_client_metadata_document_url("https://api.example.com/")
        assert result == "https://api.example.com/api/v1/oauth/client-metadata.json"
