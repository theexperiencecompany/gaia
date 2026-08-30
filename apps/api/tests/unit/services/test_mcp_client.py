"""Comprehensive unit tests for MCP client, client pool, token store, token management,
OAuth discovery, LangChain adapter, and resilient adapter.

Covers: connect, disconnect, execute tool, list tools, client pool get/evict/cleanup/shutdown,
token store CRUD/encrypt/decrypt, token refresh/expiry, OAuth discovery, probe,
LangChain adapter schema sanitization, and resilient adapter retry/skip logic.
"""

import asyncio
import base64
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

from langchain_core.tools import BaseTool
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from mcp.types import (
    CallToolResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl
import pytest

from app.constants.device_bridge import DEVICE_TRANSPORT
from app.constants.log_tags import LogTag
from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.models.device import Device
from app.models.mcp_config import MCPConfig, OAuthDiscovery
from app.services.mcp.langchain_adapter import SanitizingLangChainAdapter
from app.services.mcp.mcp_client import (
    DCRNotSupportedError,
    MCPClient,
    StepUpAuthRequiredError,
    _parse_device_server_url,
    get_mcp_client,
)
from app.services.mcp.mcp_client_pool import MCPClientPool, PooledClient
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.oauth_discovery import discover_oauth_config, probe_mcp_connection
from app.services.mcp.resilient_adapter import ResilientLangChainAdapter
from app.services.mcp.token_management import (
    resolve_client_credentials,
    revoke_tokens,
    try_refresh_token,
)
from app.utils.mcp_oauth_utils import MCP_PROTOCOL_VERSION

# ---------------------------------------------------------------------------
# Helpers / Factories
# ---------------------------------------------------------------------------

USER_ID = "test_user_123"
INTEGRATION_ID = "test_integration"
SERVER_URL = "https://mcp.example.com/v1"


def _make_mcp_config(**overrides: Any) -> MCPConfig:
    defaults: dict[str, Any] = {"server_url": SERVER_URL, "requires_auth": False}
    defaults.update(overrides)
    return MCPConfig(**defaults)


def _make_oauth_metadata(**overrides: Any) -> OAuthMetadata:
    """Build a valid RFC 8414 OAuthMetadata with HTTPS endpoints + PKCE support."""
    defaults: dict[str, Any] = {
        "issuer": "https://auth.example.com",
        "authorization_endpoint": "https://auth.example.com/authorize",
        "token_endpoint": "https://auth.example.com/token",
        "code_challenge_methods_supported": ["S256"],
    }
    defaults.update(overrides)
    return OAuthMetadata.model_validate(defaults)


def _make_oauth_discovery(
    metadata_overrides: dict[str, Any] | None = None, **overrides: Any
) -> OAuthDiscovery:
    """Build an OAuthDiscovery (SDK-model based) for tests.

    ``metadata_overrides`` tweak the wrapped ``as_metadata`` (e.g. drop the
    authorization_endpoint); ``overrides`` tweak the OAuthDiscovery fields
    (resource, initial_scope, discovery_method, prm).
    """
    as_metadata = _make_oauth_metadata(**(metadata_overrides or {}))
    defaults: dict[str, Any] = {
        "as_metadata": as_metadata,
        "resource": SERVER_URL,
        "discovery_method": "rfc9728_prm",
    }
    defaults.update(overrides)
    return OAuthDiscovery(**defaults)


def _make_credential(**overrides: Any) -> MCPCredential:
    """Build a lightweight MCPCredential mock with sensible defaults."""
    cred = MagicMock(spec=MCPCredential)
    cred.user_id = overrides.get("user_id", USER_ID)
    cred.integration_id = overrides.get("integration_id", INTEGRATION_ID)
    cred.auth_type = overrides.get("auth_type", MCPAuthType.OAUTH)
    cred.status = overrides.get("status", MCPCredentialStatus.CONNECTED)
    cred.access_token = overrides.get("access_token", "encrypted_token")
    cred.refresh_token = overrides.get("refresh_token")
    cred.token_expires_at = overrides.get("token_expires_at")
    cred.client_registration = overrides.get("client_registration")
    cred.connected_at = overrides.get("connected_at")
    cred.error_message = overrides.get("error_message")
    return cred


def _api_error(status_code: int) -> Exception:
    """A connect failure that carries an HTTP response, the way the SDK raises.

    Only the status matters here — the body has no OAuth error code, so the
    terminal-vs-transient decision is made on the status alone.
    """
    err = RuntimeError(f"server returned {status_code}")
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {}
    err.response = response  # type: ignore[attr-defined]  # mirrors the SDK's own attached response
    return err


def _mock_tool(name: str = "test_tool", description: str = "A test tool") -> MagicMock:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.description = description
    tool.metadata = {}
    return tool


# ---------------------------------------------------------------------------
# Fake DB session context manager
# ---------------------------------------------------------------------------


def _fake_db_session(cred: MCPCredential | None = None):
    """Return an async context manager that yields a mock SQLAlchemy session."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = cred
    mock_result.fetchall.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.delete = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield mock_session

    return _ctx, mock_session


# ===========================================================================
# MCPClient Tests
# ===========================================================================


class TestMCPClientInit:
    def test_init_sets_user_id(self):
        client = MCPClient(user_id=USER_ID)
        assert client.user_id == USER_ID

    def test_init_creates_token_store(self):
        client = MCPClient(user_id=USER_ID)
        assert isinstance(client.token_store, MCPTokenStore)
        assert client.token_store.user_id == USER_ID

    def test_init_empty_dicts(self):
        client = MCPClient(user_id=USER_ID)
        assert client._clients == {}
        assert client._tools == {}
        assert client._connecting == {}
        assert client._connect_results == {}


class TestMCPClientSanitizeConfig:
    def test_sanitize_removes_secrets(self):
        client = MCPClient(user_id=USER_ID)
        config = {
            "mcpServers": {
                "srv1": {
                    "url": "https://example.com",
                    "transport": "streamable-http",
                    "auth": "super_secret_token",  # NOSONAR
                    "headers": {"Authorization": "Bearer secret"},
                }
            }
        }
        sanitized = client._sanitize_config(config)
        srv = sanitized["mcpServers"]["srv1"]
        assert srv["url"] == "https://example.com"
        assert srv["transport"] == "streamable-http"
        assert srv["has_auth"] is True
        assert srv["has_headers"] is True
        assert "auth" not in srv
        assert "headers" not in srv

    def test_sanitize_no_auth(self):
        client = MCPClient(user_id=USER_ID)
        config = {"mcpServers": {"srv": {"url": "https://ex.com", "auth": None}}}
        sanitized = client._sanitize_config(config)
        assert sanitized["mcpServers"]["srv"]["has_auth"] is False


class TestMCPClientProbeConnection:
    async def test_probe_delegates_to_module_function(self):
        client = MCPClient(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_client.probe_mcp_connection",
            new_callable=AsyncMock,
            return_value={"requires_auth": False, "auth_type": "none"},
        ) as mock_probe:
            result = await client.probe_connection(SERVER_URL)
            mock_probe.assert_awaited_once_with(SERVER_URL)
            assert result["requires_auth"] is False


class TestMCPClientUpdateIntegrationAuthStatus:
    async def test_updates_mongodb(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.integration_repository") as mock_repo:
            mock_repo.set_mcp_auth = AsyncMock(return_value=True)
            await client.update_integration_auth_status(INTEGRATION_ID, True, "oauth")
            mock_repo.set_mcp_auth.assert_awaited_once_with(INTEGRATION_ID, True, "oauth")

    async def test_handles_exception_gracefully(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.integration_repository") as mock_repo:
            mock_repo.set_mcp_auth = AsyncMock(side_effect=Exception("DB failure"))
            # Should not raise
            await client.update_integration_auth_status(INTEGRATION_ID, False, "none")


class TestMCPClientBuildConfig:
    async def test_build_config_no_auth(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        srv = config["mcpServers"][INTEGRATION_ID]
        assert srv["url"] == SERVER_URL
        assert srv["auth"] is None
        assert srv["transport"] == "streamable-http"

    async def test_build_config_with_bearer_token(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        client.token_store.get_bearer_token = AsyncMock(return_value="my_token")
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        srv = config["mcpServers"][INTEGRATION_ID]
        assert srv["auth"] == "my_token"
        assert srv["headers"]["Authorization"] == "Bearer my_token"

    async def test_build_config_strips_bearer_prefix(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        client.token_store.get_bearer_token = AsyncMock(return_value="Bearer actual_token")
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        srv = config["mcpServers"][INTEGRATION_ID]
        assert srv["auth"] == "actual_token"
        assert srv["headers"]["Authorization"] == "Bearer actual_token"

    async def test_build_config_oauth_token_when_auth_required(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(requires_auth=True)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client.token_store.get_oauth_token = AsyncMock(return_value="oauth_tok")
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        assert config["mcpServers"][INTEGRATION_ID]["auth"] == "oauth_tok"

    async def test_build_config_raises_when_auth_required_no_token(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(requires_auth=True)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client.token_store.get_oauth_token = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="No valid token"):
            await client._build_config(INTEGRATION_ID, mcp_config)

    async def test_build_config_explicit_transport(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(transport="sse")
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        assert config["mcpServers"][INTEGRATION_ID]["transport"] == "sse"

    async def test_build_config_refreshes_expiring_token(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(requires_auth=True)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=True)
        client.token_store.get_oauth_token = AsyncMock(return_value="refreshed_tok")
        client._try_refresh_token = AsyncMock(return_value=True)
        config = await client._build_config(INTEGRATION_ID, mcp_config)
        client._try_refresh_token.assert_awaited_once()
        assert config["mcpServers"][INTEGRATION_ID]["auth"] == "refreshed_tok"


class TestMCPClientConnect:
    async def test_returns_cached_tools(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]
        client._tools[INTEGRATION_ID] = tools
        result = await client.connect(INTEGRATION_ID)
        assert result is tools

    async def test_deduplicates_concurrent_connects(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        async def slow_connect(iid: str) -> list:
            await asyncio.sleep(0.1)
            client._tools[iid] = tools
            return tools

        client._do_connect = AsyncMock(side_effect=slow_connect)

        results = await asyncio.gather(
            client.connect(INTEGRATION_ID),
            client.connect(INTEGRATION_ID),
        )
        # Only one actual connect should happen
        assert client._do_connect.await_count == 1
        assert results[0] is tools
        assert results[1] is tools

    async def test_raises_when_concurrent_connect_fails(self):
        client = MCPClient(user_id=USER_ID)

        async def failing_connect(iid: str) -> list:
            await asyncio.sleep(0.05)
            raise ValueError("Connection failed")

        client._do_connect = AsyncMock(side_effect=failing_connect)

        with pytest.raises(ValueError, match="Connection failed|Concurrent connect"):
            await asyncio.gather(
                client.connect(INTEGRATION_ID),
                client.connect(INTEGRATION_ID),
            )


class TestMCPClientDoConnect:
    @pytest.fixture(autouse=True)
    def _mock_ssrf_guard(self) -> Iterator[None]:
        """Neutralize the DNS-resolving SSRF guard so tests use fake hostnames."""
        with patch(
            "app.services.mcp.mcp_client.assert_public_http_url",
            new_callable=AsyncMock,
        ):
            yield

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.ResilientLangChainAdapter")
    @patch("app.services.mcp.mcp_client.wrap_tools_with_null_filter")
    @patch("app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new_callable=AsyncMock,
    )
    async def test_successful_connect(
        self,
        mock_update_status,
        mock_store_tools,
        mock_wrap,
        mock_adapter_cls,
        mock_base_client_cls,
        mock_resolver,
    ):
        # Setup resolver
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        resolved.source = "platform"
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        # Setup BaseMCPClient
        mock_base_client = AsyncMock()
        mock_base_client_cls.return_value = mock_base_client

        # Setup adapter
        tools = [_mock_tool("tool_a"), _mock_tool("tool_b")]
        mock_adapter = AsyncMock()
        mock_adapter.create_tools = AsyncMock(return_value=tools)
        mock_adapter_cls.return_value = mock_adapter

        # Wrap returns same tools
        mock_wrap.return_value = tools

        client = MCPClient(user_id=USER_ID)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.store_unauthenticated = AsyncMock()

        result = await client._do_connect(INTEGRATION_ID)

        assert len(result) == 2
        assert INTEGRATION_ID in client._tools
        assert INTEGRATION_ID in client._clients
        mock_base_client.create_session.assert_awaited_once()
        mock_adapter.create_tools.assert_awaited_once()

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    async def test_raises_when_integration_not_found(self, mock_resolver):
        mock_resolver.resolve = AsyncMock(return_value=None)
        client = MCPClient(user_id=USER_ID)
        with pytest.raises(ValueError, match="not found"):
            await client._do_connect(INTEGRATION_ID)

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    async def test_raises_when_no_mcp_config(self, mock_resolver):
        resolved = MagicMock()
        resolved.mcp_config = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)
        client = MCPClient(user_id=USER_ID)
        with pytest.raises(ValueError, match="not found"):
            await client._do_connect(INTEGRATION_ID)

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.ResilientLangChainAdapter")
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.mcp.mcp_client.delete_cache", new_callable=AsyncMock)
    async def test_step_up_auth_on_403_insufficient_scope(
        self,
        mock_delete_cache,
        mock_update_status,
        mock_adapter_cls,
        mock_base_client_cls,
        mock_resolver,
    ):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)
        resolved.source = "platform"
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        mock_base_client = AsyncMock()
        mock_base_client_cls.return_value = mock_base_client
        mock_base_client.create_session = AsyncMock(
            side_effect=Exception('403 insufficient_scope scope="read write"')
        )

        client = MCPClient(user_id=USER_ID)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client.token_store.get_oauth_token = AsyncMock(return_value="tok")

        with pytest.raises(StepUpAuthRequiredError) as exc_info:
            await client._do_connect(INTEGRATION_ID)

        assert exc_info.value.integration_id == INTEGRATION_ID
        assert "read" in exc_info.value.required_scopes

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.ResilientLangChainAdapter")
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new_callable=AsyncMock,
    )
    @patch("app.services.mcp.mcp_client.delete_cache", new_callable=AsyncMock)
    async def test_closes_leaked_session_on_tool_conversion_failure(
        self,
        mock_delete_cache,
        mock_update_status,
        mock_adapter_cls,
        mock_base_client_cls,
        mock_resolver,
    ):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        resolved.source = "platform"
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        mock_base_client = AsyncMock()
        mock_base_client_cls.return_value = mock_base_client
        mock_base_client.create_session = AsyncMock()
        mock_base_client.close_all_sessions = AsyncMock()

        mock_adapter = AsyncMock()
        mock_adapter.create_tools = AsyncMock(side_effect=Exception("Schema error"))
        mock_adapter_cls.return_value = mock_adapter

        client = MCPClient(user_id=USER_ID)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)

        with pytest.raises(Exception, match="Schema error"):
            await client._do_connect(INTEGRATION_ID)

        mock_base_client.close_all_sessions.assert_awaited_once()

    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.ResilientLangChainAdapter")
    @patch("app.services.mcp.mcp_client.wrap_tools_with_null_filter")
    @patch("app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new_callable=AsyncMock,
    )
    async def test_retries_connect_once_after_successful_token_refresh(
        self,
        mock_update_status,
        mock_store_tools,
        mock_wrap,
        mock_adapter_cls,
        mock_base_client_cls,
        mock_resolver,
    ):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)
        resolved.source = "platform"
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        tools = [_mock_tool("tool_a")]
        mock_base_client = AsyncMock()
        mock_base_client_cls.return_value = mock_base_client
        # First attempt hits a stale token; the post-refresh retry succeeds.
        mock_base_client.create_session = AsyncMock(
            side_effect=[Exception("401 Unauthorized"), MagicMock()]
        )
        mock_adapter = AsyncMock()
        mock_adapter.create_tools = AsyncMock(return_value=tools)
        mock_adapter_cls.return_value = mock_adapter
        mock_wrap.return_value = tools

        client = MCPClient(user_id=USER_ID)
        client.token_store.get_bearer_token = AsyncMock(return_value=None)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client.token_store.get_oauth_token = AsyncMock(return_value="tok")
        client.token_store.store_unauthenticated = AsyncMock()
        client._try_refresh_token = AsyncMock(return_value=True)

        result = await client._do_connect(INTEGRATION_ID)

        assert result is tools
        client._try_refresh_token.assert_awaited_once_with(INTEGRATION_ID, resolved.mcp_config)
        assert mock_base_client.create_session.await_count == 2
        assert client._tools[INTEGRATION_ID] is tools


class TestParseDeviceServerUrl:
    def test_parses_device_id_and_server_key(self):
        device_id, server_key = _parse_device_server_url("device://dev-123/filesystem")
        assert device_id == "dev-123"
        assert server_key == "filesystem"

    def test_rejects_non_device_scheme(self):
        with pytest.raises(ValueError, match="Not a device server URL"):
            _parse_device_server_url("https://example.com/dev-123/filesystem")

    def test_rejects_missing_server_key(self):
        with pytest.raises(ValueError, match="Malformed device server URL"):
            _parse_device_server_url("device://dev-123")

    def test_rejects_missing_device_id(self):
        with pytest.raises(ValueError, match="Malformed device server URL"):
            _parse_device_server_url("device://")


class TestMCPClientBuildDeviceClient:
    """The hard cross-user isolation gate: a device session must never build for a device the caller does not own."""

    def _device_config(self, device_id: str = "dev-123", server_key: str = "filesystem"):
        return _make_mcp_config(server_url=f"device://{device_id}/{server_key}", transport="device")

    async def test_raises_when_device_not_found(self):
        client = MCPClient(user_id=USER_ID)
        with patch(
            "app.services.device.device_service.get_active_device",
            new_callable=AsyncMock,
            return_value=None,
        ):
            with pytest.raises(ValueError, match="not an active device owned by"):
                await client._build_device_client(INTEGRATION_ID, self._device_config())

    async def test_raises_when_device_owned_by_different_user(self):
        """A valid, active device that simply belongs to someone else must still be rejected."""
        client = MCPClient(user_id=USER_ID)
        someone_elses_device = MagicMock(spec=Device)
        someone_elses_device.user_id = "a_completely_different_user"
        with patch(
            "app.services.device.device_service.get_active_device",
            new_callable=AsyncMock,
            return_value=someone_elses_device,
        ):
            with pytest.raises(ValueError, match="not an active device owned by"):
                await client._build_device_client(INTEGRATION_ID, self._device_config())

    async def test_succeeds_when_device_owned_by_caller(self):
        client = MCPClient(user_id=USER_ID)
        own_device = MagicMock(spec=Device)
        own_device.user_id = USER_ID

        mock_session = AsyncMock()
        with (
            patch(
                "app.services.device.device_service.get_active_device",
                new_callable=AsyncMock,
                return_value=own_device,
            ),
            patch("app.services.mcp.mcp_client.DeviceConnector") as mock_connector_cls,
            patch(
                "app.services.mcp.mcp_client.MCPSession", return_value=mock_session
            ) as mock_session_cls,
        ):
            result = await client._build_device_client(INTEGRATION_ID, self._device_config())

            mock_connector_cls.assert_called_once_with("dev-123", "filesystem")
            mock_session_cls.assert_called_once()
            mock_session.initialize.assert_awaited_once()
            assert result.sessions[INTEGRATION_ID] is mock_session
            assert INTEGRATION_ID in result.active_sessions


class TestMCPClientDisconnect:
    async def test_disconnect_cleans_up(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = AsyncMock()
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        with (
            patch(
                "app.services.mcp.mcp_client.delete_cache",
                new_callable=AsyncMock,
            ),
            patch("app.services.mcp.mcp_client.integration_repository") as mock_repo,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.clear_tools = AsyncMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            client.token_store.get_oauth_discovery = AsyncMock(return_value=None)
            client.token_store.delete_credentials = AsyncMock()

            await client.disconnect(INTEGRATION_ID)

        assert INTEGRATION_ID not in client._clients
        assert INTEGRATION_ID not in client._tools
        mock_base.close_all_sessions.assert_awaited_once()

    async def test_disconnect_handles_close_error(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = AsyncMock()
        mock_base.close_all_sessions = AsyncMock(side_effect=Exception("Close error"))
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        with (
            patch("app.services.mcp.mcp_client.delete_cache", new_callable=AsyncMock),
            patch("app.services.mcp.mcp_client.integration_repository") as mock_repo,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.clear_tools = AsyncMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            client.token_store.get_oauth_discovery = AsyncMock(return_value=None)
            client.token_store.delete_credentials = AsyncMock()

            await client.disconnect(INTEGRATION_ID)

        # Should still remove from dicts despite error
        assert INTEGRATION_ID not in client._clients

    async def test_disconnect_not_connected(self):
        """Disconnect when no active session - should not raise."""
        client = MCPClient(user_id=USER_ID)
        with (
            patch("app.services.mcp.mcp_client.delete_cache", new_callable=AsyncMock),
            patch("app.services.mcp.mcp_client.integration_repository") as mock_repo,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_repo.clear_tools = AsyncMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            client.token_store.get_oauth_discovery = AsyncMock(return_value=None)
            client.token_store.delete_credentials = AsyncMock()

            await client.disconnect(INTEGRATION_ID)


class TestMCPClientGetTools:
    async def test_returns_tools_for_connected(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]
        client._tools[INTEGRATION_ID] = tools
        result = await client.get_tools(INTEGRATION_ID)
        assert result is tools

    async def test_returns_empty_for_unknown(self):
        client = MCPClient(user_id=USER_ID)
        result = await client.get_tools("unknown")
        assert result == []


class TestMCPClientIsConnected:
    def test_is_connected_true(self):
        client = MCPClient(user_id=USER_ID)
        client._clients[INTEGRATION_ID] = MagicMock()
        assert client.is_connected(INTEGRATION_ID) is True

    def test_is_connected_false(self):
        client = MCPClient(user_id=USER_ID)
        assert client.is_connected("unknown") is False


class TestMCPClientIsConnectedDb:
    async def test_connected_in_db(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.user_integration_repository") as mock_repo:
            mock_repo.is_connected = AsyncMock(return_value=True)
            assert await client.is_connected_db(INTEGRATION_ID) is True
            mock_repo.is_connected.assert_awaited_once_with(USER_ID, INTEGRATION_ID)

    async def test_not_connected_in_db(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.user_integration_repository") as mock_repo:
            mock_repo.is_connected = AsyncMock(return_value=False)
            assert await client.is_connected_db(INTEGRATION_ID) is False


class TestMCPClientEnsureConnected:
    async def test_returns_cached(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]
        client._tools[INTEGRATION_ID] = tools
        result = await client.ensure_connected(INTEGRATION_ID)
        assert result is tools

    async def test_reconnects_from_db(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        with patch.object(client, "is_connected_db", new_callable=AsyncMock, return_value=True):
            with patch.object(client, "connect", new_callable=AsyncMock, return_value=tools):
                result = await client.ensure_connected(INTEGRATION_ID)
                assert result is tools

    async def test_raises_when_not_connected(self):
        client = MCPClient(user_id=USER_ID)
        with patch.object(client, "is_connected_db", new_callable=AsyncMock, return_value=False):
            with pytest.raises(ValueError, match="not connected"):
                await client.ensure_connected(INTEGRATION_ID)


class TestMCPClientNormalizeServerUrl:
    def test_strips_trailing_slash(self):
        assert MCPClient._normalize_server_url("https://ex.com/v1/") == "https://ex.com/v1"

    def test_lowercases_scheme_and_host(self):
        assert MCPClient._normalize_server_url("HTTPS://EX.COM/Path") == "https://ex.com/Path"

    def test_empty_string(self):
        assert MCPClient._normalize_server_url("") == ""

    def test_none_like_input(self):
        assert MCPClient._normalize_server_url("  ") == ""


class TestMCPClientCallToolOnServer:
    async def test_calls_tool_successfully(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            return_value=CallToolResult(
                content=[TextContent(type="text", text="result")], isError=False
            )
        )
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        # Mock _find_integration_id_by_server_url
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock(return_value=[_mock_tool()])

        result = await client.call_tool_on_server(SERVER_URL, "test_tool", {"arg": "val"})
        assert result.isError is False
        assert result.content[0].text == "result"

    async def test_raises_when_no_matching_integration(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="No connected MCP integration"):
            await client.call_tool_on_server("https://unknown.com", "tool", {})


class TestMCPClientCloseAllSessions:
    async def test_closes_all(self):
        client = MCPClient(user_id=USER_ID)
        mock1 = AsyncMock()
        mock2 = AsyncMock()
        client._clients["a"] = mock1
        client._clients["b"] = mock2
        await client.close_all_client_sessions()
        mock1.close_all_sessions.assert_awaited_once()
        mock2.close_all_sessions.assert_awaited_once()

    async def test_handles_close_errors(self):
        client = MCPClient(user_id=USER_ID)
        mock1 = AsyncMock()
        mock1.close_all_sessions = AsyncMock(side_effect=Exception("err"))
        client._clients["a"] = mock1
        # Should not raise
        await client.close_all_client_sessions()


class TestGetMcpClient:
    async def test_delegates_to_pool(self):
        mock_pool = AsyncMock()
        mock_client = MagicMock(spec=MCPClient)
        mock_pool.get = AsyncMock(return_value=mock_client)
        with patch(
            "app.services.mcp.mcp_client.get_mcp_client_pool",
            new_callable=AsyncMock,
            return_value=mock_pool,
        ):
            result = await get_mcp_client(USER_ID)
            assert result is mock_client


class TestStepUpAuthRequired:
    def test_attributes(self):
        exc = StepUpAuthRequiredError("my_int", ["read", "write"])
        assert exc.integration_id == "my_int"
        assert exc.required_scopes == ["read", "write"]
        assert "my_int" in str(exc)


class TestDCRNotSupportedError:
    def test_can_be_raised(self):
        with pytest.raises(DCRNotSupportedError):
            raise DCRNotSupportedError("Server doesn't support DCR")


# ===========================================================================
# MCPClientPool Tests
# ===========================================================================


class TestMCPClientPoolGet:
    async def test_creates_new_client(self):
        pool = MCPClientPool(max_clients=10)
        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = await pool.get("user1")
            assert result is mock_instance
            assert pool.size == 1

    async def test_reuses_existing_client(self):
        pool = MCPClientPool(max_clients=10)
        mock_client = MagicMock()
        pool._clients["user1"] = PooledClient(client=mock_client)
        result = await pool.get("user1")
        assert result is mock_client
        assert pool.size == 1

    async def test_evicts_oldest_at_capacity(self):
        pool = MCPClientPool(max_clients=2)
        old_client = MagicMock()
        old_client.close_all_client_sessions = AsyncMock()
        pool._clients["old_user"] = PooledClient(client=old_client)
        pool._clients["user2"] = PooledClient(client=MagicMock())

        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            mock_cls.return_value = MagicMock()
            await pool.get("user3")

        assert "old_user" not in pool._clients
        assert pool.size == 2
        old_client.close_all_client_sessions.assert_awaited_once()

    async def test_moves_to_end_on_reuse(self):
        pool = MCPClientPool(max_clients=10)
        pool._clients["a"] = PooledClient(client=MagicMock())
        pool._clients["b"] = PooledClient(client=MagicMock())
        await pool.get("a")
        # 'a' should now be at end
        assert list(pool._clients.keys())[-1] == "a"


class TestMCPClientPoolEvict:
    async def test_evicts_and_closes(self):
        pool = MCPClientPool()
        mock_client = MagicMock()
        mock_client.close_all_client_sessions = AsyncMock()
        pool._clients["u1"] = PooledClient(client=mock_client)
        await pool._evict("u1")
        assert "u1" not in pool._clients
        mock_client.close_all_client_sessions.assert_awaited_once()

    async def test_noop_for_unknown_user(self):
        pool = MCPClientPool()
        await pool._evict("nonexistent")


# TestMCPClientPoolCleanupStale and TestPooledClient.test_touch_updates_timestamp
# were deleted with the TTL-based cleanup. Sessions now persist for the worker's
# lifetime; eviction only fires at the max_clients cap (LRU).


class TestMCPClientPoolShutdown:
    async def test_shutdown_cleans_all(self):
        pool = MCPClientPool()
        mock1 = MagicMock()
        mock1.close_all_client_sessions = AsyncMock()
        mock2 = MagicMock()
        mock2.close_all_client_sessions = AsyncMock()
        pool._clients["u1"] = PooledClient(client=mock1)
        pool._clients["u2"] = PooledClient(client=mock2)
        await pool.shutdown()
        assert pool.size == 0
        mock1.close_all_client_sessions.assert_awaited_once()
        mock2.close_all_client_sessions.assert_awaited_once()


class TestMCPClientPoolSize:
    def test_size_property(self):
        pool = MCPClientPool()
        assert pool.size == 0
        pool._clients["a"] = PooledClient(client=MagicMock())
        assert pool.size == 1


# ===========================================================================
# MCPTokenStore Tests
# ===========================================================================


class TestMCPTokenStoreCipher:
    def test_get_cipher_missing_key_raises(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch("app.services.mcp.mcp_token_store.settings") as mock_settings:
            mock_settings.MCP_ENCRYPTION_KEY = None
            with pytest.raises(ValueError, match="MCP_ENCRYPTION_KEY not configured"):
                store._get_cipher()

    def test_get_cipher_invalid_key_raises(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch("app.services.mcp.mcp_token_store.settings") as mock_settings:
            mock_settings.MCP_ENCRYPTION_KEY = "not_a_valid_fernet_key"
            with pytest.raises(ValueError, match="not a valid Fernet key"):
                store._get_cipher()

    def test_encrypt_decrypt_round_trip(self):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode()
        store = MCPTokenStore(user_id=USER_ID)
        with patch("app.services.mcp.mcp_token_store.settings") as mock_settings:
            mock_settings.MCP_ENCRYPTION_KEY = key
            encrypted = store._encrypt("secret_data")
            assert encrypted != "secret_data"
            decrypted = store._decrypt(encrypted)
            assert decrypted == "secret_data"


class TestMCPTokenStoreGetCredential:
    async def test_returns_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential()
        ctx_fn, mock_session = _fake_db_session(cred)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            result = await store.get_credential(INTEGRATION_ID)
            assert result is cred

    async def test_returns_none_when_not_found(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, _ = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            result = await store.get_credential(INTEGRATION_ID)
            assert result is None


class TestMCPTokenStoreGetBearerToken:
    async def test_returns_decrypted_bearer(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(auth_type=MCPAuthType.BEARER)
        store.get_credential = AsyncMock(return_value=cred)
        store._decrypt = MagicMock(return_value="my_bearer_token")
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result == "my_bearer_token"

    async def test_returns_none_for_non_bearer(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(auth_type=MCPAuthType.OAUTH)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result is None

    async def test_returns_none_when_not_connected(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(auth_type=MCPAuthType.BEARER, status=MCPCredentialStatus.PENDING)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result is None

    async def test_returns_none_when_no_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_credential = AsyncMock(return_value=None)
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result is None


class TestMCPTokenStoreGetOAuthToken:
    async def test_returns_decrypted_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(auth_type=MCPAuthType.OAUTH, token_expires_at=None)
        store.get_credential = AsyncMock(return_value=cred)
        store._decrypt = MagicMock(return_value="decrypted_oauth")
        result = await store.get_oauth_token(INTEGRATION_ID)
        assert result == "decrypted_oauth"

    async def test_returns_none_when_expired(self):
        store = MCPTokenStore(user_id=USER_ID)
        past = datetime.now(UTC) - timedelta(hours=1)
        cred = _make_credential(token_expires_at=past)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_oauth_token(INTEGRATION_ID)
        assert result is None

    async def test_returns_none_when_no_access_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(access_token=None)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_oauth_token(INTEGRATION_ID)
        assert result is None

    async def test_returns_none_when_status_not_connected(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(status=MCPCredentialStatus.ERROR)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_oauth_token(INTEGRATION_ID)
        assert result is None


class TestMCPTokenStoreIsTokenExpiringSoon:
    async def test_true_when_expiring_soon(self):
        store = MCPTokenStore(user_id=USER_ID)
        soon = datetime.now(UTC) + timedelta(seconds=60)
        cred = _make_credential(token_expires_at=soon)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID, threshold_seconds=300)
        assert result is True

    async def test_false_when_not_expiring_soon(self):
        store = MCPTokenStore(user_id=USER_ID)
        far_future = datetime.now(UTC) + timedelta(hours=2)
        cred = _make_credential(token_expires_at=far_future)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is False

    async def test_false_when_no_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_credential = AsyncMock(return_value=None)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is False

    async def test_stale_token_without_expiry(self):
        """Token issued >1 hour ago with no expires_at should be treated as expiring."""
        store = MCPTokenStore(user_id=USER_ID)
        old = datetime.now(UTC) - timedelta(hours=2)
        cred = _make_credential(token_expires_at=None, connected_at=old)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is True

    async def test_fresh_token_without_expiry(self):
        """Token issued <1 hour ago with no expires_at should NOT be treated as expiring."""
        store = MCPTokenStore(user_id=USER_ID)
        recent = datetime.now(UTC) - timedelta(minutes=5)
        cred = _make_credential(token_expires_at=None, connected_at=recent)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is False


class TestMCPTokenStoreStoreOAuthTokens:
    async def test_stores_new_oauth_tokens(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)  # no existing credential
        store._encrypt = MagicMock(side_effect=lambda x: f"enc_{x}")
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_oauth_tokens(
                integration_id=INTEGRATION_ID,
                access_token="access_123",
                refresh_token="refresh_456",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        added = mock_session.add.call_args[0][0]
        assert added.user_id == USER_ID
        assert added.integration_id == INTEGRATION_ID
        assert added.auth_type == MCPAuthType.OAUTH
        assert added.access_token == "enc_access_123"
        assert added.refresh_token == "enc_refresh_456"
        assert added.status == MCPCredentialStatus.CONNECTED
        mock_session.commit.assert_awaited_once()

    async def test_updates_existing_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing_cred = _make_credential()
        ctx_fn, mock_session = _fake_db_session(existing_cred)
        store._encrypt = MagicMock(side_effect=lambda x: f"enc_{x}")
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_oauth_tokens(
                integration_id=INTEGRATION_ID,
                access_token="new_access",
            )
        assert existing_cred.access_token == "enc_new_access"
        mock_session.commit.assert_awaited_once()


class TestMCPTokenStoreStoreBearerToken:
    async def test_stores_new_bearer(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        store._encrypt = MagicMock(return_value="encrypted")
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_bearer_token(INTEGRATION_ID, "my_token")
        added = mock_session.add.call_args[0][0]
        assert added.user_id == USER_ID
        assert added.integration_id == INTEGRATION_ID
        assert added.auth_type == MCPAuthType.BEARER
        assert added.access_token == "encrypted"
        assert added.status == MCPCredentialStatus.CONNECTED
        mock_session.commit.assert_awaited_once()

    async def test_updates_existing_bearer(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential(auth_type=MCPAuthType.BEARER)
        ctx_fn, mock_session = _fake_db_session(existing)
        store._encrypt = MagicMock(return_value="enc_new")
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_bearer_token(INTEGRATION_ID, "new_token")
        assert existing.access_token == "enc_new"
        assert existing.status == MCPCredentialStatus.CONNECTED


class TestMCPTokenStoreOAuthState:
    async def test_create_and_verify_state(self):
        store = MCPTokenStore(user_id=USER_ID)
        stored_data: dict[str, Any] = {}

        async def fake_set_cache(key: str, data: Any, ttl: int = 0) -> None:
            stored_data[key] = data

        async def fake_get_and_delete(key: str) -> Any:
            return stored_data.pop(key, None)

        with (
            patch("app.services.mcp.mcp_token_store.set_cache", side_effect=fake_set_cache),
            patch(
                "app.services.mcp.mcp_token_store.get_and_delete_cache",
                side_effect=fake_get_and_delete,
            ),
        ):
            state = await store.create_oauth_state(INTEGRATION_ID, "verifier_123")
            assert isinstance(state, str)
            assert len(state) > 0

            is_valid, code_verifier = await store.verify_oauth_state(INTEGRATION_ID, state)
            assert is_valid is True
            assert code_verifier == "verifier_123"

    async def test_verify_wrong_state(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_token_store.get_and_delete_cache",
            new_callable=AsyncMock,
            return_value={"state": "correct_state", "code_verifier": "v"},
        ):
            is_valid, _ = await store.verify_oauth_state(INTEGRATION_ID, "wrong_state")
            assert is_valid is False

    async def test_verify_expired_state(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_token_store.get_and_delete_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            is_valid, _ = await store.verify_oauth_state(INTEGRATION_ID, "any")
            assert is_valid is False

    async def test_verify_legacy_string_state(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_token_store.get_and_delete_cache",
            new_callable=AsyncMock,
            return_value="my_state_string",
        ):
            is_valid, code_verifier = await store.verify_oauth_state(
                INTEGRATION_ID, "my_state_string"
            )
            assert is_valid is True
            assert code_verifier is None


class TestMCPTokenStoreDeleteCredentials:
    async def test_deletes_existing(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential()
        ctx_fn, mock_session = _fake_db_session(cred)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.delete_credentials(INTEGRATION_ID)
        mock_session.delete.assert_awaited_once_with(cred)
        mock_session.commit.assert_awaited_once()

    async def test_noop_when_not_found(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.delete_credentials(INTEGRATION_ID)
        mock_session.delete.assert_not_awaited()


class TestMCPTokenStoreIsConnected:
    async def test_true_when_connected(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(status=MCPCredentialStatus.CONNECTED)
        store.get_credential = AsyncMock(return_value=cred)
        assert await store.is_connected(INTEGRATION_ID) is True

    async def test_false_when_pending(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(status=MCPCredentialStatus.PENDING)
        store.get_credential = AsyncMock(return_value=cred)
        assert await store.is_connected(INTEGRATION_ID) is False


class TestMCPTokenStoreDCRClient:
    async def test_get_dcr_client(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(
            client_registration='{"client_id": "dcr_123", "client_secret": "sec"}'
        )
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_dcr_client(INTEGRATION_ID)
        assert result == {"client_id": "dcr_123", "client_secret": "sec"}

    async def test_get_dcr_client_none(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(client_registration=None)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_dcr_client(INTEGRATION_ID)
        assert result is None

    async def test_get_dcr_client_invalid_json(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(client_registration="not_json")
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_dcr_client(INTEGRATION_ID)
        assert result is None

    async def test_store_dcr_client_new(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_dcr_client(INTEGRATION_ID, {"client_id": "c1"})
        added = mock_session.add.call_args[0][0]
        assert json.loads(added.client_registration) == {"client_id": "c1"}
        assert added.status == MCPCredentialStatus.PENDING
        mock_session.commit.assert_awaited_once()

    async def test_store_dcr_client_update(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential()
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_dcr_client(INTEGRATION_ID, {"client_id": "c2"})
        assert json.loads(existing.client_registration) == {"client_id": "c2"}

    async def test_delete_dcr_client(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential(client_registration='{"client_id": "old"}')
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.delete_dcr_client(INTEGRATION_ID)
        assert existing.client_registration is None
        mock_session.commit.assert_awaited_once()

    async def test_delete_dcr_client_noop_when_no_registration(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential(client_registration=None)
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.delete_dcr_client(INTEGRATION_ID)
        mock_session.commit.assert_not_awaited()


class TestMCPTokenStoreOAuthDiscovery:
    async def test_store_and_get_discovery(self):
        store = MCPTokenStore(user_id=USER_ID)
        discovery = _make_oauth_discovery()
        cached: dict[str, Any] = {}

        async def fake_set(key: str, data: Any, ttl: int = 0) -> None:
            cached[key] = data

        async def fake_get(key: str) -> Any:
            return cached.get(key)

        with (
            patch("app.services.mcp.mcp_token_store.set_cache", side_effect=fake_set),
            patch("app.services.mcp.mcp_token_store.get_cache", side_effect=fake_get),
        ):
            await store.store_oauth_discovery(INTEGRATION_ID, discovery)
            result = await store.get_oauth_discovery(INTEGRATION_ID)
            assert result == discovery

    async def test_get_discovery_returns_none_when_empty(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_token_store.get_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await store.get_oauth_discovery(INTEGRATION_ID)
            assert result is None


class TestMCPTokenStoreOAuthNonce:
    async def test_store_and_get_nonce(self):
        store = MCPTokenStore(user_id=USER_ID)
        storage: dict[str, Any] = {}

        async def fake_set(key: str, data: Any, ttl: int = 0) -> None:
            storage[key] = data

        async def fake_get_delete(key: str) -> Any:
            return storage.pop(key, None)

        with (
            patch("app.services.mcp.mcp_token_store.set_cache", side_effect=fake_set),
            patch(
                "app.services.mcp.mcp_token_store.get_and_delete_cache",
                side_effect=fake_get_delete,
            ),
        ):
            await store.store_oauth_nonce(INTEGRATION_ID, "nonce_abc")
            result = await store.get_and_delete_oauth_nonce(INTEGRATION_ID)
            assert result == "nonce_abc"

            # Second call should return None (deleted)
            result2 = await store.get_and_delete_oauth_nonce(INTEGRATION_ID)
            assert result2 is None


class TestMCPTokenStoreIntrospect:
    async def test_introspect_success(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_oauth_discovery = AsyncMock(
            return_value=_make_oauth_discovery(
                metadata_overrides={"introspection_endpoint": "https://auth.example.com/introspect"}
            )
        )
        store.get_oauth_token = AsyncMock(return_value="access_tok")
        with patch(
            "app.services.mcp.mcp_token_store.do_introspect",
            new_callable=AsyncMock,
            return_value={"active": True},
        ):
            result = await store.introspect_token(INTEGRATION_ID)
            assert result == {"active": True}

    async def test_introspect_no_discovery(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_oauth_discovery = AsyncMock(return_value=None)
        result = await store.introspect_token(INTEGRATION_ID)
        assert result is None

    async def test_introspect_no_endpoint(self):
        store = MCPTokenStore(user_id=USER_ID)
        # Discovery with no introspection_endpoint advertised.
        store.get_oauth_discovery = AsyncMock(return_value=_make_oauth_discovery())
        result = await store.introspect_token(INTEGRATION_ID)
        assert result is None

    async def test_introspect_no_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_oauth_discovery = AsyncMock(
            return_value=_make_oauth_discovery(
                metadata_overrides={"introspection_endpoint": "https://e.com/introspect"}
            )
        )
        store.get_oauth_token = AsyncMock(return_value=None)
        result = await store.introspect_token(INTEGRATION_ID)
        assert result is None


class TestMCPTokenStoreStoreUnauthenticated:
    async def test_creates_record_if_missing(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_unauthenticated(INTEGRATION_ID)
        added = mock_session.add.call_args[0][0]
        assert added.user_id == USER_ID
        assert added.integration_id == INTEGRATION_ID
        assert added.auth_type == MCPAuthType.NONE
        assert added.status == MCPCredentialStatus.CONNECTED
        mock_session.commit.assert_awaited_once()

    async def test_skips_if_already_exists(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential()
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_unauthenticated(INTEGRATION_ID)
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()


# ===========================================================================
# Token Management Tests
# ===========================================================================


class TestResolveClientCredentials:
    def test_from_config(self):
        config = _make_mcp_config(client_id="cid", client_secret="csec")
        cid, csec = resolve_client_credentials(config)
        assert cid == "cid"
        assert csec == "csec"

    def test_from_env(self):
        config = _make_mcp_config(client_id_env="MY_CLIENT_ID", client_secret_env="MY_SECRET")
        with patch.dict("os.environ", {"MY_CLIENT_ID": "env_id", "MY_SECRET": "env_s"}):
            cid, csec = resolve_client_credentials(config)
            assert cid == "env_id"
            assert csec == "env_s"

    def test_returns_none_when_not_configured(self):
        config = _make_mcp_config()
        cid, csec = resolve_client_credentials(config)
        assert cid is None
        assert csec is None

    def test_config_takes_precedence(self):
        config = _make_mcp_config(client_id="from_config", client_id_env="MY_ENV_ID")
        with patch.dict("os.environ", {"MY_ENV_ID": "from_env"}):
            cid, _ = resolve_client_credentials(config)
            assert cid == "from_config"


class TestTryRefreshToken:
    async def test_successful_refresh(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config(client_id="cid", client_secret="csec", requires_auth=True)
        oauth_config = _make_oauth_discovery()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)

        assert result is True
        token_store.store_oauth_tokens.assert_awaited_once()

    async def test_no_refresh_token(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value=None)

        result = await try_refresh_token(
            token_store,
            INTEGRATION_ID,
            _make_mcp_config(),
            {"token_endpoint": "https://auth.example.com/token"},
        )
        assert result is False

    # test_no_token_endpoint was deleted: token_endpoint is a required field on
    # the SDK OAuthMetadata/OAuthDiscovery model, so a discovery result without a
    # token_endpoint can no longer be constructed. The "missing token endpoint"
    # case is now structurally impossible and enforced by the model, not this code.

    async def test_no_client_id(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        result = await try_refresh_token(
            token_store,
            INTEGRATION_ID,
            _make_mcp_config(),
            _make_oauth_discovery(),
        )
        assert result is False

    async def test_refresh_http_error(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = _make_oauth_discovery()

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Token expired",
        }

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)
        assert result is False

    async def test_refresh_exception(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = _make_oauth_discovery()

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)
        assert result is False

    async def test_uses_dcr_client_id(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(
            return_value={"client_id": "dcr_cid", "client_secret": "dcr_sec"}
        )
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config()
        oauth_config = _make_oauth_discovery()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_tok",
            "expires_in": 3600,
        }

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)

        assert result is True

    async def test_refresh_returns_false_on_empty_access_token(self):
        # A 200 with an empty access_token must be rejected, not stored as a blank
        # credential (OAuthToken itself permits access_token="").
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.user_id = USER_ID
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config(client_id="cid", requires_auth=True)
        oauth_config = _make_oauth_discovery()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": "", "expires_in": 3600}

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(token_store, INTEGRATION_ID, mcp_config, oauth_config)

        assert result is False
        token_store.store_oauth_tokens.assert_not_awaited()


class TestRevokeTokens:
    async def test_revokes_both_tokens(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_oauth_token = AsyncMock(return_value="access_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = _make_oauth_discovery(
            metadata_overrides={"revocation_endpoint": "https://auth.example.com/revoke"}
        )

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock()
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            await revoke_tokens(token_store, INTEGRATION_ID, mcp_config, oauth_config)

        assert mock_client.post.await_count == 2

    async def test_skips_when_no_endpoint(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        # Discovery with no revocation_endpoint advertised.
        await revoke_tokens(
            token_store, INTEGRATION_ID, _make_mcp_config(), _make_oauth_discovery()
        )
        token_store.get_refresh_token.assert_not_awaited()

    async def test_handles_revocation_error(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="tok")
        token_store.get_oauth_token = AsyncMock(return_value=None)
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = _make_oauth_discovery(
            metadata_overrides={"revocation_endpoint": "https://auth.example.com/revoke"}
        )

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("Network"))
            mock_http.return_value.__aexit__ = AsyncMock()

            # Should not raise
            await revoke_tokens(token_store, INTEGRATION_ID, mcp_config, oauth_config)


# ===========================================================================
# OAuth Discovery Tests
# ===========================================================================


class TestDiscoverOAuthConfig:
    async def test_returns_cached(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        cached = _make_oauth_discovery()
        token_store.get_oauth_discovery = AsyncMock(return_value=cached)

        result = await discover_oauth_config(
            token_store, INTEGRATION_ID, _make_mcp_config(requires_auth=True)
        )
        assert result is cached

    async def test_returns_static_metadata(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)

        metadata = {
            "issuer": "https://auth.com",
            "authorization_endpoint": "https://auth.com/authorize",
            "token_endpoint": "https://auth.com/token",
        }
        config = _make_mcp_config(oauth_metadata=metadata)

        with patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"):
            result = await discover_oauth_config(token_store, INTEGRATION_ID, config)
        assert result.discovery_method == "preconfigured"
        assert str(result.as_metadata.authorization_endpoint) == "https://auth.com/authorize"
        assert str(result.as_metadata.token_endpoint) == "https://auth.com/token"

    async def test_discovery_via_prm(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)
        token_store.store_oauth_discovery = AsyncMock()

        mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new_callable=AsyncMock,
                return_value={
                    "raw": 'Bearer resource_metadata="https://mcp.example.com/.well-known/prm"',
                    "resource_metadata": "https://mcp.example.com/.well-known/prm",
                },
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new_callable=AsyncMock,
                return_value="https://mcp.example.com/.well-known/prm",
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_protected_resource_metadata",
                new_callable=AsyncMock,
                return_value=ProtectedResourceMetadata.model_validate(
                    {
                        "resource": SERVER_URL,
                        "authorization_servers": ["https://auth.example.com"],
                        "scopes_supported": ["read", "write"],
                    }
                ),
            ),
            patch(
                "app.services.mcp.oauth_discovery.select_authorization_server",
                new_callable=MagicMock,
                return_value="https://auth.example.com",
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                return_value=_make_oauth_metadata(
                    registration_endpoint="https://auth.example.com/register",
                ),
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(token_store, INTEGRATION_ID, mcp_config)
        assert result.discovery_method == "rfc9728_prm"
        assert (
            str(result.as_metadata.authorization_endpoint) == "https://auth.example.com/authorize"
        )
        token_store.store_oauth_discovery.assert_awaited_once()

    async def test_fallback_to_direct_oauth(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)
        token_store.store_oauth_discovery = AsyncMock()

        mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new_callable=AsyncMock,
                return_value={},  # No WWW-Authenticate
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                return_value=_make_oauth_metadata(
                    issuer="https://srv.example.com",
                    authorization_endpoint="https://srv.example.com/authorize",
                    token_endpoint="https://srv.example.com/token",
                ),
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(token_store, INTEGRATION_ID, mcp_config)
        assert result.discovery_method == "direct_oauth"
        assert str(result.as_metadata.authorization_endpoint) == "https://srv.example.com/authorize"

    async def test_raises_when_all_discovery_fails(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                side_effect=Exception("Not found"),
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
        ):
            from app.utils.mcp_oauth_utils import OAuthDiscoveryError

            with pytest.raises(OAuthDiscoveryError):
                await discover_oauth_config(token_store, INTEGRATION_ID, mcp_config)

    async def test_uses_challenge_data_when_provided(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)
        token_store.store_oauth_discovery = AsyncMock()

        mcp_config = _make_mcp_config(requires_auth=True)
        challenge_data = {
            "raw": "Bearer",
            "scope": "read",
            "resource_metadata": "https://mcp.example.com/.well-known/prm",
        }

        with (
            patch(
                "app.services.mcp.oauth_discovery.extract_auth_challenge",
                new_callable=AsyncMock,
            ) as mock_extract,
            patch(
                "app.services.mcp.oauth_discovery.find_protected_resource_metadata",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_protected_resource_metadata",
                new_callable=AsyncMock,
                return_value=ProtectedResourceMetadata.model_validate(
                    {
                        "resource": SERVER_URL,
                        "authorization_servers": ["https://auth.example.com"],
                    }
                ),
            ),
            patch(
                "app.services.mcp.oauth_discovery.select_authorization_server",
                new_callable=MagicMock,
                return_value="https://auth.example.com",
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                return_value=_make_oauth_metadata(),
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(
                token_store, INTEGRATION_ID, mcp_config, challenge_data=challenge_data
            )
            # extract_auth_challenge should NOT be called because challenge_data was provided
            mock_extract.assert_not_awaited()
            assert result.initial_scope == "read"


class TestProbeMcpConnection:
    @pytest.fixture(autouse=True)
    def _mock_ssrf_guard(self) -> Iterator[None]:
        """Neutralize the DNS-resolving SSRF guard so tests use fake hostnames."""
        with patch(
            "app.services.mcp.oauth_discovery.assert_public_http_url",
            new_callable=AsyncMock,
        ):
            yield

    async def test_auth_required(self):
        with patch(
            "app.services.mcp.oauth_discovery.extract_auth_challenge",
            new_callable=AsyncMock,
            return_value={"raw": "Bearer realm=..."},
        ):
            result = await probe_mcp_connection(SERVER_URL)
            assert result["requires_auth"] is True
            assert result["auth_type"] == "oauth"

    async def test_no_auth_required(self):
        with patch(
            "app.services.mcp.oauth_discovery.extract_auth_challenge",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await probe_mcp_connection(SERVER_URL)
            assert result["requires_auth"] is False
            assert result["auth_type"] == "none"

    async def test_error_handling(self):
        with patch(
            "app.services.mcp.oauth_discovery.extract_auth_challenge",
            new_callable=AsyncMock,
            side_effect=Exception("Connection refused"),
        ):
            result = await probe_mcp_connection(SERVER_URL)
            assert result["requires_auth"] is False
            assert result["auth_type"] == "unknown"
            assert "Connection refused" in result["error"]


# ===========================================================================
# SanitizingLangChainAdapter Tests
# ===========================================================================


class TestSanitizingLangChainAdapter:
    def test_fix_schema_strips_underscores(self):
        adapter = SanitizingLangChainAdapter()
        schema = {
            "type": "object",
            "properties": {
                "_postman_id": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["_postman_id", "name"],
        }
        fixed = adapter.fix_schema(schema)
        assert "postman_id" in fixed["properties"]
        assert "_postman_id" not in fixed["properties"]
        assert "postman_id" in fixed["required"]

    def test_fix_schema_handles_type_array(self):
        adapter = SanitizingLangChainAdapter()
        schema = {"type": ["string", "null"]}
        fixed = adapter.fix_schema(schema)
        assert "anyOf" in fixed
        assert "type" not in fixed

    def test_fix_schema_adds_type_for_enum(self):
        adapter = SanitizingLangChainAdapter()
        schema = {"enum": ["a", "b", "c"]}
        fixed = adapter.fix_schema(schema)
        assert fixed["type"] == "string"

    def test_fix_schema_recursive_list(self):
        adapter = SanitizingLangChainAdapter()
        schema = [{"type": ["integer", "null"]}, {"enum": ["x"]}]
        fixed = adapter.fix_schema(schema)
        assert isinstance(fixed, list)
        assert "anyOf" in fixed[0]
        assert fixed[1]["type"] == "string"

    def test_fix_schema_numeric_underscore_prefix(self):
        adapter = SanitizingLangChainAdapter()
        schema = {
            "type": "object",
            "properties": {
                "_123field": {"type": "number"},
            },
        }
        fixed = adapter.fix_schema(schema)
        # Stripped underscores, starts with digit -> prefixed with "field"
        assert "field123field" in fixed["properties"]

    def test_fix_schema_passthrough_non_dict(self):
        adapter = SanitizingLangChainAdapter()
        assert adapter.fix_schema("string_value") == "string_value"
        assert adapter.fix_schema(42) == 42

    def test_fix_schema_nested_properties(self):
        adapter = SanitizingLangChainAdapter()
        schema = {
            "type": "object",
            "properties": {
                "nested": {
                    "type": "object",
                    "properties": {
                        "_inner": {"type": "string"},
                    },
                }
            },
        }
        fixed = adapter.fix_schema(schema)
        nested = fixed["properties"]["nested"]
        assert "inner" in nested["properties"]

    def test_fix_schema_no_properties_recursion(self):
        adapter = SanitizingLangChainAdapter()
        schema = {
            "type": "object",
            "items": {"type": ["string", "null"]},
        }
        fixed = adapter.fix_schema(schema)
        assert "anyOf" in fixed["items"]


# ===========================================================================
# ResilientLangChainAdapter Tests
# ===========================================================================


class TestResilientLangChainAdapter:
    async def test_create_tools_no_sessions(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_client.get_all_active_sessions.return_value = {}
        result = await adapter.create_tools(mock_client)
        assert result == []

    async def test_create_tools_no_mcp_tools(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()
        mock_connector.list_tools = AsyncMock(return_value=[])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}
        result = await adapter.create_tools(mock_client)
        assert result == []

    async def test_create_tools_skips_bad_schemas(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()

        good_tool = MagicMock()
        good_tool.name = "good_tool"
        good_tool.meta = None
        good_tool._meta = None

        bad_tool = MagicMock()
        bad_tool.name = "bad_tool"
        bad_tool.meta = None
        bad_tool._meta = None

        mock_connector.list_tools = AsyncMock(return_value=[good_tool, bad_tool])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        good_lc_tool = _mock_tool("good_tool")
        good_lc_tool.metadata = None

        call_count = 0

        async def mock_convert(tool, connector):
            nonlocal call_count
            call_count += 1
            if tool.name == "bad_tool":
                raise Exception("Invalid schema")
            return good_lc_tool

        adapter._convert_single_tool = mock_convert

        with patch(
            "app.services.mcp.resilient_adapter.patch_tool_schema",
            side_effect=lambda t: t,
        ):
            result = await adapter.create_tools(mock_client)

        assert len(result) == 1
        assert result[0].name == "good_tool"

    async def test_create_tools_raises_when_all_fail(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()

        tool1 = MagicMock()
        tool1.name = "t1"
        tool2 = MagicMock()
        tool2.name = "t2"

        mock_connector.list_tools = AsyncMock(return_value=[tool1, tool2])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        async def always_fail(tool, connector):
            raise Exception("Schema error")

        adapter._convert_single_tool = always_fail

        with patch(
            "app.services.mcp.resilient_adapter.patch_tool_schema",
            side_effect=lambda t: t,
        ):
            with pytest.raises(ValueError, match="Failed to convert any tools"):
                await adapter.create_tools(mock_client)

    async def test_create_tools_attaches_mcp_ui_metadata(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()

        mcp_tool = MagicMock()
        mcp_tool.name = "ui_tool"
        mcp_tool.meta = {"ui": {"resourceUri": "ui://tool/app.html", "csp": "strict"}}
        mcp_tool._meta = None

        mock_connector.list_tools = AsyncMock(return_value=[mcp_tool])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        lc_tool = MagicMock(spec=BaseTool)
        lc_tool.name = "ui_tool"
        lc_tool.metadata = None

        async def mock_convert(tool, connector):
            return lc_tool

        adapter._convert_single_tool = mock_convert

        with patch(
            "app.services.mcp.resilient_adapter.patch_tool_schema",
            side_effect=lambda t: t,
        ):
            result = await adapter.create_tools(mock_client)

        assert len(result) == 1
        assert result[0].metadata is not None
        assert "mcp_ui" in result[0].metadata
        assert result[0].metadata["mcp_ui"]["resource_uri"] == "ui://tool/app.html"
        assert result[0].metadata["mcp_ui"]["csp"] == "strict"

    async def test_create_tools_handles_normalize_error(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()

        tool = MagicMock()
        tool.name = "problematic"
        tool.meta = None
        tool._meta = None

        mock_connector.list_tools = AsyncMock(return_value=[tool])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        lc_tool = _mock_tool("problematic")
        lc_tool.metadata = None

        async def mock_convert(t, c):
            return lc_tool

        adapter._convert_single_tool = mock_convert

        with patch(
            "app.services.mcp.resilient_adapter.patch_tool_schema",
            side_effect=Exception("Normalize error"),
        ):
            # Should still use the original tool
            result = await adapter.create_tools(mock_client)
            assert len(result) == 1

    async def test_create_tools_legacy_flat_meta(self):
        """Test extraction of UI metadata from legacy flat _meta key."""
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()

        mcp_tool = MagicMock()
        mcp_tool.name = "legacy_tool"
        mcp_tool.meta = None
        mcp_tool._meta = {"ui/resourceUri": "ui://legacy/app.html", "ui": {}}

        mock_connector.list_tools = AsyncMock(return_value=[mcp_tool])
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        lc_tool = MagicMock(spec=BaseTool)
        lc_tool.name = "legacy_tool"
        lc_tool.metadata = None

        async def mock_convert(t, c):
            return lc_tool

        adapter._convert_single_tool = mock_convert

        with patch(
            "app.services.mcp.resilient_adapter.patch_tool_schema",
            side_effect=lambda t: t,
        ):
            result = await adapter.create_tools(mock_client)

        assert len(result) == 1
        assert result[0].metadata is not None
        assert result[0].metadata["mcp_ui"]["resource_uri"] == "ui://legacy/app.html"

    async def test_convert_single_tool_calls_parent(self):
        adapter = ResilientLangChainAdapter()
        mcp_tool = MagicMock()
        connector = MagicMock()
        expected = _mock_tool("converted")

        adapter._convert_tool = MagicMock(return_value=expected)
        result = await adapter._convert_single_tool(mcp_tool, connector)
        assert result is expected
        adapter._convert_tool.assert_called_once_with(mcp_tool, connector)

    async def test_create_tools_list_tools_failure(self):
        adapter = ResilientLangChainAdapter()
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_connector = AsyncMock()
        mock_connector.list_tools = AsyncMock(side_effect=Exception("Server error"))
        mock_session.connector = mock_connector
        mock_client.get_all_active_sessions.return_value = {"int1": mock_session}

        with pytest.raises(Exception, match="Server error"):
            await adapter.create_tools(mock_client)


# ===========================================================================
# MCPClient Register Client (DCR) Tests
# ===========================================================================


class TestMCPClientRegisterClient:
    async def test_successful_registration(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.store_dcr_client = AsyncMock()

        as_metadata = _make_oauth_metadata(
            registration_endpoint="https://auth.example.com/register"
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        # handle_registration_response reads the body via aread() and validates it
        # as OAuthClientInformationFull (redirect_uris required).
        mock_response.aread = AsyncMock(
            return_value=json.dumps(
                {
                    "client_id": "new_client_id",
                    "redirect_uris": ["https://myapp.com/callback"],
                }
            ).encode()
        )

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_http_client = AsyncMock()
            mock_http_client.send = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await client._register_client(
                INTEGRATION_ID,
                as_metadata,
                "https://myapp.com/callback",
            )

        assert result == "new_client_id"
        client.token_store.store_dcr_client.assert_awaited_once()

    async def test_dcr_not_supported_403(self):
        client = MCPClient(user_id=USER_ID)
        as_metadata = _make_oauth_metadata(
            registration_endpoint="https://auth.example.com/register"
        )

        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_http_client = AsyncMock()
        mock_http_client.send = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedError):
                await client._register_client(
                    INTEGRATION_ID,
                    as_metadata,
                    "https://myapp.com/callback",
                )

    async def test_dcr_not_supported_404(self):
        client = MCPClient(user_id=USER_ID)
        as_metadata = _make_oauth_metadata(
            registration_endpoint="https://auth.example.com/register"
        )

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_http_client = AsyncMock()
        mock_http_client.send = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedError):
                await client._register_client(
                    INTEGRATION_ID,
                    as_metadata,
                    "https://myapp.com/callback",
                )

    async def test_dcr_not_supported_405(self):
        client = MCPClient(user_id=USER_ID)
        as_metadata = _make_oauth_metadata(
            registration_endpoint="https://auth.example.com/register"
        )

        mock_response = MagicMock()
        mock_response.status_code = 405

        mock_http_client = AsyncMock()
        mock_http_client.send = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedError):
                await client._register_client(
                    INTEGRATION_ID,
                    as_metadata,
                    "https://myapp.com/callback",
                )

    async def test_dcr_other_error(self):
        client = MCPClient(user_id=USER_ID)
        as_metadata = _make_oauth_metadata(
            registration_endpoint="https://auth.example.com/register"
        )

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(side_effect=Exception("Network error"))
            mock_http.return_value.__aexit__ = AsyncMock()

            with pytest.raises(ValueError, match="Dynamic Client Registration failed"):
                await client._register_client(
                    INTEGRATION_ID,
                    as_metadata,
                    "https://myapp.com/callback",
                )


# ===========================================================================
# MCPClient Session-based operations Tests
# ===========================================================================


class TestMCPClientListResourcesOnServer:
    async def test_list_resources(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(
            return_value=ListResourcesResult(
                resources=[Resource(uri=AnyUrl("file://r1"), name="r1")]
            )
        )
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resources_on_server(SERVER_URL)
        assert [r.name for r in result.resources] == ["r1"]

    async def test_list_resources_with_cursor(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.list_resources = AsyncMock(return_value=ListResourcesResult(resources=[]))
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resources_on_server(SERVER_URL, cursor="next_page")
        assert result.resources == []
        mock_session.list_resources.assert_awaited_once_with(cursor="next_page")


class TestMCPClientReadResourceOnServer:
    async def test_read_resource(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(
            return_value=ReadResourceResult(
                contents=[
                    TextResourceContents(uri=AnyUrl("file://test.txt"), text="hello"),
                ]
            )
        )
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.read_resource_on_server(SERVER_URL, "file://test.txt")
        assert result.contents[0].text == "hello"


class TestMCPClientListPromptsOnServer:
    async def test_list_prompts(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.list_prompts = AsyncMock(return_value=ListPromptsResult(prompts=[]))
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_prompts_on_server(SERVER_URL)
        assert result.prompts == []


class TestMCPClientReadUiResource:
    async def test_read_ui_resource_success(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()

        content = MagicMock()
        content.text = "<html>Hello</html>"
        content._meta = None
        content.meta = None

        mock_result = MagicMock()
        mock_result.contents = [content]
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_base.get_session = MagicMock(return_value=mock_session)

        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is not None
        assert result["html"] == "<html>Hello</html>"

    async def test_read_ui_resource_no_matching_integration(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=None)
        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_timeout(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(side_effect=TimeoutError())
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()
        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_with_meta(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()

        content = MagicMock()
        content.text = "<html>App</html>"
        content._meta = {"ui": {"csp": "strict", "permissions": ["clipboard"]}}
        content.meta = None

        mock_result = MagicMock()
        mock_result.contents = [content]
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_base.get_session = MagicMock(return_value=mock_session)

        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is not None
        assert result["html"] == "<html>App</html>"
        assert result["csp"] == "strict"
        assert result["permissions"] == ["clipboard"]

    async def test_read_ui_resource_no_text_content(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()

        content = MagicMock()
        content.text = None  # No text attribute

        mock_result = MagicMock()
        mock_result.contents = [content]
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        mock_base.get_session = MagicMock(return_value=mock_session)

        client._clients[INTEGRATION_ID] = mock_base
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_exception(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.read_resource = AsyncMock(side_effect=Exception("Server error"))
        mock_base.get_session = MagicMock(return_value=mock_session)

        client._clients[INTEGRATION_ID] = mock_base
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_no_client(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()
        # No client in _clients

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None


# ===========================================================================
# MCPClient _find_integration_id_by_server_url Tests
# ===========================================================================


class TestMCPClientFindIntegrationIdByServerUrl:
    async def test_finds_from_active_clients(self):
        client = MCPClient(user_id=USER_ID)
        client._clients[INTEGRATION_ID] = MagicMock()

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await client._find_integration_id_by_server_url(SERVER_URL)

        assert result == INTEGRATION_ID

    async def test_finds_from_db_integrations(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[
                    {"integration_id": "db_int", "status": "connected"},
                ],
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await client._find_integration_id_by_server_url(SERVER_URL)

        assert result == "db_int"

    async def test_returns_none_for_empty_url(self):
        client = MCPClient(user_id=USER_ID)
        result = await client._find_integration_id_by_server_url("")
        assert result is None

    async def test_returns_none_when_no_match(self):
        client = MCPClient(user_id=USER_ID)
        with (
            patch(
                "app.services.mcp.mcp_client.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await client._find_integration_id_by_server_url("https://unknown.example.com")
        assert result is None

    async def test_skips_non_connected_db_integrations(self):
        client = MCPClient(user_id=USER_ID)
        with (
            patch(
                "app.services.mcp.mcp_client.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[
                    {"integration_id": "pending_int", "status": "created"},
                ],
            ),
        ):
            result = await client._find_integration_id_by_server_url(SERVER_URL)
        assert result is None

    async def test_handles_db_error(self):
        client = MCPClient(user_id=USER_ID)
        with (
            patch(
                "app.services.mcp.mcp_client.get_user_integration_records",
                new_callable=AsyncMock,
                side_effect=Exception("DB error"),
            ),
            patch("app.services.mcp.mcp_client.log"),
        ):
            result = await client._find_integration_id_by_server_url(SERVER_URL)
        assert result is None

    async def test_skips_resolve_errors(self):
        client = MCPClient(user_id=USER_ID)
        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.get_user_integration_records",
                new_callable=AsyncMock,
                return_value=[
                    {"integration_id": "err_int", "status": "connected"},
                ],
            ),
        ):
            mock_resolver.resolve = AsyncMock(side_effect=Exception("Resolve error"))
            result = await client._find_integration_id_by_server_url(SERVER_URL)
        assert result is None


# ===========================================================================
# MCPClient _safe_close_client Tests
# ===========================================================================


class TestMCPClientSafeCloseClient:
    async def test_closes_successfully(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = AsyncMock()
        await client._safe_close_client(mock_base)
        mock_base.close_all_sessions.assert_awaited_once()

    async def test_swallows_error(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = AsyncMock()
        mock_base.close_all_sessions = AsyncMock(side_effect=Exception("err"))
        # Should not raise
        await client._safe_close_client(mock_base)


# ===========================================================================
# MCPClient _revoke_tokens Tests
# ===========================================================================


class TestMCPClientRevokeTokens:
    async def test_revokes_when_oauth_config_exists(self):
        client = MCPClient(user_id=USER_ID)
        oauth_config = _make_oauth_discovery(
            metadata_overrides={"revocation_endpoint": "https://auth.example.com/revoke"}
        )
        client.token_store.get_oauth_discovery = AsyncMock(return_value=oauth_config)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.revoke_tokens",
                new_callable=AsyncMock,
            ) as mock_revoke,
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            await client._revoke_tokens(INTEGRATION_ID)

        mock_revoke.assert_awaited_once()

    async def test_skips_when_no_oauth_config(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.get_oauth_discovery = AsyncMock(return_value=None)

        with patch(
            "app.services.mcp.mcp_client.revoke_tokens",
            new_callable=AsyncMock,
        ) as mock_revoke:
            await client._revoke_tokens(INTEGRATION_ID)

        mock_revoke.assert_not_awaited()

    async def test_handles_exception(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.get_oauth_discovery = AsyncMock(side_effect=Exception("err"))
        # Should not raise
        await client._revoke_tokens(INTEGRATION_ID)


# ===========================================================================
# MCPClient _get_session_for_server Tests
# ===========================================================================


class TestMCPClientGetSessionForServer:
    async def test_returns_session(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        # Production unwraps mcp_use's wrapper to the underlying official SDK
        # ClientSession: client.get_session(id).connector.client_session.
        mock_session = MagicMock()
        mock_base.get_session.return_value.connector.client_session = mock_session
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()

        result = await client._get_session_for_server(SERVER_URL)
        assert result is mock_session

    async def test_raises_when_no_matching_integration(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="No connected MCP integration"):
            await client._get_session_for_server(SERVER_URL)

    async def test_raises_when_client_not_in_memory(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock()
        # No client in _clients

        with pytest.raises(ValueError, match="not connected in memory"):
            await client._get_session_for_server(SERVER_URL)


# ===========================================================================
# MCPClient list_resource_templates_on_server Tests
# ===========================================================================


class TestMCPClientListResourceTemplatesOnServer:
    async def test_list_templates(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.list_resource_templates = AsyncMock(
            return_value=ListResourceTemplatesResult(
                resourceTemplates=[ResourceTemplate(uriTemplate="file://{p}", name="t1")]
            )
        )
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resource_templates_on_server(SERVER_URL)
        assert [t.name for t in result.resourceTemplates] == ["t1"]

    async def test_list_templates_with_cursor(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_session.list_resource_templates = AsyncMock(
            return_value=ListResourceTemplatesResult(resourceTemplates=[])
        )
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resource_templates_on_server(SERVER_URL, cursor="page2")
        assert result.resourceTemplates == []
        mock_session.list_resource_templates.assert_awaited_once_with(cursor="page2")

    # test_list_templates_without_model_dump was deleted: _get_session_for_server
    # now returns the underlying official SDK ClientSession, whose list ops always
    # return typed *Result models with .model_dump(). The bare-dict fallback this
    # test exercised was removed in the SDK migration, so the path no longer exists.


# ===========================================================================
# MCPClient build_oauth_auth_url Tests
# ===========================================================================


class TestMCPClientBuildOauthAuthUrl:
    async def test_builds_auth_url_with_preconfigured_client(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True, client_id="my_client", oauth_scopes=["read"]
        )

        oauth_config = _make_oauth_discovery(
            metadata_overrides={"scopes_supported": ["read", "write"]}
        )

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch(
                "app.services.mcp.mcp_client.validate_pkce_support",
            ),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(
                    code_verifier="verifier_123", code_challenge="challenge_456"
                ),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state_abc")

            url = await client.build_oauth_auth_url(
                INTEGRATION_ID,
                "https://myapp.com/callback",
            )

        assert "https://auth.example.com/authorize" in url
        assert "client_id=my_client" in url
        assert "code_challenge=challenge_456" in url
        assert "state=" in url

    async def test_raises_when_integration_not_found(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=None)
            with pytest.raises(ValueError, match="not found"):
                await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

    async def test_raises_when_no_client_id(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        # No registration_endpoint => DCR fallback unavailable, so client_id
        # cannot be obtained from any source.
        oauth_config = _make_oauth_discovery()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.get_dcr_client = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Could not obtain client_id"):
                await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

    async def test_uses_dcr_client_id(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        oauth_config = _make_oauth_discovery()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch(
                "app.services.mcp.mcp_client.validate_pkce_support",
            ),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(code_verifier="v", code_challenge="c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.get_dcr_client = AsyncMock(return_value={"client_id": "dcr_id"})
            client.token_store.create_oauth_state = AsyncMock(return_value="state")

            url = await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

        assert "client_id=dcr_id" in url

    # test_raises_when_no_auth_endpoint was deleted: authorization_endpoint is a
    # required field on the SDK OAuthMetadata model, so a discovery result lacking
    # it can no longer be constructed. The "missing authorization_endpoint" guard
    # was removed from build_oauth_auth_url; the constraint is now enforced by the
    # model at discovery time.

    async def test_adds_nonce_for_openid_scope(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True,
            client_id="cid",
            oauth_scopes=["openid", "profile"],
        )

        oauth_config = _make_oauth_discovery()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(code_verifier="v", code_challenge="c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")
            client.token_store.store_oauth_nonce = AsyncMock()

            url = await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

        assert "nonce=" in url
        client.token_store.store_oauth_nonce.assert_awaited_once()

    async def test_adds_offline_access_when_supported(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True,
            client_id="cid",
            oauth_scopes=["read"],
        )

        oauth_config = _make_oauth_discovery(
            metadata_overrides={"scopes_supported": ["read", "offline_access"]}
        )

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(code_verifier="v", code_challenge="c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")

            url = await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

        assert "offline_access" in url


# ===========================================================================
# MCPClient handle_oauth_callback Tests
# ===========================================================================


class TestMCPClientHandleOauthCallback:
    async def test_raises_on_invalid_state(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(return_value=(False, None))

        with pytest.raises(ValueError, match="Invalid OAuth state"):
            await client.handle_oauth_callback(
                INTEGRATION_ID, "code", "bad_state", "https://callback.com"
            )

    async def test_raises_when_integration_not_found(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(return_value=(True, "verifier"))

        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=None)
            with pytest.raises(ValueError, match="not found"):
                await client.handle_oauth_callback(
                    INTEGRATION_ID, "code", "state", "https://callback.com"
                )

    # test_raises_when_no_token_endpoint was deleted: token_endpoint is a required
    # field on the SDK OAuthMetadata model, so a discovery result without it can no
    # longer be constructed. The "No token_endpoint" guard was removed from
    # handle_oauth_callback; the constraint is now enforced by the model.

    async def test_raises_when_no_client_id_for_exchange(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(return_value=(True, "verifier"))

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=_make_oauth_discovery(),
            ),
            patch("app.services.mcp.mcp_client.validate_https_url"),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.get_dcr_client = AsyncMock(return_value=None)

            with pytest.raises(ValueError, match="Could not resolve client_id"):
                await client.handle_oauth_callback(
                    INTEGRATION_ID, "code", "state", "https://callback.com"
                )

    async def test_raises_on_token_exchange_error(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(return_value=(True, "verifier"))

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True, client_id="cid")

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Code expired",
        }
        mock_response.text = "error"

        @asynccontextmanager
        async def fake_http_client():
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            yield mock_http_client

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=_make_oauth_discovery(),
            ),
            patch("app.services.mcp.mcp_client.validate_https_url"),
            patch(
                "app.services.mcp.mcp_client.parse_oauth_error_response",
                return_value={
                    "error": "invalid_grant",
                    "error_description": "Code expired",
                },
            ),
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=fake_http_client(),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)

            with pytest.raises(ValueError, match="Token exchange failed"):
                await client.handle_oauth_callback(
                    INTEGRATION_ID, "code", "state", "https://callback.com"
                )


# ===========================================================================
# MCPClient _handle_custom_integration_connect Tests
# ===========================================================================


class TestMCPClientHandleCustomIntegrationConnect:
    async def test_indexes_tools_and_subagent(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        with (
            patch(
                "app.services.mcp.mcp_client.derive_integration_namespace",
                return_value="ns::custom",
            ),
            patch(
                "app.services.mcp.mcp_client.index_tools_to_store",
                new_callable=AsyncMock,
            ) as mock_index,
            patch("app.services.mcp.mcp_client.providers") as mock_providers,
        ):
            mock_store = MagicMock()
            mock_providers.aget = AsyncMock(return_value=mock_store)

            # Mock the local import
            with patch(
                "app.agents.core.subagents.handoff_tools.index_custom_mcp_as_subagent",
                new_callable=AsyncMock,
            ) as mock_subagent:
                await client._handle_custom_integration_connect(
                    INTEGRATION_ID,
                    SERVER_URL,
                    tools,
                    name="My Tool",
                    description="A custom tool",
                )

            mock_index.assert_awaited_once()
            mock_subagent.assert_awaited_once()

    async def test_handles_index_error(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        with (
            patch(
                "app.services.mcp.mcp_client.derive_integration_namespace",
                return_value="ns",
            ),
            patch(
                "app.services.mcp.mcp_client.index_tools_to_store",
                new_callable=AsyncMock,
                side_effect=Exception("Index error"),
            ),
            patch("app.services.mcp.mcp_client.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=None)
            # Should not raise
            await client._handle_custom_integration_connect(INTEGRATION_ID, SERVER_URL, tools)

    async def test_the_indexed_request_carries_the_integrations_identity_verbatim(self):
        """The subagent entry is what a handoff later resolves the integration by,
        so every field of the request is pinned: a dropped server_url or tool list
        indexes a subagent that ranks for nothing and routes nowhere."""
        from app.agents.core.subagents.handoff_tools import (
            CustomMcpIndexRequest,
        )

        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        with (
            patch(
                "app.services.mcp.mcp_client.derive_integration_namespace",
                return_value="ns::custom",
            ),
            patch("app.services.mcp.mcp_client.index_tools_to_store", new_callable=AsyncMock),
            patch("app.services.mcp.mcp_client.providers") as mock_providers,
        ):
            mock_store = MagicMock()
            mock_providers.aget = AsyncMock(return_value=mock_store)

            with patch(
                "app.agents.core.subagents.handoff_tools.index_custom_mcp_as_subagent",
                new_callable=AsyncMock,
            ) as mock_subagent:
                await client._handle_custom_integration_connect(
                    INTEGRATION_ID,
                    SERVER_URL,
                    tools,
                    name="My Tool",
                    description="A custom tool",
                )

        mock_subagent.assert_awaited_once()
        assert mock_subagent.await_args.kwargs["store"] is mock_store
        assert mock_subagent.await_args.kwargs["request"] == CustomMcpIndexRequest(
            integration_id=INTEGRATION_ID,
            name="My Tool",
            description="A custom tool",
            server_url=SERVER_URL,
            tools=tools,
        )

    async def test_an_integration_with_no_description_indexes_an_empty_one(self):
        """The request's description is a plain ``str``; a missing one becomes the
        empty string rather than travelling as None into the embedded text."""
        from app.agents.core.subagents.handoff_tools import (
            CustomMcpIndexRequest,
        )

        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        with (
            patch(
                "app.services.mcp.mcp_client.derive_integration_namespace",
                return_value="ns::custom",
            ),
            patch("app.services.mcp.mcp_client.index_tools_to_store", new_callable=AsyncMock),
            patch("app.services.mcp.mcp_client.providers") as mock_providers,
        ):
            mock_providers.aget = AsyncMock(return_value=MagicMock())

            with patch(
                "app.agents.core.subagents.handoff_tools.index_custom_mcp_as_subagent",
                new_callable=AsyncMock,
            ) as mock_subagent:
                await client._handle_custom_integration_connect(
                    INTEGRATION_ID, SERVER_URL, tools, name="My Tool", description=None
                )

        assert mock_subagent.await_args.kwargs["request"] == CustomMcpIndexRequest(
            integration_id=INTEGRATION_ID,
            name="My Tool",
            description="",
            server_url=SERVER_URL,
            tools=tools,
        )

    async def test_resolves_name_from_integration_when_not_provided(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]

        resolved = MagicMock()
        resolved.custom_doc = {"name": "Resolved Name", "description": "Resolved Desc"}

        with (
            patch(
                "app.services.mcp.mcp_client.derive_integration_namespace",
                return_value="ns",
            ),
            patch(
                "app.services.mcp.mcp_client.index_tools_to_store",
                new_callable=AsyncMock,
            ),
            patch("app.services.mcp.mcp_client.providers") as mock_providers,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
        ):
            mock_store = MagicMock()
            mock_providers.aget = AsyncMock(return_value=mock_store)
            mock_resolver.resolve = AsyncMock(return_value=resolved)

            with patch(
                "app.agents.core.subagents.handoff_tools.index_custom_mcp_as_subagent",
                new_callable=AsyncMock,
            ) as mock_subagent:
                await client._handle_custom_integration_connect(
                    INTEGRATION_ID, SERVER_URL, tools, name=None
                )

            mock_subagent.assert_awaited_once()
            call_kwargs = mock_subagent.call_args[1]
            assert call_kwargs["request"].name == "Resolved Name"


# ===========================================================================
# MCPClient call_tool_on_server - additional branch coverage
# ===========================================================================


class TestMCPClientCallToolOnServerAdditional:
    async def test_call_tool_surfaces_server_error_flag(self):
        """A tool result flagged isError comes back with the flag intact."""
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(
            return_value=CallToolResult(
                content=[TextContent(type="text", text="boom")], isError=True
            )
        )
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        client._find_integration_id_by_server_url = AsyncMock(return_value=INTEGRATION_ID)
        client.ensure_connected = AsyncMock(return_value=[_mock_tool()])

        result = await client.call_tool_on_server(SERVER_URL, "test_tool", {"arg": "val"})
        assert result.isError is True
        assert result.content[0].text == "boom"


class TestMCPClientDoConnectSSRF:
    """The connect path must run the real SSRF guard (no autouse mock here).

    Regression fence for the connect-time DNS-rebinding re-check: a config whose
    server_url points at the cloud-metadata / a private address must be refused
    *before* any MCP client is constructed or any outbound connection is made.
    """

    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    async def test_private_server_url_blocked_before_connect(
        self, mock_resolver, mock_base_client_cls
    ):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(server_url="https://169.254.169.254/mcp")
        resolved.source = "platform"
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        client = MCPClient(user_id=USER_ID)

        with pytest.raises(ValueError, match="non-public"):
            await client._do_connect(INTEGRATION_ID)

        # The guard fired first: no outbound MCP client was ever built.
        mock_base_client_cls.assert_not_called()

    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    async def test_loopback_server_url_blocked_before_connect(
        self, mock_resolver, mock_base_client_cls
    ):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(server_url="https://127.0.0.1:8000/mcp")
        resolved.source = "platform"
        resolved.custom_doc = None
        mock_resolver.resolve = AsyncMock(return_value=resolved)

        client = MCPClient(user_id=USER_ID)

        with pytest.raises(ValueError, match="non-public"):
            await client._do_connect(INTEGRATION_ID)

        mock_base_client_cls.assert_not_called()


class TestProbeMcpConnectionSSRF:
    """probe_mcp_connection must run the real SSRF guard before probing."""

    @patch("app.services.mcp.oauth_discovery.extract_auth_challenge", new_callable=AsyncMock)
    async def test_private_url_is_refused_without_probing(self, mock_extract):
        result = await probe_mcp_connection("https://169.254.169.254/mcp")

        # The guard rejected it: surfaced as an error, and no outbound probe ran.
        assert result["auth_type"] == "unknown"
        assert result["requires_auth"] is False
        assert "error" in result
        mock_extract.assert_not_awaited()


# ===========================================================================
# Mutation-hardening: exact assertions on log writes, dict-key writes,
# outbound HTTP args, and raised exceptions
# ===========================================================================


def _make_id_token(payload: dict[str, Any]) -> str:
    """Build an unsigned JWT whose payload decodes exactly like a real id_token."""

    def b64(part: bytes) -> str:
        return base64.urlsafe_b64encode(part).decode().rstrip("=")

    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = b64(json.dumps(payload).encode())
    return f"{header}.{body}.sig"


def _fake_http_client(post_mock: AsyncMock):
    @asynccontextmanager
    async def _ctx():
        mock_http_client = AsyncMock()
        mock_http_client.post = post_mock
        yield mock_http_client

    return _ctx


def _ok_response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = body
    return response


class TestStampToolMetadataExact:
    def test_ui_tool_gets_server_url_and_every_tool_gets_integration_id(self):
        ui_tool = _mock_tool("ui_tool")
        ui_tool.metadata = {"mcp_ui": {"csp": "default-src 'self'"}}
        plain_tool = _mock_tool("plain_tool")
        plain_tool.metadata = None

        MCPClient._stamp_tool_metadata([ui_tool, plain_tool], INTEGRATION_ID, SERVER_URL)

        assert ui_tool.metadata == {
            "mcp_ui": {"csp": "default-src 'self'"},
            "mcp_server_url": SERVER_URL,
            "integration_id": INTEGRATION_ID,
        }
        assert plain_tool.metadata == {"integration_id": INTEGRATION_ID}

    def test_non_ui_tool_never_gets_server_url(self):
        tool = _mock_tool()
        tool.metadata = {}

        MCPClient._stamp_tool_metadata([tool], INTEGRATION_ID, SERVER_URL)

        assert tool.metadata == {"integration_id": INTEGRATION_ID}


class TestOpenSessionExact:
    async def test_device_transport_delegates_to_device_client_and_skips_ssrf_check(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(
            server_url="device://dev-1/filesystem", transport=DEVICE_TRANSPORT
        )
        device_client = AsyncMock()
        with (
            patch.object(
                client, "_build_device_client", new_callable=AsyncMock, return_value=device_client
            ) as mock_build_device,
            patch(
                "app.services.mcp.mcp_client.assert_public_http_url", new_callable=AsyncMock
            ) as mock_ssrf,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            result = await client._open_session(INTEGRATION_ID, mcp_config)

        assert result is device_client
        mock_build_device.assert_awaited_once_with(INTEGRATION_ID, mcp_config)
        mock_ssrf.assert_not_awaited()
        mock_log.info.assert_called_once_with(
            f"{LogTag.MCP} Opening device-tunnel MCP session", integration_id=INTEGRATION_ID
        )

    async def test_http_path_validates_url_then_builds_config_then_opens_session(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        config = {"mcpServers": {INTEGRATION_ID: {"url": SERVER_URL}}}
        base_client = AsyncMock()

        call_order: list[str] = []

        async def _record_ssrf(url: str) -> None:
            call_order.append("ssrf")

        async def _record_build(iid: str, cfg: MCPConfig) -> dict[str, Any]:
            call_order.append("build_config")
            return config

        with (
            patch(
                "app.services.mcp.mcp_client.assert_public_http_url",
                new_callable=AsyncMock,
                side_effect=_record_ssrf,
            ),
            patch.object(client, "_build_config", side_effect=_record_build),
            patch.object(client, "_sanitize_config", return_value={"sanitized": True}),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient", return_value=base_client
            ) as mock_cls,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            result = await client._open_session(INTEGRATION_ID, mcp_config)

        assert result is base_client
        # The DNS-rebinding re-check must run before _build_config (which can do outbound I/O).
        assert call_order == ["ssrf", "build_config"]
        mock_cls.assert_called_once_with(config)
        base_client.create_session.assert_awaited_once_with(INTEGRATION_ID)
        mock_log.info.assert_any_call(
            f"{LogTag.MCP} Starting connection to MCP server",
            integration_id=INTEGRATION_ID,
            config={"sanitized": True},
        )


class TestConvertToolsSafeExact:
    async def test_success_returns_raw_tools_and_logs_exact_count(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool("a"), _mock_tool("b")]
        adapter = AsyncMock()
        adapter.create_tools = AsyncMock(return_value=tools)
        fake_client = AsyncMock()
        with (
            patch("app.services.mcp.mcp_client.ResilientLangChainAdapter", return_value=adapter),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            result = await client._convert_tools_safe(fake_client, INTEGRATION_ID)

        assert result is tools
        adapter.create_tools.assert_awaited_once_with(fake_client)
        fake_client.close_all_sessions.assert_not_awaited()
        mock_log.info.assert_any_call(
            f"{LogTag.MCP} Successfully converted tools to LangChain format",
            integration_id=INTEGRATION_ID,
            raw_tools_count=2,
        )

    async def test_failure_closes_sessions_and_reraises_original_exception(self):
        client = MCPClient(user_id=USER_ID)
        err = RuntimeError("Schema error")
        adapter = AsyncMock()
        adapter.create_tools = AsyncMock(side_effect=err)
        fake_client = AsyncMock()
        with (
            patch("app.services.mcp.mcp_client.ResilientLangChainAdapter", return_value=adapter),
            patch("app.services.mcp.mcp_client.log"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await client._convert_tools_safe(fake_client, INTEGRATION_ID)

        assert exc_info.value is err
        fake_client.close_all_sessions.assert_awaited_once_with()

    async def test_close_failure_logs_warning_and_still_reraises_original(self):
        client = MCPClient(user_id=USER_ID)
        err = RuntimeError("Schema error")
        close_err = RuntimeError("close boom")
        adapter = AsyncMock()
        adapter.create_tools = AsyncMock(side_effect=err)
        fake_client = AsyncMock()
        fake_client.close_all_sessions = AsyncMock(side_effect=close_err)
        with (
            patch("app.services.mcp.mcp_client.ResilientLangChainAdapter", return_value=adapter),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await client._convert_tools_safe(fake_client, INTEGRATION_ID)

        assert exc_info.value is err
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MCP} Failed to close leaked session",
            integration_id=INTEGRATION_ID,
            error="close boom",
            error_type="RuntimeError",
        )


class TestMakeCallbacksExact:
    async def test_evict_callback_pops_dicts_closes_stale_client_and_logs_iid(self):
        client = MCPClient(user_id=USER_ID)
        stale_client = AsyncMock()
        client._clients[INTEGRATION_ID] = stale_client
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        with (
            patch.object(client, "_safe_close_client", new_callable=AsyncMock) as mock_close,
            patch("app.services.mcp.mcp_client._spawn_background") as mock_spawn,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            callback = client._make_evict_callback(INTEGRATION_ID)
            callback()

        assert INTEGRATION_ID not in client._clients
        assert INTEGRATION_ID not in client._tools
        coro_arg, label = mock_spawn.call_args[0]
        assert label == f"evict_close_{INTEGRATION_ID}"
        await coro_arg  # drain the never-awaited close coroutine
        mock_close.assert_awaited_once_with(stale_client)
        mock_log.info.assert_called_once_with(
            f"{LogTag.MCP} Evicted stale session after connection error", iid=INTEGRATION_ID
        )

    async def test_evict_callback_without_stale_client_spawns_nothing(self):
        client = MCPClient(user_id=USER_ID)
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        with (
            patch("app.services.mcp.mcp_client._spawn_background") as mock_spawn,
            patch("app.services.mcp.mcp_client.log"),
        ):
            client._make_evict_callback(INTEGRATION_ID)()

        assert INTEGRATION_ID not in client._tools
        mock_spawn.assert_not_called()

    async def test_evicting_an_integration_that_was_never_cached_is_a_no_op(self) -> None:
        """The callback fires from a tool-call error, and a concurrent eviction
        may already have emptied both caches — popping without a default would
        turn the second one into a KeyError inside an error handler."""
        client = MCPClient(user_id=USER_ID)

        with (
            patch("app.services.mcp.mcp_client._spawn_background") as mock_spawn,
            patch("app.services.mcp.mcp_client.log"),
        ):
            client._make_evict_callback(INTEGRATION_ID)()

        mock_spawn.assert_not_called()

    async def test_reconnect_callback_delegates_with_exact_args_and_result(self):
        client = MCPClient(user_id=USER_ID)
        sentinel = object()
        with patch.object(
            client, "reconnect_and_call", new_callable=AsyncMock, return_value=sentinel
        ) as mock_rec:
            callback = client._make_reconnect_callback(INTEGRATION_ID)
            result = await callback("my_tool", {"k": "v"})

        mock_rec.assert_awaited_once_with(INTEGRATION_ID, "my_tool", {"k": "v"})
        assert result is sentinel


class TestRunPostConnectTasksExact:
    def _resolved(self) -> MagicMock:
        resolved = MagicMock()
        resolved.source = "platform"
        resolved.custom_doc = None
        return resolved

    async def test_unauthenticated_platform_runs_each_task_with_exact_args(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.store_unauthenticated = AsyncMock()
        client._index_platform_mcp_tools = AsyncMock()
        tools = [_mock_tool("t1", "desc1")]

        with (
            patch(
                "app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock
            ) as mock_store_tools,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            await client._run_post_connect_tasks(
                self._resolved(), _make_mcp_config(), False, INTEGRATION_ID, tools
            )

        client.token_store.store_unauthenticated.assert_awaited_once_with(INTEGRATION_ID)
        mock_store_tools.assert_awaited_once_with(
            INTEGRATION_ID, [{"name": "t1", "description": "desc1"}]
        )
        client._index_platform_mcp_tools.assert_awaited_once_with(INTEGRATION_ID, tools)
        mock_status.assert_awaited_once_with(USER_ID, INTEGRATION_ID, "connected")

        ok_labels = [
            call.kwargs["label"]
            for call in mock_log.info.call_args_list
            if "post-connect task ok" in call.args[0]
        ]
        assert ok_labels == [
            "store_unauthenticated",
            "store_tools_mongo",
            "index_platform_chroma",
            "update_status_connected",
        ]

    async def test_custom_integration_routes_to_custom_handler_with_doc_fields(self):
        resolved = MagicMock()
        resolved.custom_doc = {"name": "Custom Name", "description": "Custom Desc"}
        client = MCPClient(user_id=USER_ID)
        client.token_store.store_unauthenticated = AsyncMock()
        client._handle_custom_integration_connect = AsyncMock()
        tools = [_mock_tool()]

        with (
            patch("app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            await client._run_post_connect_tasks(
                resolved, _make_mcp_config(server_url=SERVER_URL), True, INTEGRATION_ID, tools
            )

        client._handle_custom_integration_connect.assert_awaited_once_with(
            INTEGRATION_ID, SERVER_URL, tools, name="Custom Name", description="Custom Desc"
        )
        # The labels are how a failed post-connect task is identified in the log;
        # the custom path swaps exactly one of them for its own name.
        ok_labels = [
            call.kwargs["label"]
            for call in mock_log.info.call_args_list
            if "post-connect task ok" in call.args[0]
        ]
        assert ok_labels == [
            "store_unauthenticated",
            "store_tools_mongo",
            "index_custom_chroma",
            "update_status_connected",
        ]

    async def test_failing_post_task_logs_warning_with_its_label_only(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.store_unauthenticated = AsyncMock()
        client._index_platform_mcp_tools = AsyncMock()
        tools = [_mock_tool()]

        with (
            patch("app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
                side_effect=Exception("status write failed"),
            ),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            await client._run_post_connect_tasks(
                self._resolved(), _make_mcp_config(), False, INTEGRATION_ID, tools
            )

        warnings = [c for c in mock_log.warning.call_args_list]
        assert len(warnings) == 1
        assert warnings[0].args[0] == f"{LogTag.MCP} post-connect task failed"
        assert warnings[0].kwargs == {
            "integration_id": INTEGRATION_ID,
            "label": "update_status_connected",
            "error": "status write failed",
            "error_type": "Exception",
        }


class TestHandleConnectFailureExact:
    async def test_step_up_raises_with_parsed_scopes_and_original_cause(self):
        client = MCPClient(user_id=USER_ID)
        err = ValueError('403 insufficient_scope scope="read write"')
        with patch("app.services.mcp.mcp_client.log"):
            with pytest.raises(StepUpAuthRequiredError) as exc_info:
                await client._handle_connect_failure(err, INTEGRATION_ID, _make_mcp_config())

        assert exc_info.value.integration_id == INTEGRATION_ID
        assert exc_info.value.required_scopes == ["read", "write"]
        assert exc_info.value.__cause__ is err

    async def test_transient_failure_keeps_connected_status_and_warns_exactly_once(self):
        client = MCPClient(user_id=USER_ID)
        client._reset_to_disconnected = AsyncMock()
        err = RuntimeError("connection reset by peer")
        with patch("app.services.mcp.mcp_client.log") as mock_log:
            result = await client._handle_connect_failure(err, INTEGRATION_ID, _make_mcp_config())

        assert result is None
        client._reset_to_disconnected.assert_not_awaited()
        mock_log.set_ns.assert_called_once_with(
            "mcp",
            operation="connect",
            server_id=INTEGRATION_ID,
            success=False,
            error_type="RuntimeError",
        )
        mock_log.error.assert_any_call(
            f"{LogTag.MCP} Failed to connect to MCP",
            integration_id=INTEGRATION_ID,
            error="connection reset by peer",
            error_type="RuntimeError",
        )
        mock_log.warning.assert_called_once_with(
            f"{LogTag.MCP} Transient connection failure — keeping "
            f"connected status so next attempt retries with current tokens",
            integration_id=INTEGRATION_ID,
            error="connection reset by peer",
            error_type="RuntimeError",
        )

    async def test_terminal_auth_failure_resets_to_disconnected(self):
        client = MCPClient(user_id=USER_ID)
        client._reset_to_disconnected = AsyncMock()
        err = RuntimeError("invalid_grant: token revoked")
        with patch("app.services.mcp.mcp_client.log") as mock_log:
            result = await client._handle_connect_failure(err, INTEGRATION_ID, _make_mcp_config())

        assert result is None
        client._reset_to_disconnected.assert_awaited_once_with(INTEGRATION_ID)
        mock_log.warning.assert_not_called()

    async def test_auth_error_refreshes_token_and_retries_connect_once(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(requires_auth=True)
        retried_tools = [_mock_tool("retry_tool")]
        client._try_refresh_token = AsyncMock(return_value=True)
        client._do_connect = AsyncMock(return_value=retried_tools)
        err = RuntimeError("401 Unauthorized from server")

        with patch("app.services.mcp.mcp_client.log"):
            result = await client._handle_connect_failure(err, INTEGRATION_ID, mcp_config)

        assert result is retried_tools
        client._try_refresh_token.assert_awaited_once_with(INTEGRATION_ID, mcp_config)
        client._do_connect.assert_awaited_once_with(INTEGRATION_ID)
        assert client._refresh_attempts == set()

    async def test_failed_refresh_warns_then_resets_on_terminal_error(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(requires_auth=True)
        client._try_refresh_token = AsyncMock(return_value=False)
        client._reset_to_disconnected = AsyncMock()
        err = RuntimeError("401 invalid_grant")

        with patch("app.services.mcp.mcp_client.log") as mock_log:
            result = await client._handle_connect_failure(err, INTEGRATION_ID, mcp_config)

        assert result is None
        mock_log.warning.assert_any_call(
            f"{LogTag.MCP} Token refresh failed, user may need to re-authorize",
            integration_id=INTEGRATION_ID,
            error="401 invalid_grant",
            error_type="RuntimeError",
        )
        client._reset_to_disconnected.assert_awaited_once_with(INTEGRATION_ID)


class TestSmallOauthHelpersExact:
    def test_the_metadata_document_candidate_is_computed_from_the_api_base(self) -> None:
        """All three values describe the SAME base URL; computing the localhost
        flag from anything else would publish a client_id the auth server cannot
        fetch — or refuse to publish one it could."""
        with (
            patch(
                "app.services.mcp.mcp_client.get_api_base_url", return_value="http://localhost:8000"
            ),
            patch("app.services.mcp.mcp_client.is_localhost_url", return_value=True) as is_local,
            patch(
                "app.services.mcp.mcp_client.get_client_metadata_document_url",
                return_value="http://localhost:8000/.well-known/mcp-client",
            ) as doc_url,
        ):
            result = MCPClient._metadata_document_candidate()

        assert result == (
            "http://localhost:8000",
            True,
            "http://localhost:8000/.well-known/mcp-client",
        )
        is_local.assert_called_once_with("http://localhost:8000")
        doc_url.assert_called_once_with("http://localhost:8000")

    def test_scopes_are_joined_by_a_single_space(self) -> None:
        """RFC 6749 scope is space-delimited; any other separator makes the whole
        string one unknown scope and the server rejects the authorization."""
        client = MCPClient(user_id=USER_ID)
        oauth_config = _make_oauth_discovery(
            metadata_overrides={"scopes_supported": ["read", "write", "offline_access"]}
        )

        with patch("app.services.mcp.mcp_client.log"):
            scope_str = client._build_oauth_scope_string(
                INTEGRATION_ID,
                _make_mcp_config(oauth_scopes=["read", "write"]),
                oauth_config,
                None,
            )

        assert scope_str == "read write offline_access"

    async def test_the_dcr_fallback_is_asked_for_this_integration_and_redirect(self) -> None:
        """The registration is bound to both — a dropped redirect_uri registers a
        client the auth server will then refuse to redirect back to."""
        client = MCPClient(user_id=USER_ID)
        oauth_config = _make_oauth_discovery()
        client.token_store.get_dcr_client = AsyncMock(return_value=None)

        with (
            patch.object(
                client,
                "_client_id_from_metadata_or_dcr",
                new_callable=AsyncMock,
                return_value="dcr_client",
            ) as fallback,
            patch("app.services.mcp.mcp_client.log"),
        ):
            client_id = await client._obtain_auth_client_id(
                INTEGRATION_ID,
                _make_mcp_config(requires_auth=True),
                oauth_config,
                "https://myapp.com/callback",
            )

        assert client_id == "dcr_client"
        fallback.assert_awaited_once_with(
            INTEGRATION_ID, oauth_config, "https://myapp.com/callback"
        )


class TestConnectFailureClassification:
    """What counts as an auth failure worth one refresh, and what counts as
    credentials being dead. Both decisions are string-matched against the
    provider's error text, so each marker needs its own case: a marker that
    stops matching silently turns a recoverable 401 into a dead integration,
    or a dead one into an infinite reconnect."""

    @staticmethod
    def _client() -> MCPClient:
        client = MCPClient(user_id=USER_ID)
        client._try_refresh_token = AsyncMock(return_value=False)
        client._reset_to_disconnected = AsyncMock()
        return client

    @pytest.mark.parametrize(
        "message",
        [
            # Status codes alone — no prose, so the code tuple is the only
            # clause that can match each of them.
            "server returned 401",
            "server returned 405",
            "server returned 403",
            # Prose alone — no status code in the string.
            "server said unauthorized",
            "server said method not allowed",
        ],
    )
    async def test_each_auth_marker_earns_one_refresh_attempt(self, message: str) -> None:
        client = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            await client._handle_connect_failure(
                RuntimeError(message), INTEGRATION_ID, _make_mcp_config(requires_auth=True)
            )

        client._try_refresh_token.assert_awaited_once()

    @pytest.mark.parametrize(
        "message",
        ["500 Internal Server Error", "connection reset by peer", "transport mismatch"],
    )
    async def test_a_non_auth_failure_never_refreshes(self, message: str) -> None:
        client = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            await client._handle_connect_failure(
                RuntimeError(message), INTEGRATION_ID, _make_mcp_config(requires_auth=True)
            )

        client._try_refresh_token.assert_not_awaited()

    async def test_an_auth_failure_on_a_server_without_auth_never_refreshes(self) -> None:
        client = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"),
                INTEGRATION_ID,
                _make_mcp_config(requires_auth=False),
            )

        client._try_refresh_token.assert_not_awaited()

    async def test_the_retry_marker_stops_a_second_refresh_on_re_entry(self) -> None:
        """The real loop: refresh succeeds, _do_connect retries, that connect
        fails the same way and lands back here. Without the marker the two
        refresh each other forever."""
        client = self._client()
        client._try_refresh_token = AsyncMock(return_value=True)
        mcp_config = _make_mcp_config(requires_auth=True)

        async def _reconnect_and_fail_again(iid: str) -> list[Any]:
            return await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"), iid, mcp_config
            )

        client._do_connect = AsyncMock(side_effect=_reconnect_and_fail_again)

        with patch("app.services.mcp.mcp_client.log"):
            await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"), INTEGRATION_ID, mcp_config
            )

        # The inner frame saw the marker and did not refresh a second time.
        client._try_refresh_token.assert_awaited_once()

    async def test_a_later_failure_gets_its_own_refresh(self) -> None:
        """The marker is scoped to one call stack, not to the client's lifetime —
        leaving it set would cost every later reconnect its retry."""
        client = self._client()
        mcp_config = _make_mcp_config(requires_auth=True)

        with patch("app.services.mcp.mcp_client.log"):
            for _ in range(2):
                await client._handle_connect_failure(
                    RuntimeError("401 Unauthorized"), INTEGRATION_ID, mcp_config
                )

        assert client._try_refresh_token.await_count == 2

    async def test_a_refresh_for_one_integration_does_not_block_another(self) -> None:
        client = self._client()
        client._try_refresh_token = AsyncMock(return_value=True)
        mcp_config = _make_mcp_config(requires_auth=True)

        async def _fail_a_different_integration(_iid: str) -> list[Any]:
            return await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"), "other_integration", mcp_config
            )

        client._do_connect = AsyncMock(side_effect=_fail_a_different_integration)

        with patch("app.services.mcp.mcp_client.log"):
            await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"), INTEGRATION_ID, mcp_config
            )

        assert client._try_refresh_token.await_count == 2

    async def test_a_401_is_terminal_only_after_a_refresh_was_attempted(self) -> None:
        """Before a refresh, a 401 may just be an expired access token — keep the
        tokens. After a failed refresh it is dead credentials."""
        err = _api_error(401)

        without_refresh = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            await without_refresh._handle_connect_failure(
                err, INTEGRATION_ID, _make_mcp_config(requires_auth=False)
            )
        without_refresh._reset_to_disconnected.assert_not_awaited()

        after_refresh = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            await after_refresh._handle_connect_failure(
                err, INTEGRATION_ID, _make_mcp_config(requires_auth=True)
            )
        after_refresh._try_refresh_token.assert_awaited_once()
        after_refresh._reset_to_disconnected.assert_awaited_once_with(INTEGRATION_ID)

    @pytest.mark.parametrize(
        "message",
        ["403 something else entirely", 'insufficient_scope scope="read"'],
    )
    async def test_step_up_needs_both_the_403_and_the_scope_marker(self, message: str) -> None:
        """Either half alone is an ordinary failure. Raising on one of them turns
        every 403 into a step-up prompt the server never asked for."""
        client = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            result = await client._handle_connect_failure(
                RuntimeError(message), INTEGRATION_ID, _make_mcp_config()
            )

        assert result is None

    async def test_step_up_without_a_scope_parameter_reports_no_scopes(self) -> None:
        """The challenge is allowed to omit scope=; the caller must get an empty
        list, not None, because it iterates it."""
        client = self._client()
        with patch("app.services.mcp.mcp_client.log"):
            with pytest.raises(StepUpAuthRequiredError) as exc_info:
                await client._handle_connect_failure(
                    RuntimeError("403 insufficient_scope"), INTEGRATION_ID, _make_mcp_config()
                )

        assert exc_info.value.required_scopes == []

    async def test_the_failure_is_logged_with_its_full_detail_and_traceback(self) -> None:
        client = self._client()
        err = RuntimeError("connection reset by peer")
        with patch("app.services.mcp.mcp_client.log") as mock_log:
            await client._handle_connect_failure(err, INTEGRATION_ID, _make_mcp_config())

        mock_log.error.assert_any_call(
            f"{LogTag.MCP} Connection failed with exception",
            integration_id=INTEGRATION_ID,
            error="connection reset by peer",
            error_type="RuntimeError",
            exc_info=True,
        )

    async def test_the_retry_flag_is_cleared_even_when_the_retry_deletes_it_first(self) -> None:
        """The recursive _do_connect runs the same finally block, so by the time
        this frame gets there the attribute can already be gone."""
        client = self._client()
        client._try_refresh_token = AsyncMock(return_value=True)

        async def _reconnect(_iid: str) -> list[Any]:
            client._refresh_attempts.discard(INTEGRATION_ID)
            return []

        client._do_connect = AsyncMock(side_effect=_reconnect)

        with patch("app.services.mcp.mcp_client.log"):
            result = await client._handle_connect_failure(
                RuntimeError("401 Unauthorized"),
                INTEGRATION_ID,
                _make_mcp_config(requires_auth=True),
            )

        assert result == []
        assert client._refresh_attempts == set()


class TestDoConnectWiringExact:
    @pytest.fixture(autouse=True)
    def _mock_ssrf_guard(self) -> Iterator[None]:
        with patch("app.services.mcp.mcp_client.assert_public_http_url", new_callable=AsyncMock):
            yield

    @staticmethod
    def _resolved_for(source: str = "platform"):
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        resolved.source = source
        resolved.custom_doc = None
        return resolved

    async def test_every_stage_is_handed_this_integration_and_its_config(self) -> None:
        """_do_connect resolves once and threads the id, the config and the
        resolution through five stages. Any one of them losing it connects the
        right server but stamps, indexes or persists against the wrong record —
        and the connect still reports success."""
        resolved = self._resolved_for()
        client = MCPClient(user_id=USER_ID)
        session = AsyncMock()
        tools = [_mock_tool("t1")]
        client._open_session = AsyncMock(return_value=session)
        client._convert_tools_safe = AsyncMock(return_value=tools)
        client._stamp_tool_metadata = MagicMock()
        client._run_post_connect_tasks = AsyncMock()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch("app.services.mcp.mcp_client.wrap_tools_with_null_filter", return_value=tools),
            patch(
                "app.services.mcp.mcp_client.invalidate_user_integration_caches",
                new_callable=AsyncMock,
            ),
            patch("app.services.mcp.mcp_client.log"),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            await client._do_connect(INTEGRATION_ID)

        mock_resolver.resolve.assert_awaited_once_with(INTEGRATION_ID)
        client._open_session.assert_awaited_once_with(INTEGRATION_ID, resolved.mcp_config)
        client._convert_tools_safe.assert_awaited_once_with(session, INTEGRATION_ID)
        client._stamp_tool_metadata.assert_called_once_with(tools, INTEGRATION_ID, SERVER_URL)
        client._run_post_connect_tasks.assert_awaited_once_with(
            resolved, resolved.mcp_config, False, INTEGRATION_ID, tools
        )

    @pytest.mark.parametrize(
        ("source", "is_custom"), [("custom", True), ("platform", False), ("Custom", False)]
    )
    async def test_only_the_exact_custom_source_takes_the_custom_post_connect_path(
        self, source: str, is_custom: bool
    ) -> None:
        """is_custom picks which Chroma collection the tools are indexed into —
        getting it wrong hides a user's own server from retrieval entirely."""
        resolved = self._resolved_for(source)
        client = MCPClient(user_id=USER_ID)
        client._open_session = AsyncMock(return_value=AsyncMock())
        client._convert_tools_safe = AsyncMock(return_value=[])
        client._stamp_tool_metadata = MagicMock()
        client._run_post_connect_tasks = AsyncMock()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch("app.services.mcp.mcp_client.wrap_tools_with_null_filter", return_value=[]),
            patch(
                "app.services.mcp.mcp_client.invalidate_user_integration_caches",
                new_callable=AsyncMock,
            ),
            patch("app.services.mcp.mcp_client.log"),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            await client._do_connect(INTEGRATION_ID)

        assert client._run_post_connect_tasks.await_args.args[2] is is_custom

    async def test_the_outbound_config_is_built_for_this_integration(self) -> None:
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        client._build_config = AsyncMock(return_value={"mcpServers": {}})

        with (
            patch("app.services.mcp.mcp_client.BaseMCPClient", return_value=AsyncMock()),
            patch("app.services.mcp.mcp_client.log"),
        ):
            await client._open_session(INTEGRATION_ID, mcp_config)

        client._build_config.assert_awaited_once_with(INTEGRATION_ID, mcp_config)

    async def test_wraps_stamped_tools_with_live_callbacks_and_persists(self):
        raw = [_mock_tool("raw1"), _mock_tool("raw2")]
        wrapped = [MagicMock(name="w1"), MagicMock(name="w2")]
        wrapped[0].name = "w1"
        wrapped[1].name = "w2"
        mock_base = AsyncMock()
        adapter = AsyncMock()
        adapter.create_tools = AsyncMock(return_value=raw)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        resolved.source = "platform"
        resolved.custom_doc = None

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch("app.services.mcp.mcp_client.BaseMCPClient", return_value=mock_base),
            patch("app.services.mcp.mcp_client.ResilientLangChainAdapter", return_value=adapter),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter", return_value=wrapped
            ) as mock_wrap,
            patch(
                "app.services.mcp.mcp_client.store_mcp_tools", new_callable=AsyncMock
            ) as mock_store_tools,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.mcp.mcp_client.invalidate_user_integration_caches",
                new_callable=AsyncMock,
            ) as mock_inval,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client = MCPClient(user_id=USER_ID)
            client.token_store.get_bearer_token = AsyncMock(return_value=None)
            client._index_platform_mcp_tools = AsyncMock()

            result = await client._do_connect(INTEGRATION_ID)

        assert result is wrapped
        assert client._tools[INTEGRATION_ID] is wrapped
        assert client._clients[INTEGRATION_ID] is mock_base

        mock_wrap.assert_called_once()
        assert mock_wrap.call_args.args[0] is raw
        wrap_kwargs = mock_wrap.call_args.kwargs

        # Provenance was stamped before wrapping.
        assert [t.metadata["integration_id"] for t in raw] == [INTEGRATION_ID, INTEGRATION_ID]

        # The evict callback handed to the wrapper really evicts this client's caches.
        client._tools[INTEGRATION_ID] = wrapped
        client._clients[INTEGRATION_ID] = mock_base
        with (
            patch.object(client, "_safe_close_client", new_callable=AsyncMock) as mock_close,
            patch("app.services.mcp.mcp_client._spawn_background") as mock_evict_spawn,
        ):
            wrap_kwargs["on_connection_error"]()
            assert INTEGRATION_ID not in client._clients
            assert INTEGRATION_ID not in client._tools
            coro_arg, label = mock_evict_spawn.call_args[0]
            assert label == f"evict_close_{INTEGRATION_ID}"
            await coro_arg
            mock_close.assert_awaited_once_with(mock_base)

        # The reconnect callback delegates to reconnect_and_call for this integration.
        sentinel = object()
        with patch.object(
            client, "reconnect_and_call", new_callable=AsyncMock, return_value=sentinel
        ) as mock_rec:
            assert await wrap_kwargs["reconnect_and_retry"]("tool_x", {"a": 1}) is sentinel
        mock_rec.assert_awaited_once_with(INTEGRATION_ID, "tool_x", {"a": 1})

        # Post-connect persistence runs on the wrapped tool list.
        mock_store_tools.assert_awaited_once()
        stored_metadata = mock_store_tools.await_args.args[1]
        assert [entry["name"] for entry in stored_metadata] == ["w1", "w2"]
        mock_inval.assert_awaited_once_with(USER_ID)
        mock_log.set_ns.assert_called_once_with(
            "mcp",
            operation="connect",
            server_id=INTEGRATION_ID,
            tool_count=2,
            success=True,
        )


