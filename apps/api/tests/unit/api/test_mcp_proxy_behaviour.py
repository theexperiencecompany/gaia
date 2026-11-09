"""Each MCP proxy route must act on the calling user's MCP client."""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from mcp.types import (
    CallToolResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
)
import pytest

from tests.conftest import FAKE_USER

pytestmark = pytest.mark.unit

API = "/api/v1/mcp"
_MODULE = "app.api.v1.endpoints.mcp_proxy"
SERVER_URL = "https://example.com/mcp"


async def _post_with_client_sentinel(
    client: AsyncClient,
    path: str,
    body: dict[str, object],
    service_fn: str,
    result: object,
) -> tuple[MagicMock, AsyncMock, AsyncMock]:
    mcp_client = MagicMock(name="user_mcp_client")
    with (
        patch(f"{_MODULE}.get_mcp_client", new_callable=AsyncMock, return_value=mcp_client) as get,
        patch(f"{_MODULE}.{service_fn}", new_callable=AsyncMock, return_value=result) as fn,
        patch(f"{_MODULE}.capture"),
    ):
        resp = await client.post(f"{API}{path}", json=body)
    assert resp.status_code == 200
    return mcp_client, get, fn


class TestProxyUsesTheUsersClient:
    async def test_tool_call(self, client: AsyncClient) -> None:
        mcp_client, get, fn = await _post_with_client_sentinel(
            client,
            "/proxy/tool-call",
            {"server_url": SERVER_URL, "tool_name": "t", "arguments": {"a": 1}},
            "call_tool_on_server",
            CallToolResult(content=[], isError=False),
        )

        get.assert_awaited_once_with(user_id=FAKE_USER.user_id)
        fn.assert_awaited_once_with(
            mcp_client, server_url=SERVER_URL, tool_name="t", arguments={"a": 1}
        )

    async def test_resources_list(self, client: AsyncClient) -> None:
        mcp_client, get, fn = await _post_with_client_sentinel(
            client,
            "/proxy/resources/list",
            {"server_url": SERVER_URL, "cursor": "c1"},
            "list_resources_on_server",
            ListResourcesResult(resources=[]),
        )

        get.assert_awaited_once_with(user_id=FAKE_USER.user_id)
        fn.assert_awaited_once_with(mcp_client, server_url=SERVER_URL, cursor="c1")

    async def test_resource_templates_list(self, client: AsyncClient) -> None:
        mcp_client, get, fn = await _post_with_client_sentinel(
            client,
            "/proxy/resources/templates/list",
            {"server_url": SERVER_URL, "cursor": "c2"},
            "list_resource_templates_on_server",
            ListResourceTemplatesResult(resourceTemplates=[]),
        )

        get.assert_awaited_once_with(user_id=FAKE_USER.user_id)
        fn.assert_awaited_once_with(mcp_client, server_url=SERVER_URL, cursor="c2")

    async def test_resource_read(self, client: AsyncClient) -> None:
        mcp_client, get, fn = await _post_with_client_sentinel(
            client,
            "/proxy/resources/read",
            {"server_url": SERVER_URL, "uri": "ui://app"},
            "read_resource_on_server",
            ReadResourceResult(contents=[]),
        )

        get.assert_awaited_once_with(user_id=FAKE_USER.user_id)
        fn.assert_awaited_once_with(mcp_client, server_url=SERVER_URL, uri="ui://app")

    async def test_prompts_list(self, client: AsyncClient) -> None:
        mcp_client, get, fn = await _post_with_client_sentinel(
            client,
            "/proxy/prompts/list",
            {"server_url": SERVER_URL, "cursor": "c3"},
            "list_prompts_on_server",
            ListPromptsResult(prompts=[]),
        )

        get.assert_awaited_once_with(user_id=FAKE_USER.user_id)
        fn.assert_awaited_once_with(mcp_client, server_url=SERVER_URL, cursor="c3")
