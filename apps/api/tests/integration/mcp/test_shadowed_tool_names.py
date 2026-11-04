"""An MCP server's tool named like a GAIA tool stays reachable, over the real MCP wire.

Dodo Payments' server exposes execute, the name of GAIA's own execute proxy.
The executor's bound tools and the execute resolver both key on name, so GAIA's
proxy silently replaced the server's tool and the model never saw it.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from mcp.server.fastmcp import FastMCP
import pytest

from app.agents.tools.execute.resolver import ResolvedTool
from app.agents.tools.execute.schema_docs import render_tool_doc
from app.agents.tools.execute.tool_info import tool_contract
from app.constants.execute import RETURNS_INLINE_MAX_CHARS
from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_client import MCPClient
from tests.helpers import serve_asgi

INTEGRATION_ID = "dodo-integration"
RENAMED_EXECUTE = "dodo_payments_execute"


def _dodo_like_app():
    mcp = FastMCP("dodo-like", stateless_http=True)

    @mcp.tool()
    def execute(code: str) -> str:
        """Run code against the payments SDK."""
        return f"ran:{code}"

    @mcp.tool()
    def search_docs(query: str) -> str:
        return f"docs:{query}"

    return mcp.streamable_http_app()


@pytest.fixture
async def dodo_like_server_url() -> AsyncIterator[str]:
    async with serve_asgi(_dodo_like_app()) as base_url:
        yield f"{base_url}/mcp"


@contextmanager
def _integration_at(server_url: str) -> Iterator[None]:
    resolved = MagicMock()
    resolved.name = "Dodo Payments"
    resolved.source = "platform"
    resolved.custom_doc = None
    resolved.mcp_config = MCPConfig(server_url=server_url, requires_auth=False)
    with (
        patch(
            "app.services.mcp.mcp_client.IntegrationResolver.resolve",
            new=AsyncMock(return_value=resolved),
        ),
        patch("app.services.mcp.mcp_client.update_user_integration_status", new=AsyncMock()),
        patch("app.services.mcp.mcp_client.store_mcp_tools", new=AsyncMock()),
        patch("app.services.mcp.mcp_client.MCPClient._index_platform_mcp_tools", new=AsyncMock()),
    ):
        yield


async def _connect(server_url: str) -> tuple[MCPClient, list[BaseTool]]:
    client = MCPClient(user_id="test-user")
    client.token_store = MagicMock(
        get_bearer_token=AsyncMock(return_value=None),
        is_token_expiring_soon=AsyncMock(return_value=False),
        store_unauthenticated=AsyncMock(),
    )
    with _integration_at(server_url):
        tools = await client.connect(INTEGRATION_ID)
    return client, tools


@pytest.mark.integration
class TestShadowedToolNames:
    async def test_a_tool_named_like_a_gaia_tool_is_renamed_and_others_keep_their_name(
        self, dodo_like_server_url: str
    ) -> None:
        client, tools = await _connect(dodo_like_server_url)

        assert {t.name for t in tools} == {RENAMED_EXECUTE, "search_docs"}
        assert client.find_integration(RENAMED_EXECUTE) == INTEGRATION_ID

    @pytest.mark.usefixtures("no_observed_tool_shapes")
    async def test_the_model_is_told_the_server_calls_it_by_its_old_name(
        self, dodo_like_server_url: str
    ) -> None:
        _, tools = await _connect(dodo_like_server_url)
        renamed = next(t for t in tools if t.name == RENAMED_EXECUTE)
        untouched = next(t for t in tools if t.name == "search_docs")

        bound = convert_to_openai_tool(renamed)["function"]["description"]
        contract = await tool_contract(ResolvedTool(renamed.name, renamed, True))
        documented = render_tool_doc(contract, RETURNS_INLINE_MAX_CHARS)

        for seen_by_model in (bound, documented):
            assert "called execute on its own server" in seen_by_model
            assert f"always call it as {RENAMED_EXECUTE}" in seen_by_model
        assert bound.endswith("Run code against the payments SDK.")
        assert "on its own server" not in untouched.description

    async def test_the_renamed_tool_still_calls_the_server_by_its_own_name(
        self, dodo_like_server_url: str
    ) -> None:
        _, tools = await _connect(dodo_like_server_url)
        renamed = next(t for t in tools if t.name == RENAMED_EXECUTE)

        assert "ran:1+1" in str(await renamed.ainvoke({"code": "1+1"}))

    async def test_the_renamed_tool_survives_a_transparent_reconnect(
        self, dodo_like_server_url: str
    ) -> None:
        client, tools = await _connect(dodo_like_server_url)
        renamed = next(t for t in tools if t.name == RENAMED_EXECUTE)
        await client._clients[INTEGRATION_ID].close_all_sessions()

        with _integration_at(dodo_like_server_url):
            result = await renamed.ainvoke({"code": "again"})

        assert "ran:again" in str(result)