class TestBuildOauthAuthUrlExactParams:
    async def _build(self, redirect_path: str | None = None):
        client = MCPClient(user_id=USER_ID)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True, client_id="my_client", oauth_scopes=["read"]
        )
        oauth_config = _make_oauth_discovery(metadata_overrides={"scopes_supported": ["read"]})

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(
                    code_verifier="verifier_123", code_challenge="challenge_456"
                ),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state_abc")

            # Omitted entirely when the test does not care: that is the only way
            # the signature's own default is ever exercised.
            kwargs = {} if redirect_path is None else {"redirect_path": redirect_path}
            url = await client.build_oauth_auth_url(
                INTEGRATION_ID, "https://myapp.com/callback", **kwargs
            )

        return url

    async def test_query_params_are_exact(self):
        url = await self._build()
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
            "https://auth.example.com/authorize"
        )
        assert query == {
            "client_id": ["my_client"],
            "redirect_uri": ["https://myapp.com/callback"],
            "response_type": ["code"],
            "state": [f"state_abc:{INTEGRATION_ID}:/integrations"],
            "code_challenge": ["challenge_456"],
            "code_challenge_method": ["S256"],
            "resource": [SERVER_URL],
            "scope": ["read"],
        }

    async def test_the_default_redirect_path_is_the_integrations_page(self) -> None:
        """The state string is what the callback parses to decide where to send
        the browser back to; a mangled default drops the user somewhere else."""
        query = parse_qs(urlparse(await self._build()).query)
        assert query["state"] == [f"state_abc:{INTEGRATION_ID}:/integrations"]

    async def test_every_stage_is_handed_this_integration_and_its_discovery(self) -> None:
        """Discovery, client-id resolution, PKCE validation, state creation and
        scope selection each take the integration separately. Losing it on any
        one of them builds an authorize URL for the wrong server or the wrong
        client — and the URL still looks well-formed."""
        client = MCPClient(user_id=USER_ID)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True, client_id="my_client")
        oauth_config = _make_oauth_discovery()
        excluded = {"drop_me"}
        challenge = MagicMock()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client, "_discover_oauth_config", new_callable=AsyncMock, return_value=oauth_config
            ) as discover,
            patch.object(
                client, "_obtain_auth_client_id", new_callable=AsyncMock, return_value="cid"
            ) as obtain,
            patch.object(client, "_build_oauth_scope_string", return_value="read") as scopes,
            patch("app.services.mcp.mcp_client.validate_pkce_support") as pkce_check,
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(code_verifier="verifier_123", code_challenge="c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state_abc")

            await client.build_oauth_auth_url(
                INTEGRATION_ID,
                "https://myapp.com/callback",
                challenge_data=challenge,
                excluded_scopes=excluded,
            )

        mock_resolver.resolve.assert_awaited_once_with(INTEGRATION_ID)
        discover.assert_awaited_once_with(
            INTEGRATION_ID, resolved.mcp_config, challenge_data=challenge
        )
        obtain.assert_awaited_once_with(
            INTEGRATION_ID, resolved.mcp_config, oauth_config, "https://myapp.com/callback"
        )
        pkce_check.assert_called_once_with(oauth_config.as_metadata, INTEGRATION_ID)
        client.token_store.create_oauth_state.assert_awaited_once_with(
            INTEGRATION_ID, "verifier_123"
        )
        scopes.assert_called_once_with(INTEGRATION_ID, resolved.mcp_config, oauth_config, excluded)

    async def test_state_carries_custom_redirect_path(self):
        url = await self._build(redirect_path="/onboarding")
        query = parse_qs(urlparse(url).query)
        assert query["state"] == [f"state_abc:{INTEGRATION_ID}:/onboarding"]

    async def test_nonce_param_matches_nonce_passed_to_store(self):
        client = MCPClient(user_id=USER_ID)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True, client_id="cid", oauth_scopes=["openid", "profile"]
        )
        oauth_config = _make_oauth_discovery()

        stored_nonce: list[str] = []

        async def _capture_store(iid: str, nonce: str) -> None:
            stored_nonce.append(nonce)

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=oauth_config,
            ),
            patch("app.services.mcp.mcp_client.validate_pkce_support"),
            patch(
                "app.services.mcp.mcp_client.PKCEParameters.generate",
                return_value=MagicMock(code_verifier="v", code_challenge="c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")
            client.token_store.store_oauth_nonce = AsyncMock(side_effect=_capture_store)

            url = await client.build_oauth_auth_url(INTEGRATION_ID, "https://callback.com")

        query = parse_qs(urlparse(url).query)
        assert len(stored_nonce) == 1
        assert query["nonce"] == [stored_nonce[0]]
        client.token_store.store_oauth_nonce.assert_awaited_once_with(
            INTEGRATION_ID, stored_nonce[0]
        )


class TestClientIdFromMetadataOrDcrExact:
    async def test_metadata_doc_returned_when_supported_and_api_is_public(self):
        client = MCPClient(user_id=USER_ID)
        discovery = _make_oauth_discovery(
            metadata_overrides={"client_id_metadata_document_supported": True}
        )
        with (
            patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="https://api.gaia.dev",
            ),
            patch("app.services.mcp.mcp_client.is_localhost_url", return_value=False),
            patch(
                "app.services.mcp.mcp_client.get_client_metadata_document_url",
                return_value="https://api.gaia.dev/.well-known/oauth-client",
            ) as mock_doc_url,
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            result = await client._client_id_from_metadata_or_dcr(
                INTEGRATION_ID, discovery, "https://cb"
            )

        assert result == "https://api.gaia.dev/.well-known/oauth-client"
        mock_doc_url.assert_called_once_with("https://api.gaia.dev")
        mock_log.info.assert_called_once_with(
            f"{LogTag.MCP} Using client metadata document URL as client_id for",
            integration_id=INTEGRATION_ID,
            client_id="https://api.gaia.dev/.well-known/oauth-client",
        )

    async def test_falls_back_to_dcr_on_localhost_even_when_supported(self):
        client = MCPClient(user_id=USER_ID)
        discovery = _make_oauth_discovery(
            metadata_overrides={
                "client_id_metadata_document_supported": True,
                "registration_endpoint": "https://auth.example.com/register",
            }
        )
        as_metadata = discovery.as_metadata
        with (
            patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="http://localhost:8000",
            ),
            patch("app.services.mcp.mcp_client.is_localhost_url", return_value=True),
            patch.object(
                client, "_register_client", new_callable=AsyncMock, return_value="dcr_cid"
            ) as mock_register,
            patch("app.services.mcp.mcp_client.log"),
        ):
            result = await client._client_id_from_metadata_or_dcr(
                INTEGRATION_ID, discovery, "https://cb"
            )

        assert result == "dcr_cid"
        mock_register.assert_awaited_once_with(INTEGRATION_ID, as_metadata, "https://cb")


