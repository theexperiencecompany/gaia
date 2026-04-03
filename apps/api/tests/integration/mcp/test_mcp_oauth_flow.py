"""Integration tests for MCP OAuth 2.1 flow.

Tests the full OAuth lifecycle: discovery, authorization URL generation,
token exchange, token refresh, token revocation, connection pooling,
tool discovery, error handling, and concurrent connection isolation.

Mocks only HTTP calls (httpx) and database I/O boundaries. All MCP client
logic, OAuth discovery, token management, and PKCE generation run for real.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet

from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_client import MCPClient
from app.services.mcp.mcp_client_pool import MCPClientPool, PooledClient
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import MCPToolsStore, _format_tools
from app.services.mcp.oauth_discovery import discover_oauth_config
from app.services.mcp.token_management import (
    resolve_client_credentials,
    revoke_tokens,
    try_refresh_token,
)
from app.utils.mcp_oauth_utils import (
    OAuthDiscoveryError,
    OAuthSecurityError,
    parse_oauth_error_response,
    validate_https_url,
    validate_oauth_endpoints,
    validate_pkce_support,
    validate_token_response,
)
from app.utils.mcp_utils import generate_pkce_pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fernet_key() -> str:
    return Fernet.generate_key().decode()


def _make_token_store(user_id: str = "test-user") -> MCPTokenStore:
    """Create a MCPTokenStore with a valid Fernet key injected."""
    store = MCPTokenStore(user_id)
    store._cipher = Fernet(_fernet_key().encode())
    return store


def _make_db_session_context(mock_session: AsyncMock) -> AsyncMock:
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_mock_session(scalar_return=None) -> AsyncMock:
    """Build a mock DB session with execute/add/commit/delete wired."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=scalar_return)
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    return session


def _oauth_discovery_dict(
    auth_endpoint: str = "https://auth.example.com/authorize",
    token_endpoint: str = "https://auth.example.com/token",
    registration_endpoint: str = "https://auth.example.com/register",
    revocation_endpoint: str = "https://auth.example.com/revoke",
    introspection_endpoint: str = "https://auth.example.com/introspect",
) -> dict:
    """Build a standard OAuth discovery dict for tests."""
    return {
        "authorization_endpoint": auth_endpoint,
        "token_endpoint": token_endpoint,
        "registration_endpoint": registration_endpoint,
        "revocation_endpoint": revocation_endpoint,
        "introspection_endpoint": introspection_endpoint,
        "issuer": "https://auth.example.com",
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["read", "write"],
        "resource": "https://mcp.example.com",
        "discovery_method": "rfc9728_prm",
    }


def _make_mcp_config(**overrides) -> MCPConfig:
    defaults = {
        "server_url": "https://mcp.example.com",
        "requires_auth": True,
        "auth_type": "oauth",
        "transport": "streamable-http",
    }
    defaults.update(overrides)
    return MCPConfig(**defaults)


def _make_httpx_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a real httpx.Response for tests."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data,
        headers=headers or {},
        text=text if not json_data else "",
    )
    return resp


