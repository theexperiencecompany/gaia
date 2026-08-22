"""Unit tests for the MCP proxy API endpoints.

Tests cover all five proxy endpoints (tool-call, resources/list,
resources/templates/list, resources/read, prompts/list).
Service layer is mocked; only HTTP status codes, response shapes,
and error handling are verified.
"""

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from mcp.types import (
    CallToolResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    Prompt,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl

from app.services.analytics_service import AnalyticsEvents

API = "/api/v1/mcp"


class TestProxyToolCall:
    """POST /api/v1/mcp/proxy/tool-call"""

    async def test_tool_call_success(self, client: AsyncClient) -> None:
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="hello")], isError=False
        )
        with (
            patch(
                "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
                new_callable=AsyncMock,
            ) as mock_get,
            patch("app.api.v1.endpoints.mcp_proxy.capture_context_event") as mock_capture,
        ):
            mock_client = AsyncMock()
            mock_client.call_tool_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={
                    "server_url": "https://example.com/mcp",
                    "tool_name": "test_tool",
                    "arguments": {"key": "val"},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"][0]["type"] == "text"
        assert data["content"][0]["text"] == "hello"
        assert data["is_error"] is False
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TOOL_USED,
            {"tool_name": "test_tool", "source": "mcp_app"},
        )

    async def test_tool_call_with_error_flag(self, client: AsyncClient) -> None:
        mock_result = CallToolResult(content=[], isError=True)
        with (
            patch(
                "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
                new_callable=AsyncMock,
            ) as mock_get,
            patch("app.api.v1.endpoints.mcp_proxy.capture_context_event") as mock_capture,
        ):
            mock_client = AsyncMock()
            mock_client.call_tool_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={
                    "server_url": "https://example.com/mcp",
                    "tool_name": "failing_tool",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["is_error"] is True
        mock_capture.assert_called_once_with(
            AnalyticsEvents.TOOL_USED,
            {"tool_name": "failing_tool", "source": "mcp_app"},
        )

    async def test_tool_call_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.call_tool_on_server.side_effect = RuntimeError("conn refused")
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={
                    "server_url": "https://example.com/mcp",
                    "tool_name": "test_tool",
                },
            )
        assert resp.status_code == 500
        assert "Tool call failed" in resp.json()["detail"]

    async def test_tool_call_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/proxy/tool-call", json={})
        assert resp.status_code == 422

    async def test_tool_call_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/tool-call",
            json={
                "server_url": "https://example.com/mcp",
                "tool_name": "test_tool",
            },
        )
        assert resp.status_code == 401


class TestProxyResourcesList:
    """POST /api/v1/mcp/proxy/resources/list"""

    async def test_resources_list_success(self, client: AsyncClient) -> None:
        mock_result = ListResourcesResult(
            resources=[Resource(uri=AnyUrl("file:///a.txt"), name="a.txt")],
            nextCursor="cur1",
        )
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resources_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["resources"]) == 1
        assert data["next_cursor"] == "cur1"

    async def test_resources_list_with_cursor(self, client: AsyncClient) -> None:
        mock_result = ListResourcesResult(resources=[])
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resources_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/list",
                json={"server_url": "https://example.com/mcp", "cursor": "page2"},
            )
        assert resp.status_code == 200
        assert resp.json()["resources"] == []

    async def test_resources_list_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resources_on_server.side_effect = RuntimeError("boom")
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 500
        assert "resources/list failed" in resp.json()["detail"]

    async def test_resources_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/list",
            json={"server_url": "https://example.com/mcp"},
        )
        assert resp.status_code == 401


class TestProxyResourceTemplatesList:
    """POST /api/v1/mcp/proxy/resources/templates/list"""

    async def test_templates_list_success(self, client: AsyncClient) -> None:
        mock_result = ListResourceTemplatesResult(
            resourceTemplates=[ResourceTemplate(uriTemplate="file:///{path}", name="file")]
        )
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resource_templates_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/templates/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["resource_templates"]) == 1

    async def test_templates_list_serializes_camel_case(self, client: AsyncClient) -> None:
        """The SDK's camelCase fields reach the client under their alias names."""
        mock_result = ListResourceTemplatesResult(
            resourceTemplates=[ResourceTemplate(uriTemplate="file:///{x}", name="t")],
            nextCursor="c2",
        )
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resource_templates_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/templates/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["resource_templates"][0]["uriTemplate"] == "file:///{x}"
        assert data["next_cursor"] == "c2"

    async def test_templates_list_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_resource_templates_on_server.side_effect = RuntimeError("err")
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/templates/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 500

    async def test_templates_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/templates/list",
            json={"server_url": "https://example.com/mcp"},
        )
        assert resp.status_code == 401


class TestProxyResourceRead:
    """POST /api/v1/mcp/proxy/resources/read"""

    async def test_resource_read_success(self, client: AsyncClient) -> None:
        mock_result = ReadResourceResult(
            contents=[TextResourceContents(uri=AnyUrl("file:///a.txt"), text="hello world")]
        )
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.read_resource_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/read",
                json={
                    "server_url": "https://example.com/mcp",
                    "uri": "file:///a.txt",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["contents"]) == 1
        assert data["contents"][0]["text"] == "hello world"

    async def test_resource_read_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.read_resource_on_server.side_effect = RuntimeError("boom")
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/resources/read",
                json={
                    "server_url": "https://example.com/mcp",
                    "uri": "file:///a.txt",
                },
            )
        assert resp.status_code == 500
        assert "resources/read failed" in resp.json()["detail"]

    async def test_resource_read_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/proxy/resources/read", json={})
        assert resp.status_code == 422

    async def test_resource_read_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/read",
            json={"server_url": "https://example.com/mcp", "uri": "file:///a.txt"},
        )
        assert resp.status_code == 401


class TestProxyPromptsList:
    """POST /api/v1/mcp/proxy/prompts/list"""

    async def test_prompts_list_success(self, client: AsyncClient) -> None:
        mock_result = ListPromptsResult(prompts=[Prompt(name="greet", description="Say hi")])
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_prompts_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/prompts/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["prompts"]) == 1
        assert data["prompts"][0]["name"] == "greet"

    async def test_prompts_list_with_cursor(self, client: AsyncClient) -> None:
        mock_result = ListPromptsResult(prompts=[], nextCursor="c3")
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_prompts_on_server.return_value = mock_result
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/prompts/list",
                json={"server_url": "https://example.com/mcp", "cursor": "c2"},
            )
        assert resp.status_code == 200
        assert resp.json()["next_cursor"] == "c3"

    async def test_prompts_list_service_error(self, client: AsyncClient) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_client = AsyncMock()
            mock_client.list_prompts_on_server.side_effect = RuntimeError("err")
            mock_get.return_value = mock_client
            resp = await client.post(
                f"{API}/proxy/prompts/list",
                json={"server_url": "https://example.com/mcp"},
            )
        assert resp.status_code == 500
        assert "prompts/list failed" in resp.json()["detail"]

    async def test_prompts_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/prompts/list",
            json={"server_url": "https://example.com/mcp"},
        )
        assert resp.status_code == 401
