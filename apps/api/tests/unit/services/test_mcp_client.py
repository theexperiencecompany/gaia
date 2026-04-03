"""Comprehensive unit tests for MCP client, client pool, token store, token management,
OAuth discovery, LangChain adapter, and resilient adapter.

Covers: connect, disconnect, execute tool, list tools, client pool get/evict/cleanup/shutdown,
token store CRUD/encrypt/decrypt, token refresh/expiry, OAuth discovery, probe,
LangChain adapter schema sanitization, and resilient adapter retry/skip logic.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from app.models.db_oauth import MCPAuthType, MCPCredential, MCPCredentialStatus
from app.models.mcp_config import MCPConfig
from app.services.mcp.langchain_adapter import SanitizingLangChainAdapter
from app.services.mcp.mcp_client import (
    DCRNotSupportedException,
    MCPClient,
    StepUpAuthRequired,
    get_mcp_client,
)
from app.services.mcp.mcp_client_pool import MCPClientPool, PooledClient
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.mcp.mcp_tools_store import MCPToolsStore, _format_tools
from app.services.mcp.oauth_discovery import discover_oauth_config, probe_mcp_connection
from app.services.mcp.resilient_adapter import ResilientLangChainAdapter
from app.services.mcp.token_management import (
    resolve_client_credentials,
    revoke_tokens,
    try_refresh_token,
)

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


def _make_credential(**overrides: Any) -> MCPCredential:
    """Build a lightweight MCPCredential mock with sensible defaults."""
    cred = MagicMock(spec=MCPCredential)
    cred.user_id = overrides.get("user_id", USER_ID)
    cred.integration_id = overrides.get("integration_id", INTEGRATION_ID)
    cred.auth_type = overrides.get("auth_type", MCPAuthType.OAUTH)
    cred.status = overrides.get("status", MCPCredentialStatus.CONNECTED)
    cred.access_token = overrides.get("access_token", "encrypted_token")
    cred.refresh_token = overrides.get("refresh_token", None)
    cred.token_expires_at = overrides.get("token_expires_at", None)
    cred.client_registration = overrides.get("client_registration", None)
    cred.connected_at = overrides.get("connected_at", None)
    cred.error_message = overrides.get("error_message", None)
    return cred


def _mock_tool(name: str = "test_tool", description: str = "A test tool") -> MagicMock:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.description = description
    tool.metadata = {}
    return tool


# ---------------------------------------------------------------------------
# Fake DB session context manager
# ---------------------------------------------------------------------------


def _fake_db_session(cred: Optional[MCPCredential] = None):
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientUpdateIntegrationAuthStatus:
    async def test_updates_mongodb(self):
        client = MCPClient(user_id=USER_ID)
        mock_result = MagicMock()
        mock_result.modified_count = 1
        with patch("app.services.mcp.mcp_client.integrations_collection") as mock_col:
            mock_col.update_one = AsyncMock(return_value=mock_result)
            await client.update_integration_auth_status(INTEGRATION_ID, True, "oauth")
            mock_col.update_one.assert_awaited_once()
            call_args = mock_col.update_one.call_args
            assert call_args[0][0] == {"integration_id": INTEGRATION_ID}
            assert call_args[0][1]["$set"]["mcp_config.requires_auth"] is True

    async def test_handles_exception_gracefully(self):
        client = MCPClient(user_id=USER_ID)
        with patch("app.services.mcp.mcp_client.integrations_collection") as mock_col:
            mock_col.update_one = AsyncMock(side_effect=Exception("DB failure"))
            # Should not raise
            await client.update_integration_auth_status(INTEGRATION_ID, False, "none")


@pytest.mark.unit
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
        client.token_store.get_bearer_token = AsyncMock(
            return_value="Bearer actual_token"
        )
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientDoConnect:
    @patch("app.services.mcp.mcp_client.IntegrationResolver")
    @patch("app.services.mcp.mcp_client.BaseMCPClient")
    @patch("app.services.mcp.mcp_client.ResilientLangChainAdapter")
    @patch("app.services.mcp.mcp_client.wrap_tools_with_null_filter")
    @patch("app.services.mcp.mcp_client.get_mcp_tools_store")
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new_callable=AsyncMock,
    )
    async def test_successful_connect(
        self,
        mock_update_status,
        mock_get_store,
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

        # Tools store
        mock_store = AsyncMock()
        mock_get_store.return_value = mock_store

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

        with pytest.raises(StepUpAuthRequired) as exc_info:
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


@pytest.mark.unit
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
            patch("app.services.mcp.mcp_client.integrations_collection") as mock_col,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.update_one = AsyncMock()
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
            patch("app.services.mcp.mcp_client.integrations_collection") as mock_col,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.update_one = AsyncMock()
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
            patch("app.services.mcp.mcp_client.integrations_collection") as mock_col,
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.update_one = AsyncMock()
            mock_resolver.resolve = AsyncMock(return_value=None)
            client.token_store.get_oauth_discovery = AsyncMock(return_value=None)
            client.token_store.delete_credentials = AsyncMock()

            await client.disconnect(INTEGRATION_ID)


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientHealthCheck:
    async def test_healthy(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=[])
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base

        result = await client.health_check(INTEGRATION_ID)
        assert result["status"] == "healthy"
        assert "latency_ms" in result

    async def test_disconnected(self):
        client = MCPClient(user_id=USER_ID)
        result = await client.health_check(INTEGRATION_ID)
        assert result["status"] == "disconnected"

    async def test_unhealthy_on_error(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(side_effect=Exception("timeout"))
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base

        result = await client.health_check(INTEGRATION_ID)
        assert result["status"] == "unhealthy"
        assert "timeout" in result["error"]


@pytest.mark.unit
class TestMCPClientIsConnected:
    def test_is_connected_true(self):
        client = MCPClient(user_id=USER_ID)
        client._clients[INTEGRATION_ID] = MagicMock()
        assert client.is_connected(INTEGRATION_ID) is True

    def test_is_connected_false(self):
        client = MCPClient(user_id=USER_ID)
        assert client.is_connected("unknown") is False


@pytest.mark.unit
class TestMCPClientIsConnectedDb:
    async def test_connected_in_db(self):
        client = MCPClient(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_client.user_integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(
                return_value={"user_id": USER_ID, "integration_id": INTEGRATION_ID}
            )
            assert await client.is_connected_db(INTEGRATION_ID) is True

    async def test_not_connected_in_db(self):
        client = MCPClient(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_client.user_integrations_collection"
        ) as mock_col:
            mock_col.find_one = AsyncMock(return_value=None)
            assert await client.is_connected_db(INTEGRATION_ID) is False


@pytest.mark.unit
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

        with patch.object(
            client, "is_connected_db", new_callable=AsyncMock, return_value=True
        ):
            with patch.object(
                client, "connect", new_callable=AsyncMock, return_value=tools
            ):
                result = await client.ensure_connected(INTEGRATION_ID)
                assert result is tools

    async def test_raises_when_not_connected(self):
        client = MCPClient(user_id=USER_ID)
        with patch.object(
            client, "is_connected_db", new_callable=AsyncMock, return_value=False
        ):
            with pytest.raises(ValueError, match="not connected"):
                await client.ensure_connected(INTEGRATION_ID)


@pytest.mark.unit
class TestMCPClientEnsureTokenValid:
    async def test_noop_when_no_credentials(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.has_credentials = AsyncMock(return_value=False)
        await client.ensure_token_valid(INTEGRATION_ID)

    async def test_refreshes_expiring_token(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.has_credentials = AsyncMock(return_value=True)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=True)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)
        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client._try_refresh_token = AsyncMock(return_value=True)
            await client.ensure_token_valid(INTEGRATION_ID)
            client._try_refresh_token.assert_awaited_once()

    async def test_no_refresh_when_not_expiring(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.has_credentials = AsyncMock(return_value=True)
        client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
        client._try_refresh_token = AsyncMock()
        await client.ensure_token_valid(INTEGRATION_ID)
        client._try_refresh_token.assert_not_awaited()


@pytest.mark.unit
class TestMCPClientTryTokenRefresh:
    async def test_refresh_success_evicts_stale_session(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = AsyncMock()
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client._try_refresh_token = AsyncMock(return_value=True)
            result = await client.try_token_refresh(INTEGRATION_ID)

        assert result is True
        assert INTEGRATION_ID not in client._tools
        assert INTEGRATION_ID not in client._clients
        mock_base.close_all_sessions.assert_awaited_once()

    async def test_refresh_returns_false_when_not_oauth(self):
        client = MCPClient(user_id=USER_ID)
        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=False)

        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            result = await client.try_token_refresh(INTEGRATION_ID)
        assert result is False


@pytest.mark.unit
class TestMCPClientGetAllConnectedTools:
    async def test_returns_cached_and_connects_new(self):
        client = MCPClient(user_id=USER_ID)
        cached_tools = [_mock_tool("cached")]
        client._tools["already_connected"] = cached_tools

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config()
        new_tools = [_mock_tool("new")]

        with (
            patch(
                "app.services.mcp.mcp_client.get_user_connected_integrations",
                new_callable=AsyncMock,
                return_value=[
                    {"integration_id": "already_connected"},
                    {"integration_id": "new_one"},
                ],
            ),
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client._safe_connect = AsyncMock(return_value=new_tools)

            result = await client.get_all_connected_tools()

        assert "already_connected" in result
        assert "new_one" in result

    async def test_returns_empty_when_no_integrations(self):
        client = MCPClient(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_client.get_user_connected_integrations",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await client.get_all_connected_tools()
        assert result == {}


@pytest.mark.unit
class TestMCPClientNormalizeServerUrl:
    def test_strips_trailing_slash(self):
        assert (
            MCPClient._normalize_server_url("https://ex.com/v1/") == "https://ex.com/v1"
        )

    def test_lowercases_scheme_and_host(self):
        assert (
            MCPClient._normalize_server_url("HTTPS://EX.COM/Path")
            == "https://ex.com/Path"
        )

    def test_empty_string(self):
        assert MCPClient._normalize_server_url("") == ""

    def test_none_like_input(self):
        assert MCPClient._normalize_server_url("  ") == ""


@pytest.mark.unit
class TestMCPClientCallToolOnServer:
    async def test_calls_tool_successfully(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(
            return_value={"content": [{"text": "result"}], "isError": False}
        )
        mock_session.call_tool = AsyncMock(return_value=mock_result)
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        # Mock _find_integration_id_by_server_url
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock(return_value=[_mock_tool()])

        result = await client.call_tool_on_server(
            SERVER_URL, "test_tool", {"arg": "val"}
        )
        assert result["isError"] is False

    async def test_raises_when_no_matching_integration(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="No connected MCP integration"):
            await client.call_tool_on_server("https://unknown.com", "tool", {})


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientGetActiveIntegrationIds:
    def test_returns_client_keys(self):
        client = MCPClient(user_id=USER_ID)
        client._clients["a"] = MagicMock()
        client._clients["b"] = MagicMock()
        assert set(client.get_active_integration_ids()) == {"a", "b"}


@pytest.mark.unit
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


@pytest.mark.unit
class TestStepUpAuthRequired:
    def test_attributes(self):
        exc = StepUpAuthRequired("my_int", ["read", "write"])
        assert exc.integration_id == "my_int"
        assert exc.required_scopes == ["read", "write"]
        assert "my_int" in str(exc)


@pytest.mark.unit
class TestDCRNotSupportedException:
    def test_can_be_raised(self):
        with pytest.raises(DCRNotSupportedException):
            raise DCRNotSupportedException("Server doesn't support DCR")


# ===========================================================================
# MCPClientPool Tests
# ===========================================================================


@pytest.mark.unit
class TestPooledClient:
    def test_touch_updates_timestamp(self):
        pooled = PooledClient(client=MagicMock())
        # Force a visible time delta
        pooled.last_used = datetime(2020, 1, 1, tzinfo=timezone.utc)
        pooled.touch()
        assert pooled.last_used > datetime(2020, 1, 1, tzinfo=timezone.utc)


@pytest.mark.unit
class TestMCPClientPoolGet:
    async def test_creates_new_client(self):
        pool = MCPClientPool(max_clients=10, ttl_seconds=60)
        with patch("app.services.mcp.mcp_client.MCPClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = await pool.get("user1")
            assert result is mock_instance
            assert pool.size == 1

    async def test_reuses_existing_client(self):
        pool = MCPClientPool(max_clients=10, ttl_seconds=60)
        mock_client = MagicMock()
        pool._clients["user1"] = PooledClient(client=mock_client)
        result = await pool.get("user1")
        assert result is mock_client
        assert pool.size == 1

    async def test_evicts_oldest_at_capacity(self):
        pool = MCPClientPool(max_clients=2, ttl_seconds=60)
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
        pool = MCPClientPool(max_clients=10, ttl_seconds=60)
        pool._clients["a"] = PooledClient(client=MagicMock())
        pool._clients["b"] = PooledClient(client=MagicMock())
        await pool.get("a")
        # 'a' should now be at end
        assert list(pool._clients.keys())[-1] == "a"


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientPoolCleanupStale:
    async def test_removes_stale_clients(self):
        pool = MCPClientPool(ttl_seconds=1)
        mock_client = MagicMock()
        mock_client.close_all_client_sessions = AsyncMock()
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        pool._clients["stale"] = PooledClient(client=mock_client, last_used=past)
        pool._clients["fresh"] = PooledClient(client=MagicMock())
        await pool.cleanup_stale()
        assert "stale" not in pool._clients
        assert "fresh" in pool._clients
        mock_client.close_all_client_sessions.assert_awaited_once()


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientPoolSize:
    def test_size_property(self):
        pool = MCPClientPool()
        assert pool.size == 0
        pool._clients["a"] = PooledClient(client=MagicMock())
        assert pool.size == 1


# ===========================================================================
# MCPTokenStore Tests
# ===========================================================================


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
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
        cred = _make_credential(
            auth_type=MCPAuthType.BEARER, status=MCPCredentialStatus.PENDING
        )
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result is None

    async def test_returns_none_when_no_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_credential = AsyncMock(return_value=None)
        result = await store.get_bearer_token(INTEGRATION_ID)
        assert result is None


@pytest.mark.unit
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
        past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
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


@pytest.mark.unit
class TestMCPTokenStoreIsTokenExpiringSoon:
    async def test_true_when_expiring_soon(self):
        store = MCPTokenStore(user_id=USER_ID)
        soon = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=60)
        cred = _make_credential(token_expires_at=soon)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(
            INTEGRATION_ID, threshold_seconds=300
        )
        assert result is True

    async def test_false_when_not_expiring_soon(self):
        store = MCPTokenStore(user_id=USER_ID)
        far_future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            hours=2
        )
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
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        cred = _make_credential(token_expires_at=None, connected_at=old)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is True

    async def test_fresh_token_without_expiry(self):
        """Token issued <1 hour ago with no expires_at should NOT be treated as expiring."""
        store = MCPTokenStore(user_id=USER_ID)
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
        cred = _make_credential(token_expires_at=None, connected_at=recent)
        store.get_credential = AsyncMock(return_value=cred)
        result = await store.is_token_expiring_soon(INTEGRATION_ID)
        assert result is False


@pytest.mark.unit
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
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        mock_session.add.assert_called_once()
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


@pytest.mark.unit
class TestMCPTokenStoreStoreBearerToken:
    async def test_stores_new_bearer(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        store._encrypt = MagicMock(return_value="encrypted")
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_bearer_token(INTEGRATION_ID, "my_token")
        mock_session.add.assert_called_once()
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


@pytest.mark.unit
class TestMCPTokenStoreOAuthState:
    async def test_create_and_verify_state(self):
        store = MCPTokenStore(user_id=USER_ID)
        stored_data: dict[str, Any] = {}

        async def fake_set_cache(key: str, data: Any, ttl: int = 0) -> None:
            stored_data[key] = data

        async def fake_get_and_delete(key: str) -> Any:
            return stored_data.pop(key, None)

        with (
            patch(
                "app.services.mcp.mcp_token_store.set_cache", side_effect=fake_set_cache
            ),
            patch(
                "app.services.mcp.mcp_token_store.get_and_delete_cache",
                side_effect=fake_get_and_delete,
            ),
        ):
            state = await store.create_oauth_state(INTEGRATION_ID, "verifier_123")
            assert isinstance(state, str)
            assert len(state) > 0

            is_valid, code_verifier = await store.verify_oauth_state(
                INTEGRATION_ID, state
            )
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPTokenStoreHasCredentials:
    async def test_true_with_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(access_token="enc_tok")
        store.get_credential = AsyncMock(return_value=cred)
        assert await store.has_credentials(INTEGRATION_ID) is True

    async def test_false_without_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        cred = _make_credential(access_token=None)
        store.get_credential = AsyncMock(return_value=cred)
        assert await store.has_credentials(INTEGRATION_ID) is False

    async def test_false_when_no_credential(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_credential = AsyncMock(return_value=None)
        assert await store.has_credentials(INTEGRATION_ID) is False


@pytest.mark.unit
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


@pytest.mark.unit
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
        mock_session.add.assert_called_once()
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


@pytest.mark.unit
class TestMCPTokenStoreOAuthDiscovery:
    async def test_store_and_get_discovery(self):
        store = MCPTokenStore(user_id=USER_ID)
        discovery = {"authorization_endpoint": "https://auth.example.com/authorize"}
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

    async def test_delete_discovery(self):
        store = MCPTokenStore(user_id=USER_ID)
        with patch(
            "app.services.mcp.mcp_token_store.delete_cache",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await store.delete_oauth_discovery(INTEGRATION_ID)
            assert result is True


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPTokenStoreIntrospect:
    async def test_introspect_success(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_oauth_discovery = AsyncMock(
            return_value={
                "introspection_endpoint": "https://auth.example.com/introspect"
            }
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
        store.get_oauth_discovery = AsyncMock(return_value={"token_endpoint": "x"})
        result = await store.introspect_token(INTEGRATION_ID)
        assert result is None

    async def test_introspect_no_token(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.get_oauth_discovery = AsyncMock(
            return_value={"introspection_endpoint": "https://e.com/introspect"}
        )
        store.get_oauth_token = AsyncMock(return_value=None)
        result = await store.introspect_token(INTEGRATION_ID)
        assert result is None


@pytest.mark.unit
class TestMCPTokenStoreCleanupIntegration:
    async def test_cleanup_removes_all(self):
        store = MCPTokenStore(user_id=USER_ID)
        store.delete_oauth_discovery = AsyncMock()
        store.delete_credentials = AsyncMock()
        await store.cleanup_integration(INTEGRATION_ID)
        store.delete_oauth_discovery.assert_awaited_once_with(INTEGRATION_ID)
        store.delete_credentials.assert_awaited_once_with(INTEGRATION_ID)


@pytest.mark.unit
class TestMCPTokenStoreStoreUnauthenticated:
    async def test_creates_record_if_missing(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_unauthenticated(INTEGRATION_ID)
        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    async def test_skips_if_already_exists(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential()
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.store_unauthenticated(INTEGRATION_ID)
        mock_session.add.assert_not_called()
        mock_session.commit.assert_not_awaited()


@pytest.mark.unit
class TestMCPTokenStoreUpdateStatus:
    async def test_updates_status(self):
        store = MCPTokenStore(user_id=USER_ID)
        existing = _make_credential()
        ctx_fn, mock_session = _fake_db_session(existing)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.update_status(INTEGRATION_ID, MCPCredentialStatus.ERROR, "fail")
        assert existing.status == MCPCredentialStatus.ERROR
        assert existing.error_message == "fail"
        mock_session.commit.assert_awaited_once()

    async def test_noop_when_not_found(self):
        store = MCPTokenStore(user_id=USER_ID)
        ctx_fn, mock_session = _fake_db_session(None)
        with patch("app.services.mcp.mcp_token_store.get_db_session", ctx_fn):
            await store.update_status(INTEGRATION_ID, MCPCredentialStatus.ERROR)
        mock_session.commit.assert_not_awaited()


# ===========================================================================
# Token Management Tests
# ===========================================================================


@pytest.mark.unit
class TestResolveClientCredentials:
    def test_from_config(self):
        config = _make_mcp_config(client_id="cid", client_secret="csec")
        cid, csec = resolve_client_credentials(config)
        assert cid == "cid"
        assert csec == "csec"

    def test_from_env(self):
        config = _make_mcp_config(
            client_id_env="MY_CLIENT_ID", client_secret_env="MY_SECRET"
        )
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


@pytest.mark.unit
class TestTryRefreshToken:
    async def test_successful_refresh(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config(
            client_id="cid", client_secret="csec", requires_auth=True
        )
        oauth_config = {
            "token_endpoint": "https://auth.example.com/token",
            "resource": SERVER_URL,
        }

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

            result = await try_refresh_token(
                token_store, INTEGRATION_ID, mcp_config, oauth_config
            )

        assert result is True
        token_store.store_oauth_tokens.assert_awaited_once()

    async def test_no_refresh_token(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value=None)

        result = await try_refresh_token(
            token_store,
            INTEGRATION_ID,
            _make_mcp_config(),
            {"token_endpoint": "https://auth.example.com/token"},
        )
        assert result is False

    async def test_no_token_endpoint(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")

        result = await try_refresh_token(
            token_store, INTEGRATION_ID, _make_mcp_config(), {}
        )
        assert result is False

    async def test_no_client_id(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        result = await try_refresh_token(
            token_store,
            INTEGRATION_ID,
            _make_mcp_config(),
            {"token_endpoint": "https://auth.example.com/token"},
        )
        assert result is False

    async def test_refresh_http_error(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = {"token_endpoint": "https://auth.example.com/token"}

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

            result = await try_refresh_token(
                token_store, INTEGRATION_ID, mcp_config, oauth_config
            )
        assert result is False

    async def test_refresh_exception(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = {"token_endpoint": "https://auth.example.com/token"}

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Network error")
            )
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(
                token_store, INTEGRATION_ID, mcp_config, oauth_config
            )
        assert result is False

    async def test_uses_dcr_client_id(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_dcr_client = AsyncMock(
            return_value={"client_id": "dcr_cid", "client_secret": "dcr_sec"}
        )
        token_store.store_oauth_tokens = AsyncMock()

        mcp_config = _make_mcp_config()
        oauth_config = {
            "token_endpoint": "https://auth.example.com/token",
            "resource": SERVER_URL,
        }

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

            result = await try_refresh_token(
                token_store, INTEGRATION_ID, mcp_config, oauth_config
            )

        assert result is True

    async def test_refresh_returns_empty_access_token(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="ref")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = {"token_endpoint": "https://auth.example.com/token"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"access_token": ""}

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await try_refresh_token(
                token_store, INTEGRATION_ID, mcp_config, oauth_config
            )
        assert result is False


@pytest.mark.unit
class TestRevokeTokens:
    async def test_revokes_both_tokens(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="refresh_tok")
        token_store.get_oauth_token = AsyncMock(return_value="access_tok")
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = {"revocation_endpoint": "https://auth.example.com/revoke"}

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock()
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            await revoke_tokens(token_store, INTEGRATION_ID, mcp_config, oauth_config)

        assert mock_client.post.await_count == 2

    async def test_skips_when_no_endpoint(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        await revoke_tokens(token_store, INTEGRATION_ID, _make_mcp_config(), {})
        token_store.get_refresh_token.assert_not_awaited()

    async def test_handles_revocation_error(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_refresh_token = AsyncMock(return_value="tok")
        token_store.get_oauth_token = AsyncMock(return_value=None)
        token_store.get_dcr_client = AsyncMock(return_value=None)

        mcp_config = _make_mcp_config(client_id="cid")
        oauth_config = {"revocation_endpoint": "https://auth.example.com/revoke"}

        with patch("app.services.mcp.token_management.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Network")
            )
            mock_http.return_value.__aexit__ = AsyncMock()

            # Should not raise
            await revoke_tokens(token_store, INTEGRATION_ID, mcp_config, oauth_config)


# ===========================================================================
# OAuth Discovery Tests
# ===========================================================================


@pytest.mark.unit
class TestDiscoverOAuthConfig:
    async def test_returns_cached(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        cached = {"authorization_endpoint": "https://auth.com/authorize"}
        token_store.get_oauth_discovery = AsyncMock(return_value=cached)

        result = await discover_oauth_config(
            token_store, INTEGRATION_ID, _make_mcp_config(requires_auth=True)
        )
        assert result is cached

    async def test_returns_static_metadata(self):
        token_store = AsyncMock(spec=MCPTokenStore)
        token_store.get_oauth_discovery = AsyncMock(return_value=None)

        metadata = {
            "authorization_endpoint": "https://auth.com/authorize",
            "token_endpoint": "https://auth.com/token",
        }
        config = _make_mcp_config(oauth_metadata=metadata)

        with patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"):
            result = await discover_oauth_config(token_store, INTEGRATION_ID, config)
        assert result == metadata

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
                return_value={
                    "resource": SERVER_URL,
                    "authorization_servers": ["https://auth.example.com"],
                    "scopes_supported": ["read", "write"],
                },
            ),
            patch(
                "app.services.mcp.oauth_discovery.select_authorization_server",
                new_callable=AsyncMock,
                return_value="https://auth.example.com",
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                return_value={
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                    "registration_endpoint": "https://auth.example.com/register",
                    "code_challenge_methods_supported": ["S256"],
                },
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(
                token_store, INTEGRATION_ID, mcp_config
            )
        assert result["discovery_method"] == "rfc9728_prm"
        assert result["authorization_endpoint"] == "https://auth.example.com/authorize"
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
                return_value={
                    "authorization_endpoint": "https://srv.example.com/authorize",
                    "token_endpoint": "https://srv.example.com/token",
                },
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(
                token_store, INTEGRATION_ID, mcp_config
            )
        assert result["discovery_method"] == "direct_oauth"

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
                return_value={
                    "resource": SERVER_URL,
                    "authorization_servers": ["https://auth.example.com"],
                },
            ),
            patch(
                "app.services.mcp.oauth_discovery.select_authorization_server",
                new_callable=AsyncMock,
                return_value="https://auth.example.com",
            ),
            patch(
                "app.services.mcp.oauth_discovery.fetch_auth_server_metadata",
                new_callable=AsyncMock,
                return_value={
                    "authorization_endpoint": "https://auth.example.com/authorize",
                    "token_endpoint": "https://auth.example.com/token",
                },
            ),
            patch("app.services.mcp.oauth_discovery.validate_https_url"),
            patch("app.services.mcp.oauth_discovery.validate_oauth_endpoints"),
        ):
            result = await discover_oauth_config(
                token_store, INTEGRATION_ID, mcp_config, challenge_data=challenge_data
            )
            # extract_auth_challenge should NOT be called because challenge_data was provided
            mock_extract.assert_not_awaited()
            assert result["initial_scope"] == "read"


@pytest.mark.unit
class TestProbeMcpConnection:
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


@pytest.mark.unit
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


@pytest.mark.unit
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

        adapter._convert_single_tool = mock_convert  # type: ignore[method-assign]

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

        adapter._convert_single_tool = always_fail  # type: ignore[method-assign]

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

        adapter._convert_single_tool = mock_convert  # type: ignore[method-assign]

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

        adapter._convert_single_tool = mock_convert  # type: ignore[method-assign]

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

        adapter._convert_single_tool = mock_convert  # type: ignore[method-assign]

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


@pytest.mark.unit
class TestMCPClientRegisterClient:
    async def test_successful_registration(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.store_dcr_client = AsyncMock()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"client_id": "new_client_id"}
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_http.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http.return_value.__aexit__ = AsyncMock()

            result = await client._register_client(
                INTEGRATION_ID,
                "https://auth.example.com/register",
                "https://myapp.com/callback",
            )

        assert result == "new_client_id"
        client.token_store.store_dcr_client.assert_awaited_once()

    async def test_dcr_not_supported_403(self):
        client = MCPClient(user_id=USER_ID)

        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedException):
                await client._register_client(
                    INTEGRATION_ID,
                    "https://auth.example.com/register",
                    "https://myapp.com/callback",
                )

    async def test_dcr_not_supported_404(self):
        client = MCPClient(user_id=USER_ID)

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedException):
                await client._register_client(
                    INTEGRATION_ID,
                    "https://auth.example.com/register",
                    "https://myapp.com/callback",
                )

    async def test_dcr_not_supported_405(self):
        client = MCPClient(user_id=USER_ID)

        mock_response = MagicMock()
        mock_response.status_code = 405

        mock_http_client = AsyncMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = mock_http_client
            mock_http.return_value = mock_cm

            with pytest.raises(DCRNotSupportedException):
                await client._register_client(
                    INTEGRATION_ID,
                    "https://auth.example.com/register",
                    "https://myapp.com/callback",
                )

    async def test_dcr_other_error(self):
        client = MCPClient(user_id=USER_ID)

        with patch("app.services.mcp.mcp_client.httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("Network error")
            )
            mock_http.return_value.__aexit__ = AsyncMock()

            with pytest.raises(ValueError, match="Dynamic Client Registration failed"):
                await client._register_client(
                    INTEGRATION_ID,
                    "https://auth.example.com/register",
                    "https://myapp.com/callback",
                )


# ===========================================================================
# MCPClient Session-based operations Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPClientListResourcesOnServer:
    async def test_list_resources(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(return_value={"resources": [{"name": "r1"}]})
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resources_on_server(SERVER_URL)
        assert "resources" in result

    async def test_list_resources_with_cursor(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(return_value={"resources": []})
        mock_session.list_resources = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        await client.list_resources_on_server(SERVER_URL, cursor="next_page")
        mock_session.list_resources.assert_awaited_once_with(cursor="next_page")


@pytest.mark.unit
class TestMCPClientReadResourceOnServer:
    async def test_read_resource(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(
            return_value={"contents": [{"text": "hello"}]}
        )
        mock_session.read_resource = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.read_resource_on_server(SERVER_URL, "file://test.txt")
        assert result["contents"][0]["text"] == "hello"


@pytest.mark.unit
class TestMCPClientListPromptsOnServer:
    async def test_list_prompts(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(return_value={"prompts": []})
        mock_session.list_prompts = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_prompts_on_server(SERVER_URL)
        assert "prompts" in result


@pytest.mark.unit
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
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
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
        mock_session.read_resource = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock()
        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_wrapper_returns_html(self):
        client = MCPClient(user_id=USER_ID)
        client.read_ui_resource_details = AsyncMock(
            return_value={"html": "<div>Hi</div>", "csp": None, "permissions": None}
        )
        result = await client.read_ui_resource(SERVER_URL, "ui://t/a.html")
        assert result == "<div>Hi</div>"

    async def test_read_ui_resource_wrapper_returns_none(self):
        client = MCPClient(user_id=USER_ID)
        client.read_ui_resource_details = AsyncMock(return_value=None)
        result = await client.read_ui_resource(SERVER_URL, "ui://t/a.html")
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
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
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
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
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
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock()

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None

    async def test_read_ui_resource_no_client(self):
        client = MCPClient(user_id=USER_ID)
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock()
        # No client in _clients

        result = await client.read_ui_resource_details(SERVER_URL, "ui://tool/app.html")
        assert result is None


# ===========================================================================
# MCPClient _find_integration_id_by_server_url Tests
# ===========================================================================


@pytest.mark.unit
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
                "app.services.mcp.mcp_client.get_user_connected_integrations",
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
                "app.services.mcp.mcp_client.get_user_connected_integrations",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            result = await client._find_integration_id_by_server_url(
                "https://unknown.example.com"
            )
        assert result is None

    async def test_skips_non_connected_db_integrations(self):
        client = MCPClient(user_id=USER_ID)
        with (
            patch(
                "app.services.mcp.mcp_client.get_user_connected_integrations",
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
                "app.services.mcp.mcp_client.get_user_connected_integrations",
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
                "app.services.mcp.mcp_client.get_user_connected_integrations",
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
# MCPClient _safe_connect Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPClientSafeConnect:
    async def test_returns_tools_on_success(self):
        client = MCPClient(user_id=USER_ID)
        tools = [_mock_tool()]
        client.connect = AsyncMock(return_value=tools)

        result = await client._safe_connect(INTEGRATION_ID)
        assert result is tools

    async def test_returns_none_on_failure(self):
        client = MCPClient(user_id=USER_ID)
        client.connect = AsyncMock(side_effect=Exception("Connection error"))

        with patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new_callable=AsyncMock,
        ):
            result = await client._safe_connect(INTEGRATION_ID)

        assert result is None

    async def test_resets_status_on_failure(self):
        client = MCPClient(user_id=USER_ID)
        client.connect = AsyncMock(side_effect=Exception("Connection error"))

        with patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new_callable=AsyncMock,
        ) as mock_update:
            await client._safe_connect(INTEGRATION_ID)

        mock_update.assert_awaited_once_with(USER_ID, INTEGRATION_ID, "created")

    async def test_handles_status_reset_error(self):
        client = MCPClient(user_id=USER_ID)
        client.connect = AsyncMock(side_effect=Exception("Connection error"))

        with patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new_callable=AsyncMock,
            side_effect=Exception("Status error"),
        ):
            result = await client._safe_connect(INTEGRATION_ID)

        assert result is None


# ===========================================================================
# MCPClient _safe_close_client Tests
# ===========================================================================


@pytest.mark.unit
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


@pytest.mark.unit
class TestMCPClientRevokeTokens:
    async def test_revokes_when_oauth_config_exists(self):
        client = MCPClient(user_id=USER_ID)
        oauth_config = {"revocation_endpoint": "https://auth.example.com/revoke"}
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


@pytest.mark.unit
class TestMCPClientGetSessionForServer:
    async def test_returns_session(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = MagicMock()
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
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
        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock()
        # No client in _clients

        with pytest.raises(ValueError, match="not connected in memory"):
            await client._get_session_for_server(SERVER_URL)


# ===========================================================================
# MCPClient list_resource_templates_on_server Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPClientListResourceTemplatesOnServer:
    async def test_list_templates(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(
            return_value={"resourceTemplates": [{"name": "t1"}]}
        )
        mock_session.list_resource_templates = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resource_templates_on_server(SERVER_URL)
        assert "resourceTemplates" in result

    async def test_list_templates_with_cursor(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.model_dump = MagicMock(return_value={"resourceTemplates": []})
        mock_session.list_resource_templates = AsyncMock(return_value=mock_result)
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        await client.list_resource_templates_on_server(SERVER_URL, cursor="page2")
        mock_session.list_resource_templates.assert_awaited_once_with(cursor="page2")

    async def test_list_templates_without_model_dump(self):
        client = MCPClient(user_id=USER_ID)
        mock_session = AsyncMock()

        # dict() fallback requires the result to be iterable like a dict
        mock_session.list_resource_templates = AsyncMock(
            return_value={"resourceTemplates": []}
        )
        client._get_session_for_server = AsyncMock(return_value=mock_session)

        result = await client.list_resource_templates_on_server(SERVER_URL)
        assert isinstance(result, dict)
        assert result["resourceTemplates"] == []


# ===========================================================================
# MCPClient build_oauth_auth_url Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPClientBuildOauthAuthUrl:
    async def test_builds_auth_url_with_preconfigured_client(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True, client_id="my_client", oauth_scopes=["read"]
        )

        oauth_config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["read", "write"],
        }

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
                "app.services.mcp.mcp_client.generate_pkce_pair",
                return_value=("verifier_123", "challenge_456"),
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
                await client.build_oauth_auth_url(
                    INTEGRATION_ID, "https://callback.com"
                )

    async def test_raises_when_no_client_id(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        oauth_config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
        }

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
                await client.build_oauth_auth_url(
                    INTEGRATION_ID, "https://callback.com"
                )

    async def test_uses_dcr_client_id(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        oauth_config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "code_challenge_methods_supported": ["S256"],
        }

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
                "app.services.mcp.mcp_client.generate_pkce_pair",
                return_value=("v", "c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.get_dcr_client = AsyncMock(
                return_value={"client_id": "dcr_id"}
            )
            client.token_store.create_oauth_state = AsyncMock(return_value="state")

            url = await client.build_oauth_auth_url(
                INTEGRATION_ID, "https://callback.com"
            )

        assert "client_id=dcr_id" in url

    async def test_raises_when_no_auth_endpoint(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True, client_id="cid")

        oauth_config = {
            "code_challenge_methods_supported": ["S256"],
        }

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
                "app.services.mcp.mcp_client.generate_pkce_pair",
                return_value=("v", "c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")

            with pytest.raises(ValueError, match="No authorization_endpoint"):
                await client.build_oauth_auth_url(
                    INTEGRATION_ID, "https://callback.com"
                )

    async def test_adds_nonce_for_openid_scope(self):
        client = MCPClient(user_id=USER_ID)

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(
            requires_auth=True,
            client_id="cid",
            oauth_scopes=["openid", "profile"],
        )

        oauth_config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "code_challenge_methods_supported": ["S256"],
        }

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
                "app.services.mcp.mcp_client.generate_pkce_pair",
                return_value=("v", "c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")
            client.token_store.store_oauth_nonce = AsyncMock()

            url = await client.build_oauth_auth_url(
                INTEGRATION_ID, "https://callback.com"
            )

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

        oauth_config = {
            "authorization_endpoint": "https://auth.example.com/authorize",
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["read", "offline_access"],
        }

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
                "app.services.mcp.mcp_client.generate_pkce_pair",
                return_value=("v", "c"),
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            client.token_store.create_oauth_state = AsyncMock(return_value="state")

            url = await client.build_oauth_auth_url(
                INTEGRATION_ID, "https://callback.com"
            )

        assert "offline_access" in url


# ===========================================================================
# MCPClient handle_oauth_callback Tests
# ===========================================================================


@pytest.mark.unit
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
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )

        with patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver:
            mock_resolver.resolve = AsyncMock(return_value=None)
            with pytest.raises(ValueError, match="not found"):
                await client.handle_oauth_callback(
                    INTEGRATION_ID, "code", "state", "https://callback.com"
                )

    async def test_raises_when_no_token_endpoint(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            mock_resolver.resolve = AsyncMock(return_value=resolved)
            with pytest.raises(ValueError, match="No token_endpoint"):
                await client.handle_oauth_callback(
                    INTEGRATION_ID, "code", "state", "https://callback.com"
                )

    async def test_raises_when_no_client_id_for_exchange(self):
        client = MCPClient(user_id=USER_ID)
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )

        resolved = MagicMock()
        resolved.mcp_config = _make_mcp_config(requires_auth=True)

        with (
            patch("app.services.mcp.mcp_client.IntegrationResolver") as mock_resolver,
            patch.object(
                client,
                "_discover_oauth_config",
                new_callable=AsyncMock,
                return_value={
                    "token_endpoint": "https://auth.example.com/token",
                },
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
        client.token_store.verify_oauth_state = AsyncMock(
            return_value=(True, "verifier")
        )

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
                return_value={
                    "token_endpoint": "https://auth.example.com/token",
                },
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


@pytest.mark.unit
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
            await client._handle_custom_integration_connect(
                INTEGRATION_ID, SERVER_URL, tools
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
            assert call_kwargs["name"] == "Resolved Name"


# ===========================================================================
# MCPClient call_tool_on_server - additional branch coverage
# ===========================================================================


@pytest.mark.unit
class TestMCPClientCallToolOnServerAdditional:
    async def test_call_tool_with_dict_result(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()
        # Return a plain dict without model_dump
        mock_session.call_tool = AsyncMock(
            return_value={"content": [{"text": "ok"}], "isError": False}
        )
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock(return_value=[_mock_tool()])

        result = await client.call_tool_on_server(
            SERVER_URL, "test_tool", {"arg": "val"}
        )
        assert result["isError"] is False

    async def test_call_tool_with_object_result(self):
        client = MCPClient(user_id=USER_ID)
        mock_base = MagicMock()
        mock_session = AsyncMock()

        class FakeResult:
            def __init__(self):
                self.content = [{"text": "ok"}]
                self.is_error = False

        mock_session.call_tool = AsyncMock(return_value=FakeResult())
        mock_base.get_session = MagicMock(return_value=mock_session)
        client._clients[INTEGRATION_ID] = mock_base
        client._tools[INTEGRATION_ID] = [_mock_tool()]

        client._find_integration_id_by_server_url = AsyncMock(
            return_value=INTEGRATION_ID
        )
        client.ensure_connected = AsyncMock(return_value=[_mock_tool()])

        result = await client.call_tool_on_server(SERVER_URL, "test_tool", {})
        assert "content" in result


# ===========================================================================
# MCPToolsStore Tests
# ===========================================================================


@pytest.mark.unit
class TestMCPToolsStoreFormatTools:
    def test_formats_tools(self):
        tools = [
            {"name": "  tool1  ", "description": "  desc1  "},
            {"name": "tool2", "description": "desc2"},
        ]
        result = _format_tools(tools)
        assert len(result) == 2
        assert result[0]["name"] == "tool1"
        assert result[0]["description"] == "desc1"

    def test_filters_empty_names(self):
        tools = [
            {"name": "", "description": "no name"},
            {"name": "   ", "description": "whitespace"},
            {"name": "valid", "description": "ok"},
        ]
        result = _format_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "valid"

    def test_handles_missing_fields(self):
        tools = [
            {"name": "tool1"},
            {"description": "no name"},
        ]
        result = _format_tools(tools)
        assert len(result) == 1
        assert result[0]["description"] == ""


@pytest.mark.unit
class TestMCPToolsStoreStore:
    async def test_store_tools_success(self):
        store = MCPToolsStore()
        tools = [{"name": "tool1", "description": "desc"}]

        with (
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_col,
            patch(
                "app.services.mcp.mcp_tools_store.delete_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.update_one = AsyncMock()
            await store.store_tools("int1", tools)
            mock_col.update_one.assert_awaited_once()

    async def test_store_tools_skips_empty(self):
        store = MCPToolsStore()
        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_col:
            mock_col.update_one = AsyncMock()
            await store.store_tools("int1", [])
            mock_col.update_one.assert_not_awaited()

    async def test_store_tools_skips_after_format_empty(self):
        store = MCPToolsStore()
        tools = [{"name": "", "description": "no name"}]
        with patch(
            "app.services.mcp.mcp_tools_store.integrations_collection"
        ) as mock_col:
            mock_col.update_one = AsyncMock()
            await store.store_tools("int1", tools)
            mock_col.update_one.assert_not_awaited()


@pytest.mark.unit
class TestMCPToolsStoreGetAll:
    async def test_get_all_tools_from_cache(self):
        store = MCPToolsStore()
        cached = {"int1": [{"name": "t1"}]}
        with patch(
            "app.services.mcp.mcp_tools_store.get_cache",
            new_callable=AsyncMock,
            return_value=cached,
        ):
            result = await store.get_all_mcp_tools()
        assert result == cached

    async def test_get_all_tools_from_db(self):
        store = MCPToolsStore()

        docs = [
            {
                "integration_id": "int1",
                "tools": [{"name": "t1", "description": "d"}],
                "name": "Integration 1",
                "icon_url": "https://ex.com/icon.png",
            },
        ]

        # Build an async iterator for `async for doc in cursor:`
        async def _aiter():
            for doc in docs:
                yield doc

        mock_cursor = _aiter()

        with (
            patch(
                "app.services.mcp.mcp_tools_store.get_cache",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.services.mcp.mcp_tools_store.integrations_collection"
            ) as mock_col,
            patch(
                "app.services.mcp.mcp_tools_store.set_cache",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.find.return_value = mock_cursor
            result = await store.get_all_mcp_tools()

        assert "int1" in result
        assert result["int1"]["name"] == "Integration 1"
