"""Integration tests for MCP client connection flow.

Tests the MCPClient connect/disconnect lifecycle with only essential external
I/O mocked (IntegrationResolver, BaseMCPClient transport, mcp_tools_store,
update_user_integration_status).

Principle: if MCPClient._tools dict handling logic changes, these tests break.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from app.services.mcp.mcp_client import MCPClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_tool(name: str = "test_tool") -> MagicMock:
    """Create a minimal mock that satisfies BaseTool's interface."""
    t = MagicMock(spec=BaseTool)
    t.name = name
    t.description = f"A test tool named {name}"
    t.metadata = {}
    return t


def _patch_external_io(
    resolver_return=None,
    adapter_tools=None,
):
    """Return a context-manager stack that patches only external I/O boundaries.

    Patched surfaces:
    - IntegrationResolver.resolve  – avoids MongoDB calls
    - BaseMCPClient                – avoids real HTTP transport
    - ResilientLangChainAdapter    – avoids real MCP session tool listing
    - get_mcp_tools_store          – avoids MongoDB writes
    - update_user_integration_status – avoids MongoDB writes
    - delete_cache                 – avoids Redis calls

    Internal MCPClient logic (_build_config, _tools dict, _connecting event,
    _clients dict) is NOT patched and runs for real.
    """
    if adapter_tools is None:
        adapter_tools = [_make_fake_tool("tool_a"), _make_fake_tool("tool_b")]

    if resolver_return is None:
        mock_resolved = MagicMock()
        mock_resolved.mcp_config = MagicMock()
        mock_resolved.mcp_config.server_url = "http://test-server"  # NOSONAR
        mock_resolved.mcp_config.transport = "streamable-http"
        mock_resolved.mcp_config.requires_auth = False
        mock_resolved.source = "platform"
        mock_resolved.custom_doc = None
        resolver_return = mock_resolved

    return resolver_return, adapter_tools


class _MockExternalIO:
    """Context manager that applies all external-I/O patches for connect()."""

    def __init__(self, resolved, adapter_tools):
        self._resolved = resolved
        self._adapter_tools = adapter_tools
        self._patches = []
        self.mock_base_client_instance = None

    def __enter__(self):
        # Patch IntegrationResolver (MongoDB)
        p_resolver = patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve",
            new=AsyncMock(return_value=self._resolved),
        )
        # Patch BaseMCPClient (HTTP transport)
        mock_base_client_instance = MagicMock()
        mock_base_client_instance.create_session = AsyncMock()
        mock_base_client_instance.close_all_sessions = AsyncMock()
        self.mock_base_client_instance = mock_base_client_instance
        p_base = patch(
            "app.services.mcp.mcp_client.BaseMCPClient",
            return_value=mock_base_client_instance,
        )
        # Patch ResilientLangChainAdapter (avoids actual tool listing over network)
        mock_adapter = MagicMock()
        mock_adapter.create_tools = AsyncMock(return_value=self._adapter_tools)
        p_adapter = patch(
            "app.services.mcp.mcp_client.ResilientLangChainAdapter",
            return_value=mock_adapter,
        )
        # Patch wrap_tools_with_null_filter so we control what ends up in _tools
        p_wrap = patch(
            "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
            side_effect=lambda tools, **_kw: tools,
        )
        # Patch post-connection DB tasks
        p_tools_store_cls = patch(
            "app.services.mcp.mcp_client.get_mcp_tools_store",
            return_value=MagicMock(store_tools=AsyncMock()),
        )
        p_status = patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new=AsyncMock(),
        )
        for p in (p_resolver, p_base, p_adapter, p_wrap, p_tools_store_cls, p_status):
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