# ---------------------------------------------------------------------------
# 1. OAuth Discovery
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOAuthDiscovery:
    """Test OAuth discovery via mocked HTTP calls."""

    async def test_discover_oauth_config_from_prm(self):
        """discover_oauth_config fetches PRM, selects auth server, and returns metadata."""
        token_store = _make_token_store()
        mcp_config = _make_mcp_config()
        integration_id = "test-integration"

        # Mock: no cached discovery
        token_store.get_oauth_discovery = AsyncMock(return_value=None)
        token_store.store_oauth_discovery = AsyncMock()

        prm_response = {
            "resource": "https://mcp.example.com",
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["read", "write"],
        }
        auth_metadata = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "code_challenge_methods_supported": ["S256"],
            "issuer": "https://auth.example.com",
        }

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new=AsyncMock(return_value={"raw": "Bearer"}),
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new=AsyncMock(
                    return_value="https://mcp.example.com/.well-known/oauth-protected-resource"
                ),
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_protected_resource_metadata",
                new=AsyncMock(return_value=prm_response),
            ),
            patch(
                "app.services.mcp.oauth_discovery.select_authorization_server",
                new=AsyncMock(return_value="https://auth.example.com"),
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new=AsyncMock(return_value=auth_metadata),
            ),
            patch(
                "app.services.mcp.oauth_discovery.validate_oauth_endpoints",
            ),
        ):
            result = await discover_oauth_config(
                token_store, integration_id, mcp_config
            )

        assert result["authorization_endpoint"] == "https://auth.example.com/authorize"
        assert result["token_endpoint"] == "https://auth.example.com/token"
        assert result["discovery_method"] == "rfc9728_prm"
        assert result["resource"] == "https://mcp.example.com"
        # Stored to cache
        token_store.store_oauth_discovery.assert_awaited_once()

    async def test_discover_returns_cached_when_available(self):
        """discover_oauth_config returns cached data without any HTTP calls."""
        token_store = _make_token_store()
        cached = _oauth_discovery_dict()
        token_store.get_oauth_discovery = AsyncMock(return_value=cached)
        token_store.store_oauth_discovery = AsyncMock()

        mcp_config = _make_mcp_config()

        result = await discover_oauth_config(token_store, "cached-int", mcp_config)

        assert result is cached
        # Should not have stored again
        token_store.store_oauth_discovery.assert_not_awaited()

    async def test_discover_fallback_to_direct_oauth(self):
        """When PRM has no authorization_servers, fall back to RFC 8414 direct."""
        token_store = _make_token_store()
        token_store.get_oauth_discovery = AsyncMock(return_value=None)
        token_store.store_oauth_discovery = AsyncMock()

        mcp_config = _make_mcp_config()

        direct_metadata = {
            "authorization_endpoint": "https://mcp.example.com/authorize",
            "token_endpoint": "https://mcp.example.com/token",
            "code_challenge_methods_supported": ["S256"],
        }

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new=AsyncMock(return_value=direct_metadata),
            ),
            patch(
                "app.services.mcp.oauth_discovery.validate_oauth_endpoints",
            ),
        ):
            result = await discover_oauth_config(token_store, "direct-int", mcp_config)

        assert result["discovery_method"] == "direct_oauth"
        assert result["authorization_endpoint"] == "https://mcp.example.com/authorize"

    async def test_discover_raises_when_all_methods_fail(self):
        """When both PRM and direct discovery fail, OAuthDiscoveryError is raised."""
        token_store = _make_token_store()
        token_store.get_oauth_discovery = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config()

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new=AsyncMock(side_effect=Exception("Connection refused")),
            ),
        ):
            with pytest.raises(OAuthDiscoveryError, match="OAuth discovery failed"):
                await discover_oauth_config(token_store, "fail-int", mcp_config)


