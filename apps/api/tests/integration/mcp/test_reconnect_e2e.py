"""End-to-end test for the MCP transparent-reconnect flow.

Spins up a real FastMCP streamable-HTTP server on a random localhost port,
points an MCPClient at it, then proves the production reconnect path:

1. Cold connect → tool call works.
2. Force the connector dead (mirrors what MCPClientPool eviction did before
   the resilience rewrite).
3. Call the tool again. The wrapper must transparently reconnect via
   MCPClient.reconnect_and_call and return the result. The error
   "MCP client is not connected" — the symptom we set out to eliminate —
   must not surface.

The test uses a real HTTP server with real MCP wire protocol, not mocks,
so a regression in the connector lifecycle or the reconnect wrapper would
fail this immediately.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.server.fastmcp import FastMCP
import pytest
import uvicorn

from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_client import MCPClient


def _pick_free_port() -> int:
    """Bind to port 0, read the OS-assigned port, then release."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_mcp_app():
    """A FastMCP server with a single deterministic echo tool."""
    mcp = FastMCP("reconnect-test-server", stateless_http=True)

    @mcp.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    return mcp.streamable_http_app()


class _ServerHandle:
    """Manage a uvicorn server in a background asyncio task for tests."""

    def __init__(self, port: int):
        self.port = port
        self.url = f"http://127.0.0.1:{port}/mcp"
        config = uvicorn.Config(
            _build_mcp_app(),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._server.config.load()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        # Wait until the server is actually accepting connections.
        for _ in range(50):
            if self._server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("FastMCP test server did not start in 2.5s")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task


@pytest.fixture
async def fastmcp_server():
    port = _pick_free_port()
    handle = _ServerHandle(port)
    await handle.start()
    try:
        yield handle
    finally:
        await handle.stop()


def _patch_resolver(server_url: str):
    """Stub IntegrationResolver.resolve so MCPClient sees our test server."""
    resolved = MagicMock()
    resolved.source = "platform"
    resolved.custom_doc = None
    resolved.mcp_config = MCPConfig(server_url=server_url, requires_auth=False)
    return patch(
        "app.services.mcp.mcp_client.IntegrationResolver.resolve",
        new=AsyncMock(return_value=resolved),
    )


def _patch_post_connect_side_effects():
    """Stub the database side effects in _do_connect so the test doesn't need
    Mongo/Postgres/Chroma/Redis.

    The reconnect path itself is what we're testing — the post-connect tasks
    are unrelated side effects and would otherwise require a full
    infrastructure stack just to validate connector lifecycle.
    """
    return [
        patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new=AsyncMock(),
        ),
        patch(
            "app.services.mcp.mcp_client.get_mcp_tools_store",
            return_value=MagicMock(store_tools=AsyncMock()),
        ),
        patch(
            "app.services.mcp.mcp_client.MCPClient._index_platform_mcp_tools",
            new=AsyncMock(),
        ),
    ]


def _make_unauth_token_store():
    """Token store stub for an unauthenticated MCP — every lookup returns None."""
    store = MagicMock()
    store.get_bearer_token = AsyncMock(return_value=None)
    store.is_token_expiring_soon = AsyncMock(return_value=False)
    store.store_unauthenticated = AsyncMock()
    return store


@pytest.mark.integration
class TestReconnectFlowE2E:
    """End-to-end coverage of the bug we set out to fix:
    'MCP client is not connected' after a connector is torn down.
    """

    async def test_cold_connect_calls_tool_successfully(self, fastmcp_server):
        """Baseline: a fresh MCPClient connects and calls a tool over real HTTP."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_unauth_token_store()

        with _patch_resolver(fastmcp_server.url):
            for p in _patch_post_connect_side_effects():
                p.start()
            try:
                tools = await client.connect("test-integration")
                assert tools, "expected at least one tool from the test server"

                echo_tool = next(t for t in tools if t.name == "echo")
                result = await echo_tool._arun(text="hello")
                # FastMCP wraps results in a content list whose text payload
                # carries our echo string.
                assert "echo:hello" in str(result)
            finally:
                for p in _patch_post_connect_side_effects():
                    p.stop()

    async def test_dead_connector_triggers_transparent_reconnect(self, fastmcp_server):
        """The headline regression test.

        Reproduces the 2026-05-26 17:50 production failure shape: a connector
        is torn down (mirroring MCPClientPool's old TTL eviction), then a
        tool call fires. With the resilience rewrite, the wrapper detects
        the dead connector, reconnects through MCPClient.reconnect_and_call,
        retries the call, and returns the result. The user never sees
        'MCP client is not connected'.
        """
        client = MCPClient(user_id="test-user")
        client.token_store = _make_unauth_token_store()

        active_patches: list[Any] = []
        try:
            for p in _patch_post_connect_side_effects():
                p.start()
                active_patches.append(p)

            with _patch_resolver(fastmcp_server.url):
                tools = await client.connect("test-integration")
                echo_tool = next(t for t in tools if t.name == "echo")

                # First call: warm path, succeeds straight through.
                first = await echo_tool._arun(text="warm")
                assert "echo:warm" in str(first)

                # Kill the connector to simulate pool eviction / network blip.
                # close_all_client_sessions used to be called on every TTL tick;
                # we're invoking it directly so the test doesn't depend on
                # timing.
                await client._clients["test-integration"].close_all_sessions()

                # Second call: connector is dead. The wrapper must catch the
                # 'not connected' error, call reconnect_and_call, retry
                # against the fresh connector, and return the result.
                second = await echo_tool._arun(text="hot")
                assert "MCP client is not connected" not in str(second), (
                    f"expected transparent reconnect, got error: {second!r}"
                )
                assert "echo:hot" in str(second), (
                    f"expected reconnected tool to return result, got: {second!r}"
                )
        finally:
            for p in active_patches:
                p.stop()