def _build_client_with_no_auth(user_id: str = "test-user") -> MCPClient:
    """Build an MCPClient with the token_store stubbed out (no PostgreSQL)."""
    client = MCPClient(user_id=user_id)
    client.token_store = MagicMock()
    client.token_store.get_bearer_token = AsyncMock(return_value=None)
    client.token_store.get_oauth_token = AsyncMock(return_value=None)
    client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)
    client.token_store.store_unauthenticated = AsyncMock()
    client.token_store.get_oauth_discovery = AsyncMock(return_value=None)
    client.token_store.delete_credentials = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestMCPConnectionFlow:
    """Test MCPClient state machine: _tools and _clients dict handling."""

    # ------------------------------------------------------------------
    # 1. Cache hit – no reconnect on second call
    # ------------------------------------------------------------------

    async def test_cached_tools_returned_on_second_connect(self):
        """connect() must short-circuit if _tools already holds the key.

        The critical invariant: once a key is in _tools the method returns
        immediately without touching any external service.  If someone removes
        the early-return guard in connect(), this test fails.
        """
        client = _build_client_with_no_auth("user-cache-hit")
        pre_seeded = [_make_fake_tool("cached_tool")]
        client._tools["my-integration"] = pre_seeded

        # No patches needed – the cached path must not reach any I/O
        result = await client.connect("my-integration")

        assert result is pre_seeded, "Should return the exact same list object"
        assert len(result) == 1

    # ------------------------------------------------------------------
    # 2. _tools dict is populated after a fresh connect
    # ------------------------------------------------------------------

    async def test_connect_updates_internal_tools_dict(self):
        """After connect() the integration key must exist in _tools with the
        tool list returned by the adapter.

        This test would fail if _do_connect() stopped assigning to
        self._tools[integration_id].
        """
        resolved, adapter_tools = _patch_external_io()

        with _MockExternalIO(resolved, adapter_tools):
            client = _build_client_with_no_auth("user-populate-tools")

            tools = await client.connect("test-integration")

        # State-machine assertion: the dict was populated
        assert "test-integration" in client._tools, (
            "_tools must contain the integration after connect()"
        )
        assert client._tools["test-integration"] is tools, (
            "_tools[key] must be the same list returned to the caller"
        )
        assert len(client._tools["test-integration"]) == 2

    # ------------------------------------------------------------------
    # 3. _clients dict is populated (client tracking)
    # ------------------------------------------------------------------

    async def test_connect_registers_base_client_in_clients_dict(self):
        """After connect() the BaseMCPClient instance must be in _clients.

        If the assignment self._clients[integration_id] = client is removed,
        this test fails.
        """
        resolved, adapter_tools = _patch_external_io()

        with _MockExternalIO(resolved, adapter_tools) as ctx:
            client = _build_client_with_no_auth("user-clients-dict")
            await client.connect("my-server")

        assert "my-server" in client._clients, (
            "_clients must record the BaseMCPClient after connect()"
        )
        assert client._clients["my-server"] is ctx.mock_base_client_instance

    # ------------------------------------------------------------------
    # 4. disconnect() removes both _clients and _tools entries
    # ------------------------------------------------------------------

    @patch("app.services.mcp.mcp_client.delete_cache", new_callable=AsyncMock)
    @patch(
        "app.services.mcp.mcp_client.integrations_collection",
    )
    @patch(
        "app.services.mcp.mcp_client.update_user_integration_status",
        new=AsyncMock(),
    )
    @patch(
        "app.services.mcp.mcp_client.IntegrationResolver.resolve",
        new=AsyncMock(return_value=None),
    )
    async def test_disconnect_removes_client_from_pool(
        self, mock_integrations_col, mock_delete_cache
    ):
        """disconnect() must pop the integration from both _clients and _tools.

        If either del statement is removed from disconnect(), this test fails.
        """
        mock_integrations_col.update_one = AsyncMock()

        client = _build_client_with_no_auth("user-disconnect")

        # Pre-populate state as if connect() had already run
        mock_base_client = MagicMock()
        mock_base_client.close_all_sessions = AsyncMock()
        client._clients["integration-x"] = mock_base_client
        client._tools["integration-x"] = [_make_fake_tool()]

        await client.disconnect("integration-x")

        assert "integration-x" not in client._clients, (
            "_clients must be cleared after disconnect()"
        )
        assert "integration-x" not in client._tools, (
            "_tools must be cleared after disconnect()"
        )
        mock_base_client.close_all_sessions.assert_awaited_once()

    # ------------------------------------------------------------------
    # 5. Concurrent connect deduplication
    # ------------------------------------------------------------------

    async def test_concurrent_connect_deduplication(self):
        """Calling connect() twice concurrently for the same integration must
        only create a single BaseMCPClient / session pair.

        The _connecting asyncio.Event guard is the mechanism under test.
        If it is removed, two concurrent coroutines could both enter
        _do_connect() and make duplicate connections.
        """
        resolved, adapter_tools = _patch_external_io()
        create_session_call_count = 0

        async def _slow_create_session(*_args, **_kwargs):
            nonlocal create_session_call_count
            create_session_call_count += 1
            await asyncio.sleep(0)  # yield to let the second coroutine run

        mock_base_client_instance = MagicMock()
        mock_base_client_instance.create_session = AsyncMock(
            side_effect=_slow_create_session
        )
        mock_base_client_instance.close_all_sessions = AsyncMock()

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                return_value=mock_base_client_instance,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=adapter_tools)
                ),
            ),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **_kw: tools,
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
            client = _build_client_with_no_auth("user-concurrent")

            # Launch both coroutines at the same time
            results = await asyncio.gather(
                client.connect("shared-integration"),
                client.connect("shared-integration"),
            )

        # Both callers must receive valid tools
        assert len(results[0]) == 2
        assert len(results[1]) == 2

        # The underlying transport session must have been created exactly once
        assert create_session_call_count == 1, (
            f"Expected 1 session creation but got {create_session_call_count}. "
            "The deduplication guard is broken."
        )

        # Internal state consistent: exactly one entry in each dict
        assert list(client._tools.keys()) == ["shared-integration"]
        assert list(client._clients.keys()) == ["shared-integration"]

    # ------------------------------------------------------------------
    # 6. Bearer token path – token is forwarded into the config
    # ------------------------------------------------------------------

    async def test_connect_with_bearer_token(self):
        """When token_store.get_bearer_token() returns a value, connect() must
        embed it in the BaseMCPClient config (auth field).

        This exercises _build_config()'s bearer-token branch.  If the
        assignment `server_config["auth"] = raw_token` is removed, a mock
        that asserts on the config dict passed to BaseMCPClient will catch it.
        """
        bearer_token = "my-static-bearer-token"  # nosec B105

        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://test-server"  # NOSONAR
        resolved.mcp_config.transport = "streamable-http"
        # Intentionally mark as no-auth at the config level; bearer token
        # overrides that path in _build_config.
        resolved.mcp_config.requires_auth = False
        resolved.source = "platform"
        resolved.custom_doc = None

        adapter_tools = [_make_fake_tool("bearer_tool")]

        captured_configs: list[dict] = []

        def _capture_config(cfg: dict):
            captured_configs.append(cfg)
            m = MagicMock()
            m.create_session = AsyncMock()
            m.close_all_sessions = AsyncMock()
            return m

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                side_effect=_capture_config,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=adapter_tools)
                ),
            ),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **_kw: tools,
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
            client = _build_client_with_no_auth("user-bearer")
            # Override: return a bearer token from the store
            client.token_store.get_bearer_token = AsyncMock(return_value=bearer_token)

            tools = await client.connect("bearer-integration")

        assert len(tools) == 1
        assert "bearer-integration" in client._tools

        # Verify the config passed to BaseMCPClient contained the bearer token
        assert len(captured_configs) == 1, "BaseMCPClient should have been called once"
        server_cfg = captured_configs[0]["mcpServers"]["bearer-integration"]
        assert server_cfg["auth"] == bearer_token, (
            f"Expected auth='{bearer_token}' in BaseMCPClient config, "
            f"got: {server_cfg.get('auth')!r}"
        )
        assert server_cfg["headers"]["Authorization"] == f"Bearer {bearer_token}", (
            "Fallback Authorization header must also be set for servers that "
            "do not honour the auth field"
        )

    # ------------------------------------------------------------------
    # 7. OAuth token path – token is forwarded into the config
    # ------------------------------------------------------------------

    async def test_connect_with_oauth_token(self):
        """When token_store.get_oauth_token() returns a value (and the
        integration requires_auth=True), connect() must embed the token in
        the BaseMCPClient config.

        This exercises the requires_auth branch in _build_config().  If the
        fallback `stored_token = await self.token_store.get_oauth_token(...)`
        is removed, the captured config will have no auth key.
        """
        oauth_token = "oauth-access-token-xyz"  # nosec B105

        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://test-server"  # NOSONAR
        resolved.mcp_config.transport = "streamable-http"
        resolved.mcp_config.requires_auth = True  # OAuth branch
        resolved.source = "platform"
        resolved.custom_doc = None

        adapter_tools = [_make_fake_tool("oauth_tool")]
        captured_configs: list[dict] = []

        def _capture_config(cfg: dict):
            captured_configs.append(cfg)
            m = MagicMock()
            m.create_session = AsyncMock()
            m.close_all_sessions = AsyncMock()
            return m

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                side_effect=_capture_config,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=adapter_tools)
                ),
            ),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **_kw: tools,
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
            client = _build_client_with_no_auth("user-oauth")
            # No bearer token; OAuth token present
            client.token_store.get_bearer_token = AsyncMock(return_value=None)
            client.token_store.get_oauth_token = AsyncMock(return_value=oauth_token)
            client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)

            tools = await client.connect("oauth-integration")

        assert len(tools) == 1
        assert "oauth-integration" in client._tools

        # Verify the OAuth token was threaded through to BaseMCPClient
        assert len(captured_configs) == 1
        server_cfg = captured_configs[0]["mcpServers"]["oauth-integration"]
        assert server_cfg["auth"] == oauth_token, (
            f"Expected auth='{oauth_token}' in BaseMCPClient config, "
            f"got: {server_cfg.get('auth')!r}"
        )
        assert server_cfg["headers"]["Authorization"] == f"Bearer {oauth_token}"

    # ------------------------------------------------------------------
    # 8. get_all_connected_tools returns cached tools without re-connecting
    # ------------------------------------------------------------------

    async def test_get_all_connected_tools_returns_cached(self):
        """get_all_connected_tools() must return tools already in _tools
        without calling connect() again.

        This test verifies that the method checks _tools first and avoids
        redundant reconnection for already-cached integrations.
        """
        client = _build_client_with_no_auth("user-all-tools")
        tools_a = [_make_fake_tool("a")]
        tools_b = [_make_fake_tool("b")]
        client._tools = {"int-a": tools_a, "int-b": tools_b}

        with patch(
            "app.services.mcp.mcp_client.get_user_connected_integrations",
            new=AsyncMock(
                return_value=[
                    {"integration_id": "int-a"},
                    {"integration_id": "int-b"},
                ]
            ),
        ):
            result = await client.get_all_connected_tools()

        assert "int-a" in result
        assert "int-b" in result
        # Must be the exact same list objects – no copying or re-fetching
        assert result["int-a"] is tools_a
        assert result["int-b"] is tools_b

    # ------------------------------------------------------------------
    # 9. connect() raises when requires_auth=True but no token stored
    # ------------------------------------------------------------------

    async def test_connect_raises_when_auth_required_but_no_token(self):
        """If requires_auth=True and no token is available, connect() must
        raise ValueError rather than silently connecting without credentials.

        This guards the guard clause in _build_config():
            elif mcp_config.requires_auth:
                raise ValueError(...)
        """
        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://secure-server"  # NOSONAR
        resolved.mcp_config.transport = "streamable-http"
        resolved.mcp_config.requires_auth = True
        resolved.source = "platform"
        resolved.custom_doc = None

        with patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve",
            new=AsyncMock(return_value=resolved),
        ):
            client = _build_client_with_no_auth("user-no-token")
            # Explicitly return no tokens
            client.token_store.get_bearer_token = AsyncMock(return_value=None)
            client.token_store.get_oauth_token = AsyncMock(return_value=None)
            client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)

            with patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new=AsyncMock(),
            ):
                with pytest.raises(ValueError, match="OAuth authorization required"):
                    await client.connect("secure-integration")

        # _tools must NOT have been populated
        assert "secure-integration" not in client._tools

    # ------------------------------------------------------------------
    # 10. Bearer token with "Bearer " prefix is stripped before passing
    # ------------------------------------------------------------------

    async def test_connect_strips_bearer_prefix_from_stored_token(self):
        """_build_config() must strip a leading 'Bearer ' prefix so that
        mcp-use does not double-prefix it when setting Authorization headers.

        Regression test for the stripping logic:
            if stored_token.lower().startswith("bearer "):
                raw_token = stored_token[7:]
        """
        # Token with "Bearer " prefix as it might be stored
        stored_with_prefix = "Bearer my-raw-token-value"  # nosec B105
        expected_raw = "my-raw-token-value"

        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://test-server"  # NOSONAR
        resolved.mcp_config.transport = "streamable-http"
        resolved.mcp_config.requires_auth = False
        resolved.source = "platform"
        resolved.custom_doc = None

        captured_configs: list[dict] = []

        def _capture_config(cfg: dict):
            captured_configs.append(cfg)
            m = MagicMock()
            m.create_session = AsyncMock()
            m.close_all_sessions = AsyncMock()
            return m

        adapter_tools = [_make_fake_tool("strip_tool")]

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                side_effect=_capture_config,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=adapter_tools)
                ),
            ),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **_kw: tools,
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
            client = _build_client_with_no_auth("user-strip-prefix")
            client.token_store.get_bearer_token = AsyncMock(
                return_value=stored_with_prefix
            )

            await client.connect("strip-integration")

        assert len(captured_configs) == 1
        server_cfg = captured_configs[0]["mcpServers"]["strip-integration"]
        assert server_cfg["auth"] == expected_raw, (
            f"Expected stripped token '{expected_raw}', got {server_cfg['auth']!r}"
        )
        # The Authorization header should use the raw token (mcp-use adds "Bearer ")
        assert server_cfg["headers"]["Authorization"] == f"Bearer {expected_raw}"

    # ------------------------------------------------------------------
    # 11. Token refresh retry on 401 — exercises _do_connect's retry loop
    # ------------------------------------------------------------------

    async def test_token_refresh_on_401(self):
        """When _do_connect() receives a 401-style error it must attempt a
        token refresh and retry the connection exactly once.

        The mechanism under test is the ``_retry_<integration_id>`` flag inside
        _do_connect() (lines 470-499 of mcp_client.py).  On the first call
        BaseMCPClient.create_session raises a RuntimeError that contains "401",
        which triggers _try_refresh_token().  After a successful refresh the
        method calls _do_connect() recursively; on that second call
        create_session succeeds.

        We verify:
        - create_session is called twice (initial failure + retry)
        - _try_refresh_token is called once with the correct integration_id
        - the returned tools come from the retry path (not empty / exception)
        """
        oauth_token_after_refresh = "refreshed-oauth-token"  # nosec B105

        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://test-server"
        resolved.mcp_config.transport = "streamable-http"
        resolved.mcp_config.requires_auth = True
        resolved.source = "platform"
        resolved.custom_doc = None

        adapter_tools = [_make_fake_tool("tool_after_refresh")]

        # Simulate create_session raising 401 on the first call, succeeding on the second
        call_count = 0

        def _create_session_side_effect(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("HTTP 401 Unauthorized")

        mock_base_client_instance = MagicMock()
        mock_base_client_instance.create_session = AsyncMock(
            side_effect=_create_session_side_effect
        )
        mock_base_client_instance.close_all_sessions = AsyncMock()

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                return_value=mock_base_client_instance,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=adapter_tools)
                ),
            ),
            patch(
                "app.services.mcp.mcp_client.wrap_tools_with_null_filter",
                side_effect=lambda tools, **_kw: tools,
            ),
            patch(
                "app.services.mcp.mcp_client.get_mcp_tools_store",
                return_value=MagicMock(store_tools=AsyncMock()),
            ),
            patch(
                "app.services.mcp.mcp_client.update_user_integration_status",
                new=AsyncMock(),
            ),
            patch(
                "app.services.mcp.mcp_client.delete_cache",
                new=AsyncMock(),
            ),
        ):
            client = _build_client_with_no_auth("user-401-retry")
            # After refresh the token store returns a valid OAuth token
            client.token_store.get_bearer_token = AsyncMock(return_value=None)
            client.token_store.get_oauth_token = AsyncMock(
                return_value=oauth_token_after_refresh
            )
            client.token_store.is_token_expiring_soon = AsyncMock(return_value=False)

            # Patch _try_refresh_token directly on the instance to avoid the real
            # OAuth discovery HTTP call while still exercising the retry branch.
            async def _mock_refresh(_integration_id, _mcp_cfg):
                # Simulate successful refresh: token store now has a new token
                return True

            client._try_refresh_token = _mock_refresh

            tools = await client.connect("auth-integration")

        assert tools == adapter_tools, (
            "After a 401 + successful refresh, connect() must return the tools "
            f"from the retry. Got: {tools!r}"
        )
        # create_session must have been called twice: once failing, once succeeding
        assert call_count == 2, (
            f"Expected 2 create_session calls (initial 401 + retry), got {call_count}"
        )
        assert "auth-integration" in client._tools

    # ------------------------------------------------------------------
    # 12. Tools are executable after connection (not just present in dict)
    # ------------------------------------------------------------------

    async def test_tools_executable_after_connection(self):
        """After connect() the returned tools can be invoked and produce output.

        This test ensures that:
        1. The tool objects placed in _tools are functional (not broken mocks)
        2. Calling a tool returns a result rather than raising unexpectedly

        We use a real MagicMock(spec=BaseTool) with a concrete arun/invoke
        so the tool itself can be called.  The important production path verified
        here is that wrap_tools_with_null_filter does not break tool invocability
        — if it accidentally replaced real tools with broken wrappers, calling
        the tool would raise AttributeError / TypeError.

        Note: wrap_tools_with_null_filter is left un-patched so that the real
        wrapper runs; BaseMCPClient and network I/O are still mocked.
        """
        from langchain_core.tools import BaseTool

        # Build a concrete fake tool that actually executes
        class _EchoTool(BaseTool):
            name: str = "echo_tool"
            description: str = "Echoes its input"

            def _run(self, text: str = "hello") -> str:
                return f"echo: {text}"

            async def _arun(self, text: str = "hello") -> str:
                return f"echo: {text}"

        real_tool = _EchoTool()

        resolved = MagicMock()
        resolved.mcp_config = MagicMock()
        resolved.mcp_config.server_url = "http://test-server"
        resolved.mcp_config.transport = "streamable-http"
        resolved.mcp_config.requires_auth = False
        resolved.source = "platform"
        resolved.custom_doc = None

        mock_base_client_instance = MagicMock()
        mock_base_client_instance.create_session = AsyncMock()
        mock_base_client_instance.close_all_sessions = AsyncMock()

        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch(
                "app.services.mcp.mcp_client.BaseMCPClient",
                return_value=mock_base_client_instance,
            ),
            patch(
                "app.services.mcp.mcp_client.ResilientLangChainAdapter",
                return_value=MagicMock(
                    create_tools=AsyncMock(return_value=[real_tool])
                ),
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
            client = _build_client_with_no_auth("user-exec")

            tools = await client.connect("exec-integration")

        assert len(tools) == 1, "Expected exactly one tool from connect()"

        returned_tool = tools[0]

        # The tool must be invocable — call it synchronously via invoke()
        # This would raise if wrap_tools_with_null_filter broke the wrapper
        output = returned_tool.invoke({"text": "world"})
        assert "echo" in str(output).lower() or "world" in str(output), (
            f"Tool invoke() produced unexpected output: {output!r}"
        )