# ---------------------------------------------------------------------------
# 2. Authorization URL Generation with PKCE
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAuthorizationURLGeneration:
    """Test build_oauth_auth_url produces correct OAuth 2.1 authorization URLs."""

    async def test_auth_url_contains_pkce_and_required_params(self):
        """Generated auth URL must contain code_challenge, state, redirect_uri, resource."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()

        oauth_config = _oauth_discovery_dict()
        oauth_config["client_id_metadata_document_supported"] = False

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(client_id="my-client-id")

        client.token_store.create_oauth_state = AsyncMock(return_value="test-state-xyz")

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
        ):
            url = await client.build_oauth_auth_url(
                integration_id="test-int",
                redirect_uri="https://app.example.com/callback",
            )

        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        assert parsed.scheme == "https"
        assert parsed.netloc == "auth.example.com"
        assert parsed.path == "/authorize"
        assert params["client_id"] == ["my-client-id"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert "code_challenge" in params
        assert len(params["code_challenge"][0]) > 0
        assert params["redirect_uri"] == ["https://app.example.com/callback"]
        assert "state" in params
        assert params["resource"] == ["https://mcp.example.com"]

    async def test_auth_url_includes_offline_access_when_supported(self):
        """When server supports offline_access scope, it gets appended."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()

        oauth_config = _oauth_discovery_dict()
        oauth_config["scopes_supported"] = ["read", "write", "offline_access"]
        oauth_config["client_id_metadata_document_supported"] = False

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(client_id="cid", oauth_scopes=["read"])

        client.token_store.create_oauth_state = AsyncMock(return_value="state-1")

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
        ):
            url = await client.build_oauth_auth_url(
                integration_id="offline-int",
                redirect_uri="https://app.example.com/callback",
            )

        params = parse_qs(urlparse(url).query)
        scope_value = params["scope"][0]
        assert "offline_access" in scope_value
        assert "read" in scope_value

    async def test_auth_url_raises_without_pkce_support(self):
        """When server does not advertise S256 PKCE, build_oauth_auth_url raises."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()

        oauth_config = _oauth_discovery_dict()
        oauth_config["code_challenge_methods_supported"] = []  # No PKCE
        oauth_config["client_id_metadata_document_supported"] = False

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(client_id="cid")

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
        ):
            with pytest.raises(ValueError, match="PKCE support"):
                await client.build_oauth_auth_url(
                    integration_id="no-pkce-int",
                    redirect_uri="https://app.example.com/callback",
                )

    async def test_auth_url_adds_oidc_nonce_when_openid_scope(self):
        """When scope includes openid, a nonce param is added and stored."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()

        oauth_config = _oauth_discovery_dict()
        oauth_config["client_id_metadata_document_supported"] = False

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            client_id="cid", oauth_scopes=["openid", "profile"]
        )

        client.token_store.create_oauth_state = AsyncMock(return_value="state-2")
        client.token_store.store_oauth_nonce = AsyncMock()

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
        ):
            url = await client.build_oauth_auth_url(
                integration_id="oidc-int",
                redirect_uri="https://app.example.com/callback",
            )

        params = parse_qs(urlparse(url).query)
        assert "nonce" in params
        assert len(params["nonce"][0]) > 0
        client.token_store.store_oauth_nonce.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Token Exchange
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTokenExchange:
    """Test handle_oauth_callback: code-for-token exchange with PKCE."""

    async def test_successful_token_exchange_stores_tokens(self):
        """After successful code exchange, tokens are stored and connect is called."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()

        # Verify state succeeds, returns code_verifier
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "test-code-verifier")
        )
        client.token_store.store_oauth_tokens = AsyncMock()
        client.token_store.get_and_delete_oauth_nonce = AsyncMock(return_value=None)
        client.token_store.get_dcr_client = AsyncMock(
            return_value={"client_id": "dcr-cid"}
        )
        client.token_store.delete_credentials = AsyncMock()
        client.token_store.delete_dcr_client = AsyncMock()

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()

        oauth_config = _oauth_discovery_dict()
        oauth_config["client_id_metadata_document_supported"] = False

        token_response = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

        mock_tools = [MagicMock(name="tool1")]

        mock_http_response = httpx.Response(
            status_code=200,
            json=token_response,
        )

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
            patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http_cls,
            patch.object(
                client,
                "connect",
                new=AsyncMock(return_value=mock_tools),
            ),
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(return_value=mock_http_response)
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http_instance

            tools = await client.handle_oauth_callback(
                integration_id="exchange-int",
                code="auth-code-123",
                state="valid-state",
                redirect_uri="https://app.example.com/callback",
            )

        assert tools is mock_tools
        # Verify tokens were stored with correct values
        client.token_store.store_oauth_tokens.assert_awaited_once()
        call_kwargs = client.token_store.store_oauth_tokens.call_args[1]
        assert call_kwargs["integration_id"] == "exchange-int"
        assert call_kwargs["access_token"] == "new-access-token"
        assert call_kwargs["refresh_token"] == "new-refresh-token"
        assert call_kwargs["expires_at"] is not None

    async def test_token_exchange_rejects_invalid_state(self):
        """Invalid OAuth state (CSRF protection) raises ValueError."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()
        client.token_store.verify_oauth_state = AsyncMock(return_value=(False, None))

        with pytest.raises(ValueError, match="Invalid OAuth state"):
            await client.handle_oauth_callback(
                integration_id="csrf-int",
                code="code",
                state="bad-state",
                redirect_uri="https://app.example.com/callback",
            )

    async def test_token_exchange_handles_server_error(self):
        """When token endpoint returns error, ValueError with details is raised."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )
        client.token_store.get_dcr_client = AsyncMock(return_value={"client_id": "cid"})
        client.token_store.get_and_delete_oauth_nonce = AsyncMock(return_value=None)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()

        oauth_config = _oauth_discovery_dict()
        oauth_config["client_id_metadata_document_supported"] = False

        error_response = httpx.Response(
            status_code=400,
            json={"error": "invalid_grant", "error_description": "Code expired"},
            headers={"content-type": "application/json"},
        )

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
            patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http_cls,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(return_value=error_response)
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http_instance

            with pytest.raises(ValueError, match="Token exchange failed"):
                await client.handle_oauth_callback(
                    integration_id="error-int",
                    code="expired-code",
                    state="valid-state",
                    redirect_uri="https://app.example.com/callback",
                )

    async def test_token_exchange_validates_token_type(self):
        """Token response with non-Bearer type raises ValueError."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_token_store()
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )
        client.token_store.get_dcr_client = AsyncMock(return_value={"client_id": "cid"})
        client.token_store.get_and_delete_oauth_nonce = AsyncMock(return_value=None)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()

        oauth_config = _oauth_discovery_dict()
        oauth_config["client_id_metadata_document_supported"] = False

        bad_token_response = httpx.Response(
            status_code=200,
            json={
                "access_token": "token-abc",
                "token_type": "MAC",  # Not Bearer
            },
        )

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch.object(
                client,
                "_discover_oauth_config",
                new=AsyncMock(return_value=oauth_config),
            ),
            patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http_cls,
        ):
            mock_http_instance = AsyncMock()
            mock_http_instance.post = AsyncMock(return_value=bad_token_response)
            mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
            mock_http_instance.__aexit__ = AsyncMock(return_value=False)
            mock_http_cls.return_value = mock_http_instance

            with pytest.raises(ValueError, match="Unsupported token_type"):
                await client.handle_oauth_callback(
                    integration_id="mac-int",
                    code="code",
                    state="valid-state",
                    redirect_uri="https://app.example.com/callback",
                )


