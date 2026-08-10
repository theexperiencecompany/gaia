"""Unit tests for the MCP proxy API endpoints.

Tests cover all five proxy endpoints (tool-call, resources/list,
resources/templates/list, resources/read, prompts/list). The MCP client
factory is the mocked seam; the request mapping, response shaping, error
wrapping, and wide-event logging in the endpoint itself run for real and are
asserted exactly — status codes, full response bodies, exact service call
args, and the log fields each path emits.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
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
import pytest

from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.constants.log_tags import LogTag
from shared.py.wide_events import McpContext

API = "/api/v1/mcp"
USER_ID = "507f1f77bcf86cd799439011"
SERVER_URL = "https://example.com/mcp"


@contextmanager
def _patched_mcp() -> Iterator[tuple[AsyncMock, AsyncMock, MagicMock]]:
    """Patch the MCP client factory and the wide-event log for one request.

    Returns (mock_get, mock_client, mock_log): attach the service result to
    ``mock_client.<method>`` before the request, then assert on the exact
    service call args and log fields after it.
    """
    mock_get = AsyncMock()
    mock_client = AsyncMock()
    mock_get.return_value = mock_client
    with (
        patch("app.api.v1.endpoints.mcp_proxy.get_mcp_client", mock_get),
        patch("app.api.v1.endpoints.mcp_proxy.log") as mock_log,
    ):
        yield mock_get, mock_client, mock_log


@pytest.fixture
def client_without_user_id(client: AsyncClient, test_app: FastAPI) -> AsyncClient:
    """Client whose principal dict has no user_id, exercising the 400 path.

    The endpoint (not just the auth dependency) must reject a user dict
    without a user_id.
    """
    original = test_app.dependency_overrides.get(get_current_user)
    test_app.dependency_overrides[get_current_user] = lambda: {"email": "nobody@example.com"}
    yield client
    if original is None:
        test_app.dependency_overrides.pop(get_current_user, None)
    else:
        test_app.dependency_overrides[get_current_user] = original


class TestProxyToolCall:
    """POST /api/v1/mcp/proxy/tool-call"""

    async def test_tool_call_success(self, client: AsyncClient) -> None:
        result = CallToolResult(content=[TextContent(type="text", text="hello")], isError=False)
        with _patched_mcp() as (mock_get, mock_client, mock_log):
            mock_client.call_tool_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={
                    "server_url": SERVER_URL,
                    "tool_name": "test_tool",
                    "arguments": {"key": "val"},
                },
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "content": [{"type": "text", "text": "hello", "annotations": None, "meta": None}],
            "is_error": False,
        }
        mock_get.assert_awaited_once_with(user_id=USER_ID)
        mock_client.call_tool_on_server.assert_awaited_once_with(
            server_url=SERVER_URL,
            tool_name="test_tool",
            arguments={"key": "val"},
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            operation="mcp_proxy_tool_call",
            mcp=McpContext(operation="call_tool", tool_name="test_tool"),
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.set_ns.assert_called_once_with("mcp", success=True)

    async def test_tool_call_is_error_flag_passthrough(self, client: AsyncClient) -> None:
        result = CallToolResult(content=[], isError=True)
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.call_tool_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={"server_url": SERVER_URL, "tool_name": "failing_tool"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"content": [], "is_error": True}
        mock_log.set_ns.assert_called_once_with("mcp", success=False)

    async def test_tool_call_missing_user_id_returns_400(
        self, client_without_user_id: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            resp = await client_without_user_id.post(
                f"{API}/proxy/tool-call",
                json={"server_url": SERVER_URL, "tool_name": "test_tool"},
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}
        mock_get.assert_not_awaited()

    async def test_tool_call_service_error_returns_500(self, client: AsyncClient) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.call_tool_on_server.side_effect = RuntimeError("conn refused")
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={"server_url": SERVER_URL, "tool_name": "test_tool"},
            )

        assert resp.status_code == 500
        assert resp.json() == {"detail": "Tool call failed: conn refused"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} MCP proxy tool call failed",
            user_id=USER_ID,
            tool_name="test_tool",
            error_type="RuntimeError",
            error="conn refused",
        )

    async def test_tool_call_http_exception_propagates_unchanged(
        self, client: AsyncClient
    ) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.call_tool_on_server.side_effect = HTTPException(
                status_code=403, detail="Forbidden"
            )
            resp = await client.post(
                f"{API}/proxy/tool-call",
                json={"server_url": SERVER_URL, "tool_name": "test_tool"},
            )

        assert resp.status_code == 403
        assert resp.json() == {"detail": "Forbidden"}
        mock_log.error.assert_not_called()

    async def test_tool_call_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/proxy/tool-call", json={})
        assert resp.status_code == 422

    async def test_tool_call_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/tool-call",
            json={"server_url": SERVER_URL, "tool_name": "test_tool"},
        )
        assert resp.status_code == 401


class TestProxyResourcesList:
    """POST /api/v1/mcp/proxy/resources/list"""

    async def test_resources_list_success(self, client: AsyncClient) -> None:
        result = ListResourcesResult(
            resources=[
                Resource(uri=AnyUrl("file:///a.txt"), name="a.txt", mimeType="text/plain")
            ],
            nextCursor="cur1",
        )
        with _patched_mcp() as (mock_get, mock_client, mock_log):
            mock_client.list_resources_on_server.return_value = result
            resp = await client.post(f"{API}/proxy/resources/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 200
        resource = resp.json()["resources"][0]
        assert resource["uri"] == "file:///a.txt"
        assert resource["name"] == "a.txt"
        assert resource["mimeType"] == "text/plain"
        assert resource["_meta"] is None
        assert "meta" not in resource
        assert "mime_type" not in resource
        assert resp.json()["next_cursor"] == "cur1"
        mock_get.assert_awaited_once_with(user_id=USER_ID)
        mock_client.list_resources_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor=None
        )
        mock_log.set.assert_any_call(user={"id": USER_ID}, operation="mcp_proxy_resources_list")
        mock_log.set.assert_any_call(outcome="success")
        mock_log.set.assert_any_call(mcp=McpContext(success=True, result_count=1))

    async def test_resources_list_forwards_cursor(self, client: AsyncClient) -> None:
        result = ListResourcesResult(resources=[])
        with _patched_mcp() as (_, mock_client, _):
            mock_client.list_resources_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/resources/list",
                json={"server_url": SERVER_URL, "cursor": "page2"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"resources": [], "next_cursor": None}
        mock_client.list_resources_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor="page2"
        )

    async def test_resources_list_missing_user_id_returns_400(
        self, client_without_user_id: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            resp = await client_without_user_id.post(
                f"{API}/proxy/resources/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}
        mock_get.assert_not_awaited()

    async def test_resources_list_service_error_returns_500(self, client: AsyncClient) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_resources_on_server.side_effect = RuntimeError("boom")
            resp = await client.post(f"{API}/proxy/resources/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 500
        assert resp.json() == {"detail": "resources/list failed: boom"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} MCP proxy resources/list failed",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="boom",
        )

    async def test_resources_list_http_exception_propagates_unchanged(
        self, client: AsyncClient
    ) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_resources_on_server.side_effect = HTTPException(
                status_code=403, detail="Forbidden"
            )
            resp = await client.post(f"{API}/proxy/resources/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 403
        assert resp.json() == {"detail": "Forbidden"}
        mock_log.error.assert_not_called()

    async def test_resources_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/list",
            json={"server_url": SERVER_URL},
        )
        assert resp.status_code == 401


class TestProxyResourceTemplatesList:
    """POST /api/v1/mcp/proxy/resources/templates/list"""

    async def test_templates_list_success(self, client: AsyncClient) -> None:
        result = ListResourceTemplatesResult(
            resourceTemplates=[
                ResourceTemplate(
                    uriTemplate="file:///{path}", name="file", mimeType="text/plain"
                )
            ],
            nextCursor="cur1",
        )
        with _patched_mcp() as (mock_get, mock_client, mock_log):
            mock_client.list_resource_templates_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/resources/templates/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 200
        template = resp.json()["resource_templates"][0]
        assert template["uriTemplate"] == "file:///{path}"
        assert template["name"] == "file"
        assert template["mimeType"] == "text/plain"
        assert template["_meta"] is None
        assert "meta" not in template
        assert "uri_template" not in template
        assert "mime_type" not in template
        assert resp.json()["next_cursor"] == "cur1"
        mock_get.assert_awaited_once_with(user_id=USER_ID)
        mock_client.list_resource_templates_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor=None
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID}, operation="mcp_proxy_resource_templates_list"
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.set.assert_any_call(mcp=McpContext(success=True, result_count=1))

    async def test_templates_list_forwards_cursor(self, client: AsyncClient) -> None:
        result = ListResourceTemplatesResult(resourceTemplates=[])
        with _patched_mcp() as (_, mock_client, _):
            mock_client.list_resource_templates_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/resources/templates/list",
                json={"server_url": SERVER_URL, "cursor": "page2"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"resource_templates": [], "next_cursor": None}
        mock_client.list_resource_templates_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor="page2"
        )

    async def test_templates_list_missing_user_id_returns_400(
        self, client_without_user_id: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            resp = await client_without_user_id.post(
                f"{API}/proxy/resources/templates/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}
        mock_get.assert_not_awaited()

    async def test_templates_list_service_error_returns_500(self, client: AsyncClient) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_resource_templates_on_server.side_effect = RuntimeError("err")
            resp = await client.post(
                f"{API}/proxy/resources/templates/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 500
        assert resp.json() == {"detail": "resources/templates/list failed: err"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} MCP proxy resources/templates/list failed",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="err",
        )

    async def test_templates_list_http_exception_propagates_unchanged(
        self, client: AsyncClient
    ) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_resource_templates_on_server.side_effect = HTTPException(
                status_code=403, detail="Forbidden"
            )
            resp = await client.post(
                f"{API}/proxy/resources/templates/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 403
        assert resp.json() == {"detail": "Forbidden"}
        mock_log.error.assert_not_called()

    async def test_templates_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/templates/list",
            json={"server_url": SERVER_URL},
        )
        assert resp.status_code == 401


class TestProxyResourceRead:
    """POST /api/v1/mcp/proxy/resources/read"""

    async def test_resource_read_success(self, client: AsyncClient) -> None:
        result = ReadResourceResult(
            contents=[TextResourceContents(uri=AnyUrl("file:///a.txt"), text="hello world")]
        )
        with _patched_mcp() as (mock_get, mock_client, mock_log):
            mock_client.read_resource_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/resources/read",
                json={"server_url": SERVER_URL, "uri": "file:///a.txt"},
            )

        assert resp.status_code == 200
        content = resp.json()["contents"][0]
        assert content["uri"] == "file:///a.txt"
        assert content["text"] == "hello world"
        assert content["_meta"] is None
        assert "meta" not in content
        mock_get.assert_awaited_once_with(user_id=USER_ID)
        mock_client.read_resource_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, uri="file:///a.txt"
        )
        mock_log.set.assert_any_call(
            user={"id": USER_ID},
            operation="mcp_proxy_resource_read",
            resource_uri="file:///a.txt",
        )
        mock_log.set.assert_any_call(outcome="success")
        mock_log.set.assert_any_call(mcp=McpContext(success=True, result_count=1))

    async def test_resource_read_missing_user_id_returns_400(
        self, client_without_user_id: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            resp = await client_without_user_id.post(
                f"{API}/proxy/resources/read",
                json={"server_url": SERVER_URL, "uri": "file:///a.txt"},
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}
        mock_get.assert_not_awaited()

    async def test_resource_read_service_error_returns_500(self, client: AsyncClient) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.read_resource_on_server.side_effect = RuntimeError("boom")
            resp = await client.post(
                f"{API}/proxy/resources/read",
                json={"server_url": SERVER_URL, "uri": "file:///a.txt"},
            )

        assert resp.status_code == 500
        assert resp.json() == {"detail": "resources/read failed: boom"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} MCP proxy resources/read failed",
            user_id=USER_ID,
            resource_uri="file:///a.txt",
            error_type="RuntimeError",
            error="boom",
        )

    async def test_resource_read_http_exception_propagates_unchanged(
        self, client: AsyncClient
    ) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.read_resource_on_server.side_effect = HTTPException(
                status_code=403, detail="Forbidden"
            )
            resp = await client.post(
                f"{API}/proxy/resources/read",
                json={"server_url": SERVER_URL, "uri": "file:///a.txt"},
            )

        assert resp.status_code == 403
        assert resp.json() == {"detail": "Forbidden"}
        mock_log.error.assert_not_called()

    async def test_resource_read_validation_error(self, client: AsyncClient) -> None:
        resp = await client.post(f"{API}/proxy/resources/read", json={})
        assert resp.status_code == 422

    async def test_resource_read_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/resources/read",
            json={"server_url": SERVER_URL, "uri": "file:///a.txt"},
        )
        assert resp.status_code == 401


class TestProxyPromptsList:
    """POST /api/v1/mcp/proxy/prompts/list"""

    async def test_prompts_list_success(self, client: AsyncClient) -> None:
        result = ListPromptsResult(prompts=[Prompt(name="greet", description="Say hi")])
        with _patched_mcp() as (mock_get, mock_client, mock_log):
            mock_client.list_prompts_on_server.return_value = result
            resp = await client.post(f"{API}/proxy/prompts/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 200
        prompt = resp.json()["prompts"][0]
        assert prompt["name"] == "greet"
        assert prompt["description"] == "Say hi"
        assert prompt["_meta"] is None
        assert "meta" not in prompt
        mock_get.assert_awaited_once_with(user_id=USER_ID)
        mock_client.list_prompts_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor=None
        )
        mock_log.set.assert_any_call(user={"id": USER_ID}, operation="mcp_proxy_prompts_list")
        mock_log.set.assert_any_call(outcome="success")
        mock_log.set.assert_any_call(mcp=McpContext(success=True, result_count=1))

    async def test_prompts_list_forwards_cursor(self, client: AsyncClient) -> None:
        result = ListPromptsResult(prompts=[], nextCursor="c3")
        with _patched_mcp() as (_, mock_client, _):
            mock_client.list_prompts_on_server.return_value = result
            resp = await client.post(
                f"{API}/proxy/prompts/list",
                json={"server_url": SERVER_URL, "cursor": "c2"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"prompts": [], "next_cursor": "c3"}
        mock_client.list_prompts_on_server.assert_awaited_once_with(
            server_url=SERVER_URL, cursor="c2"
        )

    async def test_prompts_list_missing_user_id_returns_400(
        self, client_without_user_id: AsyncClient
    ) -> None:
        with patch(
            "app.api.v1.endpoints.mcp_proxy.get_mcp_client",
            new_callable=AsyncMock,
        ) as mock_get:
            resp = await client_without_user_id.post(
                f"{API}/proxy/prompts/list", json={"server_url": SERVER_URL}
            )

        assert resp.status_code == 400
        assert resp.json() == {"detail": "User ID not found"}
        mock_get.assert_not_awaited()

    async def test_prompts_list_service_error_returns_500(self, client: AsyncClient) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_prompts_on_server.side_effect = RuntimeError("err")
            resp = await client.post(f"{API}/proxy/prompts/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 500
        assert resp.json() == {"detail": "prompts/list failed: err"}
        mock_log.error.assert_called_once_with(
            f"{LogTag.MCP} MCP proxy prompts/list failed",
            user_id=USER_ID,
            error_type="RuntimeError",
            error="err",
        )

    async def test_prompts_list_http_exception_propagates_unchanged(
        self, client: AsyncClient
    ) -> None:
        with _patched_mcp() as (_, mock_client, mock_log):
            mock_client.list_prompts_on_server.side_effect = HTTPException(
                status_code=403, detail="Forbidden"
            )
            resp = await client.post(f"{API}/proxy/prompts/list", json={"server_url": SERVER_URL})

        assert resp.status_code == 403
        assert resp.json() == {"detail": "Forbidden"}
        mock_log.error.assert_not_called()

    async def test_prompts_list_requires_auth(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            f"{API}/proxy/prompts/list",
            json={"server_url": SERVER_URL},
        )
        assert resp.status_code == 401