class TestResolveTokenExchangeCredentialsExact:
    async def test_preconfigured_credentials_win_before_dcr_lookup(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config(client_id="cfg_client", client_secret="cfg_secret")
        client.token_store.get_dcr_client = AsyncMock()

        result = await client._resolve_token_exchange_credentials(
            INTEGRATION_ID, mcp_config, _make_oauth_discovery()
        )

        assert result == ("cfg_client", "cfg_secret")
        client.token_store.get_dcr_client.assert_not_awaited()

    async def test_stored_dcr_client_used_when_no_preconfigured_credentials(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        client.token_store.get_dcr_client = AsyncMock(
            return_value={"client_id": "dcr_cid", "client_secret": "dcr_sec"}
        )

        result = await client._resolve_token_exchange_credentials(
            INTEGRATION_ID, mcp_config, _make_oauth_discovery()
        )

        assert result == ("dcr_cid", "dcr_sec")
        client.token_store.get_dcr_client.assert_awaited_once_with(INTEGRATION_ID)

    async def test_metadata_document_returns_url_without_secret(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        discovery = _make_oauth_discovery(
            metadata_overrides={"client_id_metadata_document_supported": True}
        )
        client.token_store.get_dcr_client = AsyncMock(return_value=None)
        with (
            patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="https://api.gaia.dev",
            ),
            patch("app.services.mcp.mcp_client.is_localhost_url", return_value=False),
            patch(
                "app.services.mcp.mcp_client.get_client_metadata_document_url",
                return_value="https://api.gaia.dev/.well-known/oauth-client",
            ),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            result = await client._resolve_token_exchange_credentials(
                INTEGRATION_ID, mcp_config, discovery
            )

        assert result == ("https://api.gaia.dev/.well-known/oauth-client", None)
        mock_log.info.assert_called_once_with(
            f"{LogTag.MCP} Using client metadata document URL as client_id for token exchange",
            client_id="https://api.gaia.dev/.well-known/oauth-client",
        )

    async def test_localhost_never_uses_metadata_document(self):
        client = MCPClient(user_id=USER_ID)
        mcp_config = _make_mcp_config()
        discovery = _make_oauth_discovery(
            metadata_overrides={"client_id_metadata_document_supported": True}
        )
        client.token_store.get_dcr_client = AsyncMock(return_value=None)
        with (
            patch(
                "app.services.mcp.mcp_client.get_api_base_url",
                return_value="http://localhost:8000",
            ),
            patch("app.services.mcp.mcp_client.is_localhost_url", return_value=True),
            patch(
                "app.services.mcp.mcp_client.get_client_metadata_document_url",
                return_value="http://localhost:8000/.well-known/oauth-client",
            ) as mock_doc_url,
            patch("app.services.mcp.mcp_client.log"),
        ):
            result = await client._resolve_token_exchange_credentials(
                INTEGRATION_ID, mcp_config, discovery
            )

        # Supported or not, a localhost API base can never serve the metadata
        # document — no client_id may come out of this branch.
        assert result == (None, None)
        mock_doc_url.assert_called_once_with("http://localhost:8000")


class TestExchangeCodeForTokensExact:
    def _exchange(self, **overrides: Any) -> dict[str, Any]:
        exchange: dict[str, Any] = {
            "code": "authcode",
            "redirect_uri": "https://myapp.com/callback",
            "resource": SERVER_URL,
            "client_id": "cid",
            "client_secret": None,
            "code_verifier": "verifier123",
        }
        exchange.update(overrides)
        return exchange

    async def test_posts_exact_form_data_headers_and_timeout(self):
        client = MCPClient(user_id=USER_ID)
        post = AsyncMock(return_value=_ok_response({"access_token": "at"}))
        with (
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=_fake_http_client(post)(),
            ),
        ):
            result = await client._exchange_code_for_tokens(
                INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
            )

        post.assert_awaited_once_with(
            "https://auth.example.com/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "cid",
                "code": "authcode",
                "redirect_uri": "https://myapp.com/callback",
                "resource": SERVER_URL,
                "code_verifier": "verifier123",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            },
            timeout=30,
        )
        assert result == {"access_token": "at"}

    async def test_missing_verifier_omits_the_key_entirely(self):
        client = MCPClient(user_id=USER_ID)
        post = AsyncMock(return_value=_ok_response({}))
        with patch(
            "app.services.mcp.mcp_client.httpx.AsyncClient",
            return_value=_fake_http_client(post)(),
        ):
            await client._exchange_code_for_tokens(
                INTEGRATION_ID, "https://auth.example.com/token", self._exchange(code_verifier=None)
            )

        sent_data = post.call_args.kwargs["data"]
        assert sent_data == {
            "grant_type": "authorization_code",
            "client_id": "cid",
            "code": "authcode",
            "redirect_uri": "https://myapp.com/callback",
            "resource": SERVER_URL,
        }

    async def test_secret_adds_basic_auth_header_with_exact_encoding(self):
        client = MCPClient(user_id=USER_ID)
        post = AsyncMock(return_value=_ok_response({}))
        expected_basic = "Basic " + base64.b64encode(b"cid:sec").decode()
        with patch(
            "app.services.mcp.mcp_client.httpx.AsyncClient",
            return_value=_fake_http_client(post)(),
        ):
            await client._exchange_code_for_tokens(
                INTEGRATION_ID,
                "https://auth.example.com/token",
                self._exchange(client_secret="sec"),
            )

        headers = post.call_args.kwargs["headers"]
        assert headers["Authorization"] == expected_basic

    async def test_no_secret_means_no_authorization_header(self):
        client = MCPClient(user_id=USER_ID)
        post = AsyncMock(return_value=_ok_response({}))
        with patch(
            "app.services.mcp.mcp_client.httpx.AsyncClient",
            return_value=_fake_http_client(post)(),
        ):
            await client._exchange_code_for_tokens(
                INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
            )

        assert "Authorization" not in post.call_args.kwargs["headers"]

    @pytest.mark.parametrize("status", [200, 201, 299])
    async def test_every_2xx_is_a_successful_exchange(self, status: int) -> None:
        """OAuth servers differ on which 2xx they return; only 3xx and up is an
        error. A boundary off by one rejects a token that was actually issued."""
        client = MCPClient(user_id=USER_ID)
        response = _ok_response({"access_token": "at"})
        response.status_code = status
        with patch(
            "app.services.mcp.mcp_client.httpx.AsyncClient",
            return_value=_fake_http_client(AsyncMock(return_value=response))(),
        ):
            result = await client._exchange_code_for_tokens(
                INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
            )

        assert result == {"access_token": "at"}

    @pytest.mark.parametrize("status", [300, 301, 400])
    async def test_the_first_non_2xx_status_is_an_error(self, status: int) -> None:
        client = MCPClient(user_id=USER_ID)
        response = MagicMock()
        response.status_code = status
        with (
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=_fake_http_client(AsyncMock(return_value=response))(),
            ),
            patch(
                "app.services.mcp.mcp_client.parse_oauth_error_response",
                return_value={"error": "invalid_grant", "error_description": "Code expired"},
            ) as parse,
            patch("app.services.mcp.mcp_client.log"),
        ):
            with pytest.raises(ValueError):
                await client._exchange_code_for_tokens(
                    INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
                )

        # Parsed from the response itself — the body is where the OAuth error lives.
        parse.assert_called_once_with(response)

    async def test_an_error_without_a_description_says_unknown_error(self) -> None:
        """The raised message is what reaches the user's reconnect screen, so the
        placeholder has to read as English, not as an empty tail."""
        client = MCPClient(user_id=USER_ID)
        response = MagicMock()
        response.status_code = 400
        with (
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=_fake_http_client(AsyncMock(return_value=response))(),
            ),
            patch(
                "app.services.mcp.mcp_client.parse_oauth_error_response",
                return_value={"error": "invalid_grant"},
            ),
            patch("app.services.mcp.mcp_client.log"),
        ):
            with pytest.raises(ValueError) as exc_info:
                await client._exchange_code_for_tokens(
                    INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
                )

        assert str(exc_info.value) == "Token exchange failed: invalid_grant - Unknown error"

    async def test_error_response_logs_exact_kwargs_and_raises_exact_message(self):
        client = MCPClient(user_id=USER_ID)
        bad_response = MagicMock()
        bad_response.status_code = 400
        with (
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=_fake_http_client(AsyncMock(return_value=bad_response))(),
            ),
            patch(
                "app.services.mcp.mcp_client.parse_oauth_error_response",
                return_value={"error": "invalid_grant", "error_description": "Code expired"},
            ),
            patch("app.services.mcp.mcp_client.log") as mock_log,
        ):
            with pytest.raises(
                ValueError, match=r"^Token exchange failed: invalid_grant - Code expired$"
            ):
                await client._exchange_code_for_tokens(
                    INTEGRATION_ID, "https://auth.example.com/token", self._exchange()
                )

        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} Token exchange failed",
            integration_id=INTEGRATION_ID,
            oauth_error="invalid_grant",
            oauth_error_description="Code expired",
        )