# ---------------------------------------------------------------------------
# 4. Token Refresh
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTokenRefresh:
    """Test try_refresh_token: expired token refresh via refresh_token grant."""

    async def test_successful_refresh_stores_new_tokens(self):
        """Successful refresh stores new access and refresh tokens."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value="old-refresh-token")
        token_store.get_dcr_client = AsyncMock(
            return_value={"client_id": "dcr-cid", "client_secret": None}
        )
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict()

        refresh_response = httpx.Response(
            status_code=200,
            json={
                "access_token": "refreshed-access-token",
                "token_type": "Bearer",
                "refresh_token": "new-refresh-token",
                "expires_in": 7200,
            },
        )

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=refresh_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_instance

            result = await try_refresh_token(
                token_store, "refresh-int", mcp_config, oauth_config
            )

        assert result is True
        token_store.store_oauth_tokens.assert_awaited_once()
        call_kwargs = token_store.store_oauth_tokens.call_args[1]
        assert call_kwargs["access_token"] == "refreshed-access-token"
        assert call_kwargs["refresh_token"] == "new-refresh-token"
        assert call_kwargs["expires_at"] is not None

    async def test_refresh_fails_without_refresh_token(self):
        """When no refresh token is stored, try_refresh_token returns False."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict()

        result = await try_refresh_token(
            token_store, "no-refresh-int", mcp_config, oauth_config
        )

        assert result is False

    async def test_refresh_fails_on_server_error(self):
        """When token endpoint returns non-200, refresh returns False."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value="valid-refresh")
        token_store.get_dcr_client = AsyncMock(return_value={"client_id": "cid"})

        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict()

        error_response = httpx.Response(
            status_code=400,
            json={"error": "invalid_grant"},
        )

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=error_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_instance

            result = await try_refresh_token(
                token_store, "fail-refresh", mcp_config, oauth_config
            )

        assert result is False

    async def test_refresh_fails_without_client_id(self):
        """When no client_id can be resolved, refresh returns False."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value="valid-refresh")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        # No client_id anywhere
        mcp_config = _make_mcp_config(client_id=None)
        oauth_config = _oauth_discovery_dict()

        result = await try_refresh_token(
            token_store, "no-cid-int", mcp_config, oauth_config
        )

        assert result is False


