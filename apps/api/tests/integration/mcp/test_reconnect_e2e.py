"""End-to-end test for the MCP transparent-reconnect flow.

Spins up a real FastMCP streamable-HTTP server on a random localhost port,
points an MCPClient at it, then proves: cold connect works; forcing the
connector dead (mirrors what MCPClientPool eviction did before the
resilience rewrite) does not break the next tool call, which transparently
reconnects via MCPClient.reconnect_and_call without surfacing "MCP client
is not connected" — the symptom this fixes.

Uses a real HTTP server with the real MCP wire protocol, not mocks, so a
regression in the connector lifecycle or reconnect wrapper fails this test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.server.fastmcp import FastMCP
import pytest

from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_client import MCPClient
from tests.helpers import serve_asgi


def _build_mcp_app():
    """Build a FastMCP server with a single deterministic echo tool."""
    mcp = FastMCP("reconnect-test-server", stateless_http=True)

    @mcp.tool()
    def echo(text: str) -> str:
        return f"echo:{text}"

    return mcp.streamable_http_app()


@pytest.fixture
async def fastmcp_server_url() -> AsyncIterator[str]:
    async with serve_asgi(_build_mcp_app()) as base_url:
        yield f"{base_url}/mcp"


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
    """Stub the database side effects in _do_connect (Mongo/Postgres/Chroma/Redis) so only the reconnect path under test needs no real infra."""
    return [
        patch(
            "app.services.mcp.mcp_client.update_user_integration_status",
            new=AsyncMock(),
        ),
        patch(
            "app.services.mcp.mcp_client.store_mcp_tools",
            new=AsyncMock(),
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
    """End-to-end coverage of the bug we set out to fix: 'MCP client is not connected' after a connector is torn down."""

    async def test_cold_connect_calls_tool_successfully(self, fastmcp_server_url):
        """Baseline: a fresh MCPClient connects and calls a tool over real HTTP."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_unauth_token_store()

        with _patch_resolver(fastmcp_server_url):
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

    async def test_dead_connector_triggers_transparent_reconnect(self, fastmcp_server_url):
        """Regression test for the 2026-05-26 17:50 production failure: a reconnect must not surface 'MCP client is not connected'."""
        client = MCPClient(user_id="test-user")
        client.token_store = _make_unauth_token_store()

        active_patches: list[Any] = []
        try:
            for p in _patch_post_connect_side_effects():
                p.start()
                active_patches.append(p)

            with _patch_resolver(fastmcp_server_url):
                tools = await client.connect("test-integration")
                echo_tool = next(t for t in tools if t.name == "echo")

                # First call: warm path, succeeds straight through.
                first = await echo_tool._arun(text="warm")
                assert "echo:warm" in str(first)

                # Simulate pool eviction/network blip; invoked directly so the test doesn't depend on TTL timing.
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
