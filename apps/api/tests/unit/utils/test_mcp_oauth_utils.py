"""Unit tests for app.utils.mcp_oauth_utils module.

Tests cover:
- validate_https_url: HTTPS validation, HTTP rejection, localhost exceptions
- is_localhost_url: localhost, loopback addresses, regular domains
- validate_oauth_endpoints: all endpoints valid, one invalid raises error
- extract_auth_challenge: 401 with WWW-Authenticate, non-401, timeout, connect error
- find_protected_resource_metadata: found at first URL, found at second, not found
- fetch_auth_server_metadata: OAuth discovery, OIDC fallback, full fallback
- revoke_token: success, failure, timeout, client auth variants
- validate_token_response: valid, missing access_token, wrong token_type
- validate_pkce_support: S256 present, plain only, none
- validate_jwt_issuer: valid JWT, non-JWT, mismatched issuer, decode error
- parse_oauth_error_response: JSON, non-JSON, parse error
- get_client_metadata_document_url: URL construction
- introspect_token: success, failure, timeout
- select_authorization_server: single, multiple, preferred
"""

import base64
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils.mcp_oauth_utils import (
    MCP_PROTOCOL_VERSION,
    OAuthDiscoveryError,
    OAuthSecurityError,
    TokenOperationError,
    extract_auth_challenge,
    fetch_auth_server_metadata,
    fetch_protected_resource_metadata,
    find_protected_resource_metadata,
    get_client_metadata_document_url,
    introspect_token,
    is_localhost_url,
    parse_oauth_error_response,
    revoke_token,
    select_authorization_server,
    validate_https_url,
    validate_jwt_issuer,
    validate_oauth_endpoints,
    validate_pkce_support,
    validate_token_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    headers: dict[str, str] | None = None,
    json_data: dict[str, Any] | None = None,
    text: str = "",
) -> MagicMock:
    """Create a mock HTTP response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def _build_jwt(payload: dict[str, Any]) -> str:
    """Build a simple unsigned JWT (header.payload.signature)."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode())
        .decode()
        .rstrip("=")
    )
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = base64.urlsafe_b64encode(b"sig").decode().rstrip("=")
    return f"{header}.{body}.{signature}"