class TestHandleOauthCallbackNonceEnforcement:
    """A stored nonce must gate the whole exchange — every mismatch path fails loud."""

    def _make_client(self) -> MCPClient:
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(return_value=(True, "verifier"))
        client.token_store.get_and_delete_oauth_nonce = AsyncMock()
        client.token_store.store_oauth_tokens = AsyncMock()
        return client

    async def _run_callback(
        self, client: MCPClient, tokens: dict[str, Any], stored_nonce: str | None
    ) -> list[BaseTool]:
        client.token_store.get_and_delete_oauth_nonce = AsyncMock(return_value=stored_nonce)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True, client_id="cid")

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value=_make_oauth_discovery(),
            ),
            patch("app.services.mcp.mcp_client.validate_https_url"),
            patch("app.services.mcp.mcp_client.validate_jwt_issuer", return_value=True),
            patch(
                "app.services.mcp.mcp_client.httpx.AsyncClient",
                return_value=_fake_http_client(AsyncMock(return_value=_ok_response(tokens)))(),
            ),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            return await client.handle_oauth_callback(
                INTEGRATION_ID, "code", "state", "https://callback.com"
            )

    async def test_the_exchange_and_the_nonce_check_are_scoped_to_this_integration(
        self,
    ) -> None:
        """The callback resolves, discovers, exchanges and nonce-checks under one
        integration id. Losing it on any hop exchanges the code against the wrong
        server's token endpoint or validates the wrong stored nonce."""
        client = self._make_client()
        tokens = {
            "access_token": "at",
            "token_type": "Bearer",
            "id_token": _make_id_token({"nonce": "stored_nonce"}),
        }
        client._validate_oidc_nonce = MagicMock()
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True, client_id="cid")
        oauth_config = _make_oauth_discovery()

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client, "_discover_oauth_config", new_callable=AsyncMock, return_value=oauth_config
            ) as discover,
            patch.object(
                client, "_exchange_code_for_tokens", new_callable=AsyncMock, return_value=tokens
            ) as exchange,
            patch.object(
                client,
                "_resolve_token_exchange_credentials",
                new_callable=AsyncMock,
                return_value=("cid", None),
            ) as credentials,
            patch("app.services.mcp.mcp_client._spawn_background", return_value=MagicMock()),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.get_and_delete_oauth_nonce = AsyncMock(return_value="stored_nonce")
            await client.handle_oauth_callback(
                INTEGRATION_ID, "the-code", "state", "https://callback.com"
            )

        discover.assert_awaited_once_with(INTEGRATION_ID, resolved.mcp_config)
        credentials.assert_awaited_once_with(INTEGRATION_ID, resolved.mcp_config, oauth_config)
        assert exchange.await_args.kwargs["integration_id"] == INTEGRATION_ID
        assert exchange.await_args.kwargs["token_endpoint"] == "https://auth.example.com/token"
        client._validate_oidc_nonce.assert_called_once_with(INTEGRATION_ID, "stored_nonce", tokens)

    async def test_nonce_mismatch_aborts_before_tokens_are_stored(self):
        client = self._make_client()
        tokens = {
            "access_token": "at",
            "token_type": "Bearer",
            "id_token": _make_id_token({"nonce": "attacker_nonce"}),
        }
        with pytest.raises(ValueError, match=r"^OIDC nonce mismatch .* possible replay attack$"):
            await self._run_callback(client, tokens, stored_nonce="stored_nonce")
        client.token_store.store_oauth_tokens.assert_not_awaited()

    async def test_missing_id_token_with_stored_nonce_raises(self):
        client = self._make_client()
        tokens = {"access_token": "at", "token_type": "Bearer"}
        with pytest.raises(ValueError) as exc_info:
            await self._run_callback(client, tokens, stored_nonce="stored_nonce")
        assert str(exc_info.value) == (
            f"OIDC nonce validation failed for {INTEGRATION_ID}: "
            "token response contained no id_token"
        )
        client.token_store.store_oauth_tokens.assert_not_awaited()

    async def test_undecodable_id_token_raises(self):
        client = self._make_client()
        tokens = {
            "access_token": "at",
            "token_type": "Bearer",
            "id_token": "not-a-jwt",
        }
        with pytest.raises(ValueError, match="could not decode id_token"):
            await self._run_callback(client, tokens, stored_nonce="stored_nonce")
        client.token_store.store_oauth_tokens.assert_not_awaited()

    async def test_id_token_without_nonce_claim_raises(self):
        client = self._make_client()
        tokens = {
            "access_token": "at",
            "token_type": "Bearer",
            "id_token": _make_id_token({"sub": "user-1"}),
        }
        with pytest.raises(ValueError) as exc_info:
            await self._run_callback(client, tokens, stored_nonce="stored_nonce")
        assert str(exc_info.value) == (
            f"OIDC nonce validation failed for {INTEGRATION_ID}: id_token carries no nonce claim"
        )
        client.token_store.store_oauth_tokens.assert_not_awaited()

    async def test_matching_nonce_proceeds_to_storage_and_returns_empty_list(self):
        client = self._make_client()
        tokens = {
            "access_token": "at",
            "token_type": "Bearer",
            "expires_in": 3600,
            "id_token": _make_id_token({"nonce": "stored_nonce"}),
        }
        with patch("app.services.mcp.mcp_client._spawn_background", return_value=MagicMock()):
            result = await self._run_callback(client, tokens, stored_nonce="stored_nonce")

        assert result == []
        client.token_store.store_oauth_tokens.assert_awaited_once()
        call_kwargs = client.token_store.store_oauth_tokens.await_args.kwargs
        assert call_kwargs["integration_id"] == INTEGRATION_ID
        assert call_kwargs["access_token"] == "at"
        assert call_kwargs["refresh_token"] is None