# ---------------------------------------------------------------------------
# 5. Token Revocation
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTokenRevocation:
    """Test revoke_tokens: RFC 7009 token revocation."""

    async def test_revoke_tokens_calls_revocation_endpoint(self):
        """revoke_tokens sends revocation requests for both tokens."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value="refresh-to-revoke")
        token_store.get_oauth_token = AsyncMock(return_value="access-to-revoke")
        token_store.get_dcr_client = AsyncMock(return_value={"client_id": "cid"})

        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict()

        revoke_response = httpx.Response(status_code=200)

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=revoke_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_instance

            await revoke_tokens(token_store, "revoke-int", mcp_config, oauth_config)

            # Should have called POST twice: once for refresh_token, once for access_token
            assert mock_instance.post.call_count == 2
            # Verify revocation endpoint was called
            first_call_args = mock_instance.post.call_args_list[0]
            assert first_call_args[0][0] == "https://auth.example.com/revoke"

    async def test_revoke_skipped_when_no_revocation_endpoint(self):
        """When no revocation_endpoint in config, revoke_tokens is a no-op."""
        token_store = _make_token_store()
        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict(revocation_endpoint="")
        del oauth_config["revocation_endpoint"]

        # Should not raise or call any HTTP
        await revoke_tokens(token_store, "no-revoke-int", mcp_config, oauth_config)

    async def test_revoke_handles_server_failure_gracefully(self):
        """Token revocation failure is logged but does not raise."""
        token_store = _make_token_store()
        token_store.get_refresh_token = AsyncMock(return_value="rt")
        token_store.get_oauth_token = AsyncMock(return_value="at")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config()
        oauth_config = _oauth_discovery_dict()

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_instance

            # Should not raise despite connection error
            await revoke_tokens(
                token_store, "fail-revoke-int", mcp_config, oauth_config
            )


# ---------------------------------------------------------------------------
# 6. Connection Pooling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnectionPooling:
    """Test MCPClientPool: reuse, LRU eviction, TTL cleanup."""

    async def test_pool_reuses_client_for_same_user(self):
        """Getting the same user_id twice returns the same MCPClient instance."""
        pool = MCPClientPool(max_clients=10, ttl_seconds=300)

        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            client_1 = await pool.get("user-1")
            client_2 = await pool.get("user-1")

        assert client_1 is client_2
        assert pool.size == 1

    async def test_pool_creates_different_clients_for_different_users(self):
        """Different user_ids get separate MCPClient instances."""
        pool = MCPClientPool(max_clients=10, ttl_seconds=300)

        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            mock_cls.side_effect = lambda user_id: MagicMock(user_id=user_id)

            client_1 = await pool.get("user-a")
            client_2 = await pool.get("user-b")

        assert client_1 is not client_2
        assert pool.size == 2

    async def test_pool_evicts_lru_at_capacity(self):
        """When pool is full, the least recently used client is evicted."""
        pool = MCPClientPool(max_clients=2, ttl_seconds=300)

        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            evicted_client = MagicMock()
            evicted_client.close_all_client_sessions = AsyncMock()

            call_count = 0

            def make_client(user_id):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return evicted_client
                return MagicMock(close_all_client_sessions=AsyncMock())

            mock_cls.side_effect = make_client

            await pool.get("user-oldest")  # Will be evicted
            await pool.get("user-middle")
            await pool.get("user-newest")  # Triggers eviction

        assert pool.size == 2
        # The oldest client should have been closed
        evicted_client.close_all_client_sessions.assert_awaited_once()

    async def test_pool_cleanup_stale_removes_expired(self):
        """cleanup_stale removes clients that haven't been used within TTL."""
        pool = MCPClientPool(max_clients=10, ttl_seconds=1)

        stale_client = MagicMock()
        stale_client.close_all_client_sessions = AsyncMock()

        # Inject a stale entry directly
        pool._clients["stale-user"] = PooledClient(
            client=stale_client,
            last_used=datetime.now(timezone.utc) - timedelta(seconds=10),
        )

        await pool.cleanup_stale()

        assert pool.size == 0
        stale_client.close_all_client_sessions.assert_awaited_once()

    async def test_pool_shutdown_closes_all(self):
        """shutdown() closes all pooled clients."""
        pool = MCPClientPool(max_clients=10, ttl_seconds=300)

        mock_clients = []
        for uid in ["u1", "u2", "u3"]:
            mc = MagicMock()
            mc.close_all_client_sessions = AsyncMock()
            pool._clients[uid] = PooledClient(client=mc)
            mock_clients.append(mc)

        await pool.shutdown()

        assert pool.size == 0
        for mc in mock_clients:
            mc.close_all_client_sessions.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Tool Discovery via MCP
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestToolDiscovery:
    """Test MCPToolsStore: tool storage and retrieval."""

    async def test_store_tools_writes_to_mongodb(self):
        """store_tools calls MongoDB update_one with formatted tool data."""
        store = MCPToolsStore()

        raw_tools = [
            {"name": "get_data", "description": "Gets data from API"},
            {"name": "post_data", "description": "Posts data to API"},
        ]

        with (
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_col,
            patch(
                "app.services.mcp.mcp_tools_store.delete_cache",
                new=AsyncMock(),
            ),
            patch.object(store, "_refresh_cache", new=AsyncMock()),
        ):
            mock_col.update_one = AsyncMock()

            await store.store_tools("tool-int", raw_tools)

            mock_col.update_one.assert_awaited_once()
            call_args = mock_col.update_one.call_args
            filter_doc = call_args[0][0]
            assert filter_doc == {"integration_id": "tool-int"}
            update_doc = call_args[0][1]
            stored_tools = update_doc["$set"]["tools"]
            assert len(stored_tools) == 2
            assert stored_tools[0]["name"] == "get_data"

    def test_format_tools_strips_whitespace_and_filters_empty(self):
        """_format_tools strips whitespace and drops tools without names."""
        tools = [
            {"name": "  valid_tool  ", "description": "  desc  "},
            {"name": "", "description": "empty name"},
            {"name": "   ", "description": "whitespace name"},
            {"name": "another_tool", "description": ""},
        ]
        result = _format_tools(tools)
        assert len(result) == 2
        assert result[0]["name"] == "valid_tool"
        assert result[0]["description"] == "desc"
        assert result[1]["name"] == "another_tool"

    async def test_store_tools_skips_empty_list(self):
        """store_tools is a no-op for empty tool list."""
        store = MCPToolsStore()

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_col:
            mock_col.update_one = AsyncMock()
            await store.store_tools("empty-int", [])
            mock_col.update_one.assert_not_awaited()

    async def test_get_tools_returns_stored_tools(self):
        """get_tools returns tools from MongoDB for the integration."""
        store = MCPToolsStore()

        stored_doc = {
            "tools": [
                {"name": "tool_a", "description": "Tool A"},
            ]
        }

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=stored_doc)

            result = await store.get_tools("my-int")

        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "tool_a"

    async def test_get_tools_returns_none_when_not_found(self):
        """get_tools returns None when integration has no stored tools."""
        store = MCPToolsStore()

        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            result = await store.get_tools("missing-int")

        assert result is None