# ---------------------------------------------------------------------------
# validate_https_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateHttpsUrl:
    """Tests for validate_https_url — enforces HTTPS with localhost exception."""

    def test_https_url_is_valid(self) -> None:
        # Should not raise
        validate_https_url("https://auth.example.com/oauth")

    def test_http_non_localhost_raises(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("http://auth.example.com/oauth")

    def test_http_localhost_is_valid_by_default(self) -> None:
        validate_https_url("http://localhost:8080/callback")

    def test_http_127_0_0_1_is_valid_by_default(self) -> None:
        validate_https_url("http://127.0.0.1:3000/callback")

    def test_http_ipv6_loopback_is_valid_by_default(self) -> None:
        validate_https_url("http://[::1]:8000/callback")

    def test_http_localhost_disallowed_when_flag_false(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("http://localhost:8080/callback", allow_localhost=False)

    def test_http_127_disallowed_when_flag_false(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("http://127.0.0.1:3000/callback", allow_localhost=False)

    def test_ftp_scheme_raises(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("ftp://example.com/file")

    def test_no_scheme_raises(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("example.com/path")

    def test_http_non_localhost_hostname_raises(self) -> None:
        with pytest.raises(OAuthSecurityError):
            validate_https_url("http://192.168.1.1:8080/callback")


# ---------------------------------------------------------------------------
# is_localhost_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsLocalhostUrl:
    """Tests for is_localhost_url — detects localhost/loopback addresses."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8080/path",
            "http://LOCALHOST:8080/path",
            "http://127.0.0.1:3000",
            "http://127.0.0.255:3000",
            "http://[::1]:8000",
        ],
    )
    def test_localhost_urls(self, url: str) -> None:
        assert is_localhost_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "https://auth.google.com",
            "https://192.168.1.1:443",
            "https://10.0.0.1",
        ],
    )
    def test_non_localhost_urls(self, url: str) -> None:
        assert is_localhost_url(url) is False

    def test_empty_hostname_returns_false(self) -> None:
        # A URL like "file:///path" has no hostname
        assert is_localhost_url("file:///some/path") is False

    def test_malformed_url_returns_false(self) -> None:
        assert is_localhost_url("not a url at all") is False

    def test_0_0_0_0_is_localhost(self) -> None:
        # 0.0.0.0 is "unspecified" / all interfaces — treated as localhost
        assert is_localhost_url("http://0.0.0.0:8000") is True

    def test_ipv6_unspecified_is_localhost(self) -> None:
        assert is_localhost_url("http://[::]:8000") is True


# ---------------------------------------------------------------------------
# validate_oauth_endpoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateOauthEndpoints:
    """Tests for validate_oauth_endpoints — validates all endpoint URLs."""

    def test_all_https_endpoints_valid(self) -> None:
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
        }
        # Should not raise
        validate_oauth_endpoints(config)

    def test_one_http_endpoint_raises(self) -> None:
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "http://auth.example.com/token",  # HTTP!
        }
        with pytest.raises(OAuthSecurityError, match="Invalid token_endpoint"):
            validate_oauth_endpoints(config)

    def test_missing_endpoints_are_skipped(self) -> None:
        config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            # Other endpoints are absent — should not raise
        }
        validate_oauth_endpoints(config)

    def test_empty_config_no_error(self) -> None:
        validate_oauth_endpoints({})

    def test_localhost_endpoints_allowed_by_default(self) -> None:
        config = {
            "authorization_endpoint": "http://localhost:8080/authorize",
            "token_endpoint": "http://127.0.0.1:3000/token",
        }
        validate_oauth_endpoints(config)

    def test_localhost_disallowed_when_flag_false(self) -> None:
        config = {
            "token_endpoint": "http://localhost:8080/token",
        }
        with pytest.raises(OAuthSecurityError, match="Invalid token_endpoint"):
            validate_oauth_endpoints(config, allow_localhost=False)

    def test_all_known_endpoint_keys_validated(self) -> None:
        """Ensure all six endpoint keys defined in the function are checked."""
        for key in [
            "authorization_endpoint",
            "token_endpoint",
            "registration_endpoint",
            "revocation_endpoint",
            "introspection_endpoint",
            "issuer",
        ]:
            config = {key: "http://evil.com/steal"}
            with pytest.raises(OAuthSecurityError, match=f"Invalid {key}"):
                validate_oauth_endpoints(config)


# ---------------------------------------------------------------------------
# extract_auth_challenge
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractAuthChallenge:
    """Tests for extract_auth_challenge — probes MCP server for 401 challenge."""

    async def test_401_with_www_authenticate_parsed(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {
            "WWW-Authenticate": (
                'Bearer resource_metadata="https://res.example.com/.well-known/oauth-protected-resource", '
                'scope="read write"'
            )
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://mcp.example.com")

        assert "resource_metadata" in result
        assert (
            result["resource_metadata"]
            == "https://res.example.com/.well-known/oauth-protected-resource"
        )
        assert result["scope"] == "read write"
        assert "raw" in result

    async def test_401_with_error_fields(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {
            "WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token expired"'
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://mcp.example.com")

        assert result["error"] == "invalid_token"
        assert result["error_description"] == "Token expired"

    async def test_401_without_www_authenticate(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.headers = {}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://mcp.example.com")

        assert result == {"raw": ""}

    async def test_non_401_returns_empty_dict(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://mcp.example.com")

        assert result == {}

    async def test_timeout_returns_empty_dict(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("read timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://slow.example.com")

        assert result == {}

    async def test_connect_error_reraises(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(httpx.ConnectError):
                await extract_auth_challenge("https://down.example.com")

    async def test_generic_exception_returns_empty_dict(self) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RuntimeError("unexpected")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await extract_auth_challenge("https://broken.example.com")

        assert result == {}


# ---------------------------------------------------------------------------
# find_protected_resource_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindProtectedResourceMetadata:
    """Tests for find_protected_resource_metadata — RFC 9728 well-known URIs."""

    async def test_found_at_path_aware_url(self) -> None:
        """First candidate (path-aware) returns valid JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "authorization_servers": ["https://auth.example.com"]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata(
                "https://mcp.example.com/api/v1"
            )

        assert result is not None
        assert "oauth-protected-resource/api/v1" in result

    async def test_found_at_root_url(self) -> None:
        """Path-aware 404, but root URL responds with valid JSON."""
        call_count = 0

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 1:
                # First call (path-aware) fails
                resp.status_code = 404
                resp.json.side_effect = ValueError("Not found")
            else:
                # Second call (root) succeeds
                resp.status_code = 200
                resp.json.return_value = {"resource": "https://mcp.example.com"}
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata(
                "https://mcp.example.com/api/v1"
            )

        assert result is not None
        assert result.endswith("/.well-known/oauth-protected-resource")

    async def test_not_found_returns_none(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.side_effect = ValueError("Not found")

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata(
                "https://mcp.example.com/api"
            )

        assert result is None

    async def test_root_url_no_path_only_one_candidate(self) -> None:
        """When server URL has no path, only the root candidate is tried."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resource": "https://mcp.example.com"}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata("https://mcp.example.com")

        assert result is not None
        mock_client.get.assert_called_once()

    async def test_200_without_expected_keys_skipped(self) -> None:
        """200 response but JSON lacks authorization_servers/resource keys."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"something_else": True}

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata("https://mcp.example.com")

        assert result is None

    async def test_exception_during_fetch_continues(self) -> None:
        """If one candidate throws, the next is still tried."""
        call_count = 0

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timed out")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "authorization_servers": ["https://auth.example.com"]
            }
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await find_protected_resource_metadata(
                "https://mcp.example.com/path"
            )

        # Second candidate should succeed
        assert result is not None


# ---------------------------------------------------------------------------
# fetch_auth_server_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchAuthServerMetadata:
    """Tests for fetch_auth_server_metadata — RFC 8414 discovery with fallback."""

    async def test_found_via_oauth_discovery(self) -> None:
        """First candidate URL returns 200."""
        metadata = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = metadata

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_auth_server_metadata("https://auth.example.com")

        assert result["issuer"] == "https://auth.example.com"
        assert "fallback" not in result

    async def test_found_via_oidc_discovery(self) -> None:
        """OAuth URL 404s, OIDC URL returns 200."""
        call_count = 0
        oidc_metadata = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
        }

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if "openid-configuration" in url:
                resp.status_code = 200
                resp.json.return_value = oidc_metadata
            else:
                resp.status_code = 404
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_auth_server_metadata("https://auth.example.com")

        assert result["issuer"] == "https://auth.example.com"

    async def test_all_fail_returns_fallback(self) -> None:
        """All discovery URLs fail — returns fallback URLs."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_auth_server_metadata("https://auth.example.com")

        assert result["fallback"] is True
        assert result["authorization_endpoint"] == "https://auth.example.com/authorize"
        assert result["token_endpoint"] == "https://auth.example.com/token"
        assert result["registration_endpoint"] == "https://auth.example.com/register"
        assert result["issuer"] == "https://auth.example.com"

    async def test_path_in_url_generates_path_aware_candidates(self) -> None:
        """Auth server URL with path generates path-aware discovery URLs."""
        urls_tried: list[str] = []

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            urls_tried.append(url)
            resp = MagicMock()
            resp.status_code = 404
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await fetch_auth_server_metadata("https://auth.example.com/tenant1")

        # Should try path-aware OAuth and OIDC first
        assert any("/oauth-authorization-server/tenant1" in u for u in urls_tried)
        assert any("/openid-configuration/tenant1" in u for u in urls_tried)
        # Also appended OIDC
        assert any("tenant1/.well-known/openid-configuration" in u for u in urls_tried)

    async def test_exception_during_discovery_continues(self) -> None:
        """Network errors on one candidate don't prevent trying the next."""
        call_count = 0

        async def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise httpx.ConnectError("refused")
            resp = MagicMock()
            resp.status_code = 404
            return resp

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_auth_server_metadata("https://auth.example.com")

        # Should still return fallback (all failed)
        assert result["fallback"] is True

    async def test_fallback_uses_origin_only(self) -> None:
        """Fallback URLs use origin (no path), per MCP spec 2025-03-26."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_auth_server_metadata(
                "https://server.smithery.ai/excalidraw"
            )

        # Fallback should use origin only, NOT include /excalidraw
        assert result["token_endpoint"] == "https://server.smithery.ai/token"
        assert (
            result["authorization_endpoint"] == "https://server.smithery.ai/authorize"
        )


# ---------------------------------------------------------------------------
# revoke_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRevokeToken:
    """Tests for revoke_token — RFC 7009 token revocation."""

    async def test_success_returns_true(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
            )

        assert result is True

    async def test_non_200_returns_false(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
            )

        assert result is False

    async def test_timeout_returns_false(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
            )

        assert result is False

    async def test_generic_exception_returns_false(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("network down")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
            )

        assert result is False

    async def test_with_client_secret_uses_basic_auth(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
                client_id="my_client",
                client_secret="my_secret",  # pragma: allowlist secret
            )

        # Verify Basic auth header was set
        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "Authorization" in headers
        expected_creds = base64.b64encode(b"my_client:my_secret").decode()
        assert headers["Authorization"] == f"Basic {expected_creds}"
        # client_id should NOT be in the form data
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
        assert "client_id" not in data

    async def test_with_client_id_no_secret_includes_in_body(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await revoke_token(
                "https://auth.example.com/revoke",
                token="test_token",
                client_id="public_client",
            )

        call_kwargs = mock_client.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
        assert data["client_id"] == "public_client"
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "Authorization" not in headers

    async def test_http_endpoint_raises_security_error(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            await revoke_token(
                "http://evil.com/revoke",
                token="test_token",
            )

    async def test_token_type_hint_passed_in_body(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await revoke_token(
                "https://auth.example.com/revoke",
                token="my_refresh",
                token_type_hint="refresh_token",
            )

        call_kwargs = mock_client.post.call_args
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data", {})
        assert data["token_type_hint"] == "refresh_token"


# ---------------------------------------------------------------------------
# introspect_token
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntrospectToken:
    """Tests for introspect_token — RFC 7662 token introspection."""

    async def test_success_returns_dict(self) -> None:
        introspection_data = {"active": True, "scope": "read write", "sub": "user123"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = introspection_data

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await introspect_token(
                "https://auth.example.com/introspect",
                token="test_token",
            )

        assert result is not None
        assert result["active"] is True
        assert result["scope"] == "read write"

    async def test_non_200_returns_none(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "unauthorized"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await introspect_token(
                "https://auth.example.com/introspect",
                token="test_token",
            )

        assert result is None

    async def test_timeout_returns_none(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await introspect_token(
                "https://auth.example.com/introspect",
                token="test_token",
            )

        assert result is None

    async def test_generic_exception_returns_none(self) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("broken")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await introspect_token(
                "https://auth.example.com/introspect",
                token="test_token",
            )

        assert result is None

    async def test_http_endpoint_raises_security_error(self) -> None:
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            await introspect_token(
                "http://evil.com/introspect",
                token="test_token",
            )

    async def test_with_client_secret_uses_basic_auth(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"active": True}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await introspect_token(
                "https://auth.example.com/introspect",
                token="test_token",
                client_id="my_client",
                client_secret="my_secret",  # pragma: allowlist secret
            )

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        expected_creds = base64.b64encode(b"my_client:my_secret").decode()
        assert headers["Authorization"] == f"Basic {expected_creds}"


# ---------------------------------------------------------------------------
# parse_oauth_error_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseOauthErrorResponse:
    """Tests for parse_oauth_error_response — RFC 6749 Section 5.2 error parsing."""

    def test_json_response_with_all_fields(self) -> None:
        response = _make_response(
            status_code=400,
            headers={"content-type": "application/json"},
            json_data={
                "error": "invalid_grant",
                "error_description": "The authorization code has expired",
                "error_uri": "https://docs.example.com/errors/invalid_grant",
            },
        )
        result = parse_oauth_error_response(response)

        assert result["error"] == "invalid_grant"
        assert result["error_description"] == "The authorization code has expired"
        assert result["error_uri"] == "https://docs.example.com/errors/invalid_grant"
        assert result["status_code"] == 400

    def test_json_response_minimal(self) -> None:
        response = _make_response(
            status_code=400,
            headers={"content-type": "application/json; charset=utf-8"},
            json_data={"error": "unauthorized_client"},
        )
        result = parse_oauth_error_response(response)

        assert result["error"] == "unauthorized_client"
        assert result["error_description"] is None
        assert result["error_uri"] is None

    def test_non_json_content_type_but_json_body(self) -> None:
        """Response without JSON content-type but body is valid JSON."""
        response = _make_response(
            status_code=400,
            headers={"content-type": "text/html"},
            json_data={
                "error": "server_error",
                "error_description": "Internal failure",
            },
        )
        result = parse_oauth_error_response(response)

        assert result["error"] == "server_error"
        assert result["error_description"] == "Internal failure"

    def test_non_json_content_type_non_json_body(self) -> None:
        """Non-JSON content type and body can't be parsed as JSON either."""
        response = _make_response(
            status_code=502,
            headers={"content-type": "text/plain"},
            text="Bad Gateway",
        )
        result = parse_oauth_error_response(response)

        assert result["error"] == "unknown_error"
        assert result["error_description"] == "Bad Gateway"
        assert result["status_code"] == 502

    def test_long_text_truncated(self) -> None:
        """Non-JSON text longer than 500 chars is truncated."""
        long_text = "A" * 1000
        response = _make_response(
            status_code=500,
            headers={"content-type": "text/plain"},
            text=long_text,
        )
        result = parse_oauth_error_response(response)

        assert len(result["error_description"]) == 500

    def test_json_parse_error_in_outer_try(self) -> None:
        """Top-level json() raises even with JSON content-type."""
        response = MagicMock()
        response.status_code = 400
        response.headers = {"content-type": "application/json"}
        response.json.side_effect = RuntimeError("Corrupted JSON")
        response.text = "garbage data"

        result = parse_oauth_error_response(response)

        # Falls into outer except
        assert result["error"] == "unknown_error"
        assert "Corrupted JSON" in str(result["error_description"])

    def test_empty_json_data(self) -> None:
        response = _make_response(
            status_code=400,
            headers={"content-type": "application/json"},
            json_data={},
        )
        result = parse_oauth_error_response(response)

        assert result["error"] == "unknown_error"
        assert result["error_description"] is None


# ---------------------------------------------------------------------------
# validate_token_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateTokenResponse:
    """Tests for validate_token_response — OAuth 2.1 token response validation."""

    def test_valid_response(self) -> None:
        tokens = {
            "access_token": "eyJhbGciOi...",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        # Should not raise
        validate_token_response(tokens, "test-integration")

    def test_bearer_case_insensitive(self) -> None:
        tokens = {
            "access_token": "eyJhbGciOi...",
            "token_type": "bearer",
        }
        # lowercase "bearer" should be accepted
        validate_token_response(tokens, "test-integration")

    def test_missing_access_token_raises(self) -> None:
        tokens = {"token_type": "Bearer"}
        with pytest.raises(ValueError, match="missing required 'access_token'"):
            validate_token_response(tokens, "test-integration")

    def test_empty_access_token_raises(self) -> None:
        tokens = {"access_token": "", "token_type": "Bearer"}
        with pytest.raises(ValueError, match="missing required 'access_token'"):
            validate_token_response(tokens, "test-integration")

    def test_missing_token_type_raises(self) -> None:
        tokens = {"access_token": "eyJhbGciOi..."}
        with pytest.raises(ValueError, match="missing required 'token_type'"):
            validate_token_response(tokens, "test-integration")

    def test_empty_token_type_raises(self) -> None:
        tokens = {"access_token": "eyJhbGciOi...", "token_type": ""}
        with pytest.raises(ValueError, match="missing required 'token_type'"):
            validate_token_response(tokens, "test-integration")

    def test_wrong_token_type_raises(self) -> None:
        tokens = {"access_token": "token123", "token_type": "MAC"}
        with pytest.raises(ValueError, match="Unsupported token_type 'MAC'"):
            validate_token_response(tokens, "test-integration")

    def test_none_access_token_raises(self) -> None:
        tokens = {"access_token": None, "token_type": "Bearer"}
        with pytest.raises(ValueError, match="missing required 'access_token'"):
            validate_token_response(tokens, "test-integration")


# ---------------------------------------------------------------------------
# validate_pkce_support
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatePkceSupport:
    """Tests for validate_pkce_support — MCP PKCE requirement checking."""

    def test_s256_present_passes(self) -> None:
        config = {"code_challenge_methods_supported": ["S256"]}
        # Should not raise
        validate_pkce_support(config, "test-integration")

    def test_s256_among_multiple_passes(self) -> None:
        config = {"code_challenge_methods_supported": ["plain", "S256"]}
        validate_pkce_support(config, "test-integration")

    def test_empty_list_raises(self) -> None:
        config: dict[str, object] = {"code_challenge_methods_supported": []}
        with pytest.raises(ValueError, match="does not advertise PKCE support"):
            validate_pkce_support(config, "test-integration")

    def test_missing_key_raises(self) -> None:
        config: dict[str, object] = {}
        with pytest.raises(ValueError, match="does not advertise PKCE support"):
            validate_pkce_support(config, "test-integration")

    def test_only_plain_raises_insecure(self) -> None:
        config = {"code_challenge_methods_supported": ["plain"]}
        with pytest.raises(ValueError, match="insecure"):
            validate_pkce_support(config, "test-integration")

    def test_unsupported_method_without_plain_raises(self) -> None:
        config = {"code_challenge_methods_supported": ["custom_method"]}
        with pytest.raises(ValueError, match="does not support S256"):
            validate_pkce_support(config, "test-integration")

    def test_none_value_raises(self) -> None:
        config = {"code_challenge_methods_supported": None}
        with pytest.raises(ValueError, match="does not advertise PKCE support"):
            validate_pkce_support(config, "test-integration")


# ---------------------------------------------------------------------------
# validate_jwt_issuer
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateJwtIssuer:
    """Tests for validate_jwt_issuer — JWT issuer claim validation."""

    def test_valid_jwt_matching_issuer(self) -> None:
        token = _build_jwt({"iss": "https://auth.example.com", "sub": "user1"})
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        assert result is True

    def test_matching_issuer_with_trailing_slash_normalization(self) -> None:
        token = _build_jwt({"iss": "https://auth.example.com/"})
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        assert result is True

    def test_mismatched_issuer(self) -> None:
        token = _build_jwt({"iss": "https://evil.example.com"})
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        assert result is False

    def test_non_jwt_returns_true(self) -> None:
        # Not a JWT (not 3 dot-separated parts)
        result = validate_jwt_issuer(
            "opaque_token_abc", "https://auth.example.com", "test-int"
        )
        assert result is True

    def test_two_part_token_returns_true(self) -> None:
        result = validate_jwt_issuer(
            "part1.part2", "https://auth.example.com", "test-int"
        )
        assert result is True

    def test_four_part_token_returns_true(self) -> None:
        result = validate_jwt_issuer("a.b.c.d", "https://auth.example.com", "test-int")
        assert result is True

    def test_jwt_without_iss_claim_returns_true(self) -> None:
        token = _build_jwt({"sub": "user1", "exp": 9999999999})
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        assert result is True

    def test_corrupted_base64_payload_returns_true(self) -> None:
        # Valid 3 parts but payload is not valid base64/JSON
        token = "header.!!!invalid_base64!!!.signature"
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        # Should catch exception and return True (non-critical)
        assert result is True

    def test_payload_not_json_returns_true(self) -> None:
        # Valid base64 but not JSON
        payload = base64.urlsafe_b64encode(b"not json at all").decode().rstrip("=")
        token = f"header.{payload}.signature"
        result = validate_jwt_issuer(token, "https://auth.example.com", "test-int")
        assert result is True


# ---------------------------------------------------------------------------
# get_client_metadata_document_url
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetClientMetadataDocumentUrl:
    """Tests for get_client_metadata_document_url."""

    def test_basic_url(self) -> None:
        result = get_client_metadata_document_url("https://api.heygaia.com")
        assert result == "https://api.heygaia.com/api/v1/oauth/client-metadata.json"

    def test_trailing_slash_stripped(self) -> None:
        result = get_client_metadata_document_url("https://api.heygaia.com/")
        assert result == "https://api.heygaia.com/api/v1/oauth/client-metadata.json"

    def test_multiple_trailing_slashes(self) -> None:
        result = get_client_metadata_document_url("https://api.heygaia.com///")
        # rstrip('/') removes all trailing slashes
        assert result.endswith("/api/v1/oauth/client-metadata.json")


# ---------------------------------------------------------------------------
# select_authorization_server
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSelectAuthorizationServer:
    """Tests for select_authorization_server — MCP server selection."""

    async def test_single_server_returned(self) -> None:
        result = await select_authorization_server(["https://auth.example.com"])
        assert result == "https://auth.example.com"

    async def test_empty_list_raises(self) -> None:
        with pytest.raises(OAuthDiscoveryError, match="No authorization servers"):
            await select_authorization_server([])

    async def test_preferred_server_selected(self) -> None:
        servers = ["https://auth1.example.com", "https://auth2.example.com"]
        result = await select_authorization_server(
            servers, preferred_server="https://auth2.example.com"
        )
        assert result == "https://auth2.example.com"

    async def test_preferred_not_in_list_uses_first(self) -> None:
        servers = ["https://auth1.example.com", "https://auth2.example.com"]
        result = await select_authorization_server(
            servers, preferred_server="https://unknown.example.com"
        )
        assert result == "https://auth1.example.com"

    async def test_multiple_servers_no_preference_uses_first(self) -> None:
        servers = ["https://first.example.com", "https://second.example.com"]
        result = await select_authorization_server(servers)
        assert result == "https://first.example.com"


# ---------------------------------------------------------------------------
# fetch_protected_resource_metadata
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchProtectedResourceMetadata:
    """Tests for fetch_protected_resource_metadata — RFC 9728 metadata fetch."""

    async def test_successful_fetch(self) -> None:
        prm_data = {
            "resource": "https://mcp.example.com",
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["read", "write"],
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = prm_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            result = await fetch_protected_resource_metadata(
                "https://mcp.example.com/.well-known/oauth-protected-resource"
            )

        assert result["resource"] == "https://mcp.example.com"
        assert "authorization_servers" in result

    async def test_http_error_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await fetch_protected_resource_metadata(
                    "https://mcp.example.com/.well-known/oauth-protected-resource"
                )

    async def test_includes_mcp_protocol_version_header(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"resource": "test"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.utils.mcp_oauth_utils.httpx.AsyncClient", return_value=mock_client
        ):
            await fetch_protected_resource_metadata(
                "https://example.com/.well-known/oauth-protected-resource"
            )

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["MCP-Protocol-Version"] == MCP_PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstants:
    """Verify module-level constants."""

    def test_mcp_protocol_version_is_string(self) -> None:
        assert isinstance(MCP_PROTOCOL_VERSION, str)
        assert len(MCP_PROTOCOL_VERSION) > 0

    def test_exception_classes_exist(self) -> None:
        assert issubclass(OAuthSecurityError, Exception)
        assert issubclass(OAuthDiscoveryError, Exception)
        assert issubclass(TokenOperationError, Exception)