class TestServerUrlMatchingHelpersExact:
    def _resolved_with(self, server_url: str | None) -> MagicMock:
        resolved = MagicMock()
        resolved.mcp_config = (
            None if server_url is None else _make_mcp_config(server_url=server_url)
        )
        return resolved

    def test_matches_normalized_urls(self):
        client = MCPClient(user_id=USER_ID)
        target = client._normalize_server_url(SERVER_URL)
        assert (
            client._resolved_matches_server_url(self._resolved_with(SERVER_URL + "/"), target)
            is True
        )
        assert (
            client._resolved_matches_server_url(
                self._resolved_with("HTTPS://MCP.EXAMPLE.COM/v1"), target
            )
            is True
        )
        assert (
            client._resolved_matches_server_url(self._resolved_with("https://other.com"), target)
            is False
        )

    def test_rejects_none_resolution_and_missing_config(self):
        client = MCPClient(user_id=USER_ID)
        assert client._resolved_matches_server_url(None, "anything") is False
        assert client._resolved_matches_server_url(self._resolved_with(None), "anything") is False

    async def test_match_active_client_returns_first_matching_integration_id(self):
        client = MCPClient(user_id=USER_ID)
        client._clients["aaa"] = MagicMock()
        client._clients["bbb"] = MagicMock()
        target = client._normalize_server_url(SERVER_URL)
        resolutions = {
            "aaa": self._resolved_with("https://elsewhere.io"),
            "bbb": self._resolved_with(SERVER_URL),
        }

        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(side_effect=lambda iid: resolutions[iid])
            match = await client._match_active_client_by_server_url(target)

        assert match == "bbb"

    async def test_match_active_client_returns_none_when_nothing_matches(self):
        client = MCPClient(user_id=USER_ID)
        client._clients["aaa"] = MagicMock()
        target = client._normalize_server_url(SERVER_URL)
        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(
                return_value=self._resolved_with("https://elsewhere.io")
            )
            match = await client._match_active_client_by_server_url(target)

        assert match is None

    def test_connectable_candidate_ids_filters_exactly(self):
        docs = [
            {"integration_id": "a", "status": "connected"},
            {"integration_id": "b", "status": "created"},
            {"integration_id": None, "status": "connected"},
            {"integration_id": "c"},
            {"integration_id": 123, "status": "connected"},
        ]
        assert MCPClient._connectable_candidate_ids(docs) == ["a", "c", "123"]

    def test_connectable_candidate_ids_empty_for_no_docs(self):
        assert MCPClient._connectable_candidate_ids([]) == []
