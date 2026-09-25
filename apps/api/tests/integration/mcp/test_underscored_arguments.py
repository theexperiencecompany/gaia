"""A server tool whose arguments start with an underscore still receives them, over the real MCP wire.

Pydantic rejects field names with a leading underscore, so the model is shown
_id as id. The server still requires _id, and used to receive id instead.
"""

import asyncio
from collections.abc import AsyncIterator
import contextlib
import socket
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send
import uvicorn

from app.models.mcp_config import MCPConfig
from app.services.mcp.mcp_client import MCPClient

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "_id": {"type": "string"},
        "meta": {"type": "object", "properties": {"_rev": {"type": "string"}}},
    },
    "required": ["_id"],
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _underscored_app() -> Starlette:
    server: Server = Server("underscored")

    @server.list_tools()
    async def _list() -> list[Tool]:
        return [Tool(name="get_document", description="Fetch one.", inputSchema=INPUT_SCHEMA)]

    @server.call_tool()
    async def _call(name: str, arguments: dict[str, object]) -> list[TextContent]:
        if "_id" not in arguments:
            raise ValueError(f"missing required _id, got {sorted(arguments)}")
        return [TextContent(type="text", text=f"got:{arguments['_id']}:{arguments.get('meta')}")]

    manager = StreamableHTTPSessionManager(app=server, stateless=True)

    async def _handle(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def _lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    return Starlette(routes=[Mount("/mcp", app=_handle)], lifespan=_lifespan)


@pytest.fixture
async def server_url() -> AsyncIterator[str]:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_underscored_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}/mcp/"
    finally:
        server.should_exit = True
        await task


@pytest.mark.integration
class TestUnderscoredArguments:
    @pytest.mark.regression
    async def test_the_server_receives_the_underscored_names_it_declared(
        self, server_url: str
    ) -> None:
        resolved = MagicMock()
        resolved.name = "Docs"
        resolved.source = "platform"
        resolved.custom_doc = None
        resolved.mcp_config = MCPConfig(server_url=server_url, requires_auth=False)
        client = MCPClient(user_id="test-user")
        client.token_store = MagicMock(
            get_bearer_token=AsyncMock(return_value=None),
            is_token_expiring_soon=AsyncMock(return_value=False),
            store_unauthenticated=AsyncMock(),
        )
        with (
            patch(
                "app.services.mcp.mcp_client.IntegrationResolver.resolve",
                new=AsyncMock(return_value=resolved),
            ),
            patch("app.services.mcp.mcp_client.update_user_integration_status", new=AsyncMock()),
            patch("app.services.mcp.mcp_client.store_mcp_tools", new=AsyncMock()),
            patch(
                "app.services.mcp.mcp_client.MCPClient._index_platform_mcp_tools",
                new=AsyncMock(),
            ),
        ):
            (tool,) = await client.connect("docs")

        result = await tool.ainvoke({"id": "doc-1", "meta": {"rev": "r7"}})

        assert result == "got:doc-1:{'_rev': 'r7'}"