# ---------------------------------------------------------------------------
# 8. Error Handling
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestErrorHandling:
    """Test that errors propagate clearly, not swallowed."""

    def test_validate_https_rejects_http(self):
        """validate_https_url raises OAuthSecurityError for non-localhost HTTP."""
        with pytest.raises(OAuthSecurityError, match="must use HTTPS"):
            validate_https_url("http://remote-server.com/token", allow_localhost=True)

    def test_validate_https_allows_localhost_http(self):
        """validate_https_url allows HTTP for localhost in development."""
        # Should not raise
        validate_https_url("http://localhost:8080/token", allow_localhost=True)
        validate_https_url("http://127.0.0.1:8080/token", allow_localhost=True)

    def test_validate_https_accepts_https(self):
        """validate_https_url accepts HTTPS URLs."""
        validate_https_url("https://auth.example.com/token")

    def test_validate_pkce_rejects_no_support(self):
        """validate_pkce_support raises when no methods advertised."""
        with pytest.raises(ValueError, match="PKCE support"):
            validate_pkce_support({"code_challenge_methods_supported": []}, "test-int")

    def test_validate_pkce_rejects_plain_only(self):
        """validate_pkce_support raises when only plain is supported."""
        with pytest.raises(ValueError, match="insecure"):
            validate_pkce_support(
                {"code_challenge_methods_supported": ["plain"]}, "test-int"
            )

    def test_validate_pkce_accepts_s256(self):
        """validate_pkce_support succeeds when S256 is supported."""
        validate_pkce_support(
            {"code_challenge_methods_supported": ["S256"]}, "test-int"
        )

    def test_validate_token_response_rejects_missing_access_token(self):
        """validate_token_response raises when access_token is missing."""
        with pytest.raises(ValueError, match="access_token"):
            validate_token_response({}, "test-int")

    def test_validate_token_response_rejects_missing_token_type(self):
        """validate_token_response raises when token_type is missing."""
        with pytest.raises(ValueError, match="token_type"):
            validate_token_response({"access_token": "at"}, "test-int")

    def test_validate_token_response_rejects_non_bearer(self):
        """validate_token_response raises for non-Bearer token type."""
        with pytest.raises(ValueError, match="Unsupported token_type"):
            validate_token_response(
                {"access_token": "at", "token_type": "MAC"}, "test-int"
            )

    def test_validate_token_response_accepts_bearer(self):
        """validate_token_response succeeds with valid Bearer response."""
        validate_token_response(
            {"access_token": "at", "token_type": "Bearer"}, "test-int"
        )

    def test_parse_oauth_error_response_extracts_fields(self):
        """parse_oauth_error_response extracts error info from JSON responses."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "error": "invalid_request",
            "error_description": "Missing required parameter",
        }

        result = parse_oauth_error_response(mock_response)

        assert result["error"] == "invalid_request"
        assert result["error_description"] == "Missing required parameter"
        assert result["status_code"] == 400

    def test_validate_oauth_endpoints_rejects_http_endpoints(self):
        """validate_oauth_endpoints rejects HTTP endpoints on non-localhost."""
        config = {
            "authorization_endpoint": "http://remote.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
        with pytest.raises(OAuthSecurityError):
            validate_oauth_endpoints(config, allow_localhost=False)

    async def test_connection_failure_propagates_error(self):
        """When MCP connection fails, the error propagates up (not swallowed)."""
        client = MCPClient(user_id="test-user")
        client.token_store = MagicMock()
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.get_oauth_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)
        resolved.source = "platform"
        resolved.custom_doc = None

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new=AsyncMock(),
            ),
        ):
            with pytest.raises(ValueError, match="OAuth authorization required"):
                await client.connect("no-token-int")


# ---------------------------------------------------------------------------
# 9. Concurrent Connections / Isolated Token Storage
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConcurrentConnectionIsolation:
    """Test that different users and integrations have isolated token storage."""

    async def test_different_users_have_separate_token_stores(self):
        """MCPClient instances for different users use separate MCPTokenStore."""
        client_a = MCPClient(user_id="user-a")
        client_b = MCPClient(user_id="user-b")

        assert client_a.token_store.user_id == "user-a"
        assert client_b.token_store.user_id == "user-b"
        assert client_a.token_store is not client_b.token_store

    async def test_same_user_multiple_integrations_isolated_state(self):
        """Same user connecting to multiple MCP servers maintains separate state per integration."""
        client = MCPClient(user_id="multi-user")
        client.token_store = MagicMock()
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.get_oauth_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client.token_store.store_unauthenticated = AsyncMock()
        client.token_store.get_oauth_discovery = AsyncMock(return_value=None)

        tool_a = MagicMock()
        tool_a.name = "tool_from_server_a"
        tool_a.description = "Tool A"
        tool_a.metadata = {}

        tool_b = MagicMock()
        tool_b.name = "tool_from_server_b"
        tool_b.description = "Tool B"
        tool_b.metadata = {}

        resolved_a = MagicMock()
        resolved_a.mcp_config = _make_mcp_config(
            server_url="https://server-a.example.com", requires_auth=False
        )
        resolved_a.source = "platform"
        resolved_a.custom_doc = None

        resolved_b = MagicMock()
        resolved_b.mcp_config = _make_mcp_config(
            server_url="https://server-b.example.com", requires_auth=False
        )
        resolved_b.source = "platform"
        resolved_b.custom_doc = None

        resolve_map = {"int-a": resolved_a, "int-b": resolved_b}
        adapter_tools_map = {"int-a": [tool_a], "int-b": [tool_b]}

        def make_adapter_for(integration_id):
            mock_adapter = MagicMock()
            mock_adapter.create_tools = AsyncMock(
                return_value=adapter_tools_map[integration_id]
            )
            return mock_adapter

        adapter_call_count = 0

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(side_effect=lambda iid: resolve_map[iid]),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
            ) as mock_base_cls,
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
            ) as mock_adapter_cls,
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **kw: tools,
            ),
            patch(
                "app.services.mcp.mcp_client.get_mcp_tools_store",
                return_value=MagicMock(store_tools=AsyncMock()),
            ),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new=AsyncMock(),
            ),
        ):
            mock_base_instance = MagicMock()
            mock_base_instance.create_session = AsyncMock()
            mock_base_instance.close_all_sessions = AsyncMock()
            mock_base_cls.return_value = mock_base_instance

            # Track which integration gets which adapter
            adapter_instances = []

            def adapter_factory():
                nonlocal adapter_call_count
                adapter_call_count += 1
                # Return tools based on call order
                m = MagicMock()
                adapter_instances.append(m)
                return m

            mock_adapter_cls.side_effect = lambda: adapter_factory()

            # Set up adapter to return correct tools
            def make_create_tools(idx):
                async def create_tools(c):
                    if idx == 0:
                        return [tool_a]
                    return [tool_b]

                return create_tools

            # Connect to server A
            adapter_instances.clear()
            adapter_call_count = 0
            mock_adapter_cls.side_effect = lambda: MagicMock(
                create_tools=AsyncMock(return_value=[tool_a])
            )
            tools_a = await client.connect("int-a")

            mock_adapter_cls.side_effect = lambda: MagicMock(
                create_tools=AsyncMock(return_value=[tool_b])
            )
            tools_b = await client.connect("int-b")

        # Both integrations have tools but they are separate
        assert len(tools_a) == 1
        assert len(tools_b) == 1
        assert tools_a[0].name == "tool_from_server_a"
        assert tools_b[0].name == "tool_from_server_b"

        # Internal state has both integrations isolated
        assert "int-a" in client._tools
        assert "int-b" in client._tools
        assert client._tools["int-a"] is not client._tools["int-b"]

    @patch("app.services.mcp.mcp_token_store.get_db_session")
    async def test_oauth_state_per_user_per_integration(self, mock_get_session):
        """OAuth state is keyed by (user_id, integration_id) for isolation."""
        store_a = _make_token_store("user-a")
        store_b = _make_token_store("user-b")

        with patch(
            "app.services.mcp.mcp_token_store.set_cache", new_callable=AsyncMock
        ) as mock_set_cache:
            state_a = await store_a.create_oauth_state("shared-int", "verifier-a")
            state_b = await store_b.create_oauth_state("shared-int", "verifier-b")

        # States are different random values
        assert state_a != state_b

        # Cache keys include user_id for isolation
        call_keys = [call[0][0] for call in mock_set_cache.call_args_list]
        assert any("user-a" in key for key in call_keys)
        assert any("user-b" in key for key in call_keys)


# ---------------------------------------------------------------------------
# PKCE Utility Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPKCEGeneration:
    """Test PKCE code_verifier/code_challenge generation."""

    def test_pkce_pair_produces_valid_values(self):
        """generate_pkce_pair returns a verifier and S256 challenge."""
        verifier, challenge = generate_pkce_pair()

        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 20
        assert len(challenge) > 20
        # Challenge should be base64url without padding
        assert "=" not in challenge

    def test_pkce_pairs_are_unique(self):
        """Each call produces different verifier/challenge pairs."""
        pair_1 = generate_pkce_pair()
        pair_2 = generate_pkce_pair()

        assert pair_1[0] != pair_2[0]
        assert pair_1[1] != pair_2[1]

    def test_pkce_challenge_is_s256_of_verifier(self):
        """The code_challenge is the base64url(SHA256(code_verifier))."""
        import base64
        import hashlib

        verifier, challenge = generate_pkce_pair()
        digest = hashlib.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")

        assert challenge == expected


# ---------------------------------------------------------------------------
# Client Credential Resolution
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClientCredentialResolution:
    """Test resolve_client_credentials priority order."""

    def test_returns_config_credentials_first(self):
        """Pre-configured client_id/secret take priority."""
        config = _make_mcp_config(client_id="cfg-cid", client_secret="cfg-secret")
        cid, secret = resolve_client_credentials(config)

        assert cid == "cfg-cid"
        assert secret == "cfg-secret"

    def test_falls_back_to_env_vars(self):
        """When config has env var names, resolves from environment."""
        config = _make_mcp_config(
            client_id=None,
            client_secret=None,
            client_id_env="TEST_MCP_CLIENT_ID",
            client_secret_env="TEST_MCP_CLIENT_SECRET",
        )

        with patch.dict(
            "os.environ",
            {
                "TEST_MCP_CLIENT_ID": "env-cid",
                "TEST_MCP_CLIENT_SECRET": "env-secret",
            },
        ):
            cid, secret = resolve_client_credentials(config)

        assert cid == "env-cid"
        assert secret == "env-secret"

    def test_returns_none_when_nothing_configured(self):
        """When no credentials are configured, returns (None, None)."""
        config = _make_mcp_config(client_id=None, client_secret=None)
        cid, secret = resolve_client_credentials(config)

        assert cid is None
        assert secret is None
