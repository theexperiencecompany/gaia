"""Behaviour of MCP server-URL routing: matching, session lookup, and UI resource reads.

Only the I/O seams are replaced (integration resolver, user-integration repository,
the MCP client's sessions); the routing logic itself runs for real.
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mcp.types import (
    BlobResourceContents,
    CallToolResult,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
)
from pydantic import AnyUrl
import pytest

from app.constants.log_tags import LogTag
from app.services.mcp import server_routing
from app.services.mcp.server_routing import (
    _normalize_server_url,
    call_tool_on_server,
    list_prompts_on_server,
    list_resource_templates_on_server,
    list_resources_on_server,
    read_resource_on_server,
    read_ui_resource_details,
)
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

MODULE = "app.services.mcp.server_routing"
SERVER_URL = "https://mcp.example.com/api"
USER_ID = "user-1"


def _resolved(server_url: str) -> SimpleNamespace:
    return SimpleNamespace(mcp_config=SimpleNamespace(server_url=server_url))


class FakeClient:
    """A real MCPSessionHost implementation recording what routing asks of it."""

    def __init__(
        self,
        sessions: dict[str, Any] | None = None,
        active: list[str] | None = None,
        connected_db: bool = True,
    ) -> None:
        self.user_id = USER_ID
        self._sessions = sessions or {}
        self._active = active if active is not None else []
        self._connected_db = connected_db
        self.ensure_connected_calls: list[str] = []

    def active_integration_ids(self) -> list[str]:
        return self._active

    def session_for(self, integration_id: str) -> Any:
        return self._sessions.get(integration_id)

    async def is_connected_db(self, integration_id: str) -> bool:
        return self._connected_db

    async def ensure_connected(self, integration_id: str) -> list[Any]:
        self.ensure_connected_calls.append(integration_id)
        return []


def _resolver(mapping: dict[str, Any]) -> AsyncMock:
    async def resolve(integration_id: str) -> Any:
        value = mapping[integration_id]
        if isinstance(value, BaseException):
            raise value
        return value

    return AsyncMock(side_effect=resolve)


def _repo(integration_ids: list[str]) -> AsyncMock:
    docs = [SimpleNamespace(integration_id=i, status="connected") for i in integration_ids]
    return AsyncMock(return_value=docs)


class TestNormalizeServerUrl:
    def test_strips_repeated_trailing_slashes_but_not_other_characters(self):
        assert _normalize_server_url("https://H.com/mcpXX//") == "https://h.com/mcpXX"

    def test_unparseable_url_falls_back_to_trimmed_url_without_trailing_slashes(self):
        assert _normalize_server_url("  http://[badX//  ") == "http://[badX"

    def test_blank_url_is_empty(self):
        assert _normalize_server_url("   ") == ""


class TestIntegrationMatching:
    async def test_repository_failure_is_logged_and_no_match_returned(self):
        client = FakeClient()
        repo = AsyncMock(side_effect=ValueError("db down"))

        with patch(f"{MODULE}.user_integration_repository.list_for_user", repo):
            async with captured_wide_event() as event:
                with pytest.raises(ValueError, match="No connected MCP integration found"):
                    await call_tool_on_server(client, SERVER_URL, "t", {})

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Failed to load user integrations while matching server_url",
                "server_url": SERVER_URL,
                "error": "db down",
                "error_type": "ValueError",
            }
        ]
        repo.assert_awaited_once_with(USER_ID)

    async def test_resolver_is_called_with_each_candidate_id(self):
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=CallToolResult(content=[], isError=False))
        client = FakeClient(sessions={"b": session})
        resolver = _resolver({"a": _resolved("https://other.example"), "b": _resolved(SERVER_URL)})

        with (
            patch(f"{MODULE}.user_integration_repository.list_for_user", _repo(["a", "b"])),
            patch(f"{MODULE}.IntegrationResolver.resolve", resolver),
        ):
            await call_tool_on_server(client, SERVER_URL, "t", {})

        assert sorted(c.args for c in resolver.await_args_list) == [("a",), ("b",)]
        assert client.ensure_connected_calls == ["b"]

    async def test_failed_resolution_of_one_candidate_does_not_hide_a_later_match(self):
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=CallToolResult(content=[], isError=False))
        client = FakeClient(sessions={"b": session})
        resolver = _resolver({"a": RuntimeError("boom"), "b": _resolved(SERVER_URL + "/")})

        with (
            patch(f"{MODULE}.user_integration_repository.list_for_user", _repo(["a", "b"])),
            patch(f"{MODULE}.IntegrationResolver.resolve", resolver),
        ):
            await call_tool_on_server(client, SERVER_URL, "t", {})

        assert client.ensure_connected_calls == ["b"]


def _route_to(client_sessions: dict[str, Any], integration_id: str = "int-1") -> Any:
    """Patch the persisted-integration lookup so SERVER_URL routes to integration_id."""
    resolver = _resolver({integration_id: _resolved(SERVER_URL)})
    return (
        patch(f"{MODULE}.user_integration_repository.list_for_user", _repo([integration_id])),
        patch(f"{MODULE}.IntegrationResolver.resolve", resolver),
    )


class TestCallToolOnServer:
    async def test_calls_tool_and_records_wide_event_context(self):
        result = CallToolResult(content=[TextContent(type="text", text="x")], isError=False)
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=result)
        client = FakeClient(sessions={"int-1": session})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                got = await call_tool_on_server(client, SERVER_URL, "do_it", {"a": 1})

        assert got is result
        session.call_tool.assert_awaited_once_with(name="do_it", arguments={"a": 1})
        assert client.ensure_connected_calls == ["int-1"]
        assert event["mcp"]["operation"] == "call_tool"
        assert event["mcp"]["server_id"] == "int-1"
        assert event["mcp"]["tool_name"] == "do_it"
        assert event["mcp"]["success"] is True

    async def test_missing_session_names_the_integration(self):
        client = FakeClient(sessions={})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            with pytest.raises(ValueError) as exc:
                await call_tool_on_server(client, SERVER_URL, "t", {})

        assert str(exc.value) == "MCP integration int-1 is not connected in memory"

    async def test_unmatched_url_names_the_url(self):
        client = FakeClient()
        with patch(f"{MODULE}.user_integration_repository.list_for_user", _repo([])):
            with pytest.raises(ValueError) as exc:
                await call_tool_on_server(client, SERVER_URL, "t", {})

        assert str(exc.value) == f"No connected MCP integration found for server_url: {SERVER_URL}"

    async def test_tool_exception_is_recorded_as_failure_and_reraised(self):
        session = MagicMock()
        session.call_tool = AsyncMock(side_effect=RuntimeError("bad"))
        client = FakeClient(sessions={"int-1": session})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                with pytest.raises(RuntimeError, match="bad"):
                    await call_tool_on_server(client, SERVER_URL, "t", {})

        assert event["mcp"]["success"] is False
        assert isinstance(event["mcp"]["latency_ms"], float)

    async def test_error_result_is_recorded_as_unsuccessful(self):
        session = MagicMock()
        session.call_tool = AsyncMock(return_value=CallToolResult(content=[], isError=True))
        client = FakeClient(sessions={"int-1": session})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                await call_tool_on_server(client, SERVER_URL, "t", {})

        assert event["mcp"]["success"] is False


def _client_session_host(client_session: Any) -> FakeClient:
    session = SimpleNamespace(connector=SimpleNamespace(client_session=client_session))
    return FakeClient(sessions={"int-1": session})


class TestSessionBackedOperations:
    async def test_list_resources_forwards_cursor_and_returns_result(self):
        cs = MagicMock()
        expected = ListResourcesResult(resources=[])
        cs.list_resources = AsyncMock(return_value=expected)
        client = _client_session_host(cs)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await list_resources_on_server(client, SERVER_URL, "cur")

        assert got is expected
        cs.list_resources.assert_awaited_once_with(cursor="cur")
        assert client.ensure_connected_calls == ["int-1"]

    async def test_list_resource_templates_forwards_cursor(self):
        cs = MagicMock()
        expected = ListResourceTemplatesResult(resourceTemplates=[])
        cs.list_resource_templates = AsyncMock(return_value=expected)
        client = _client_session_host(cs)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await list_resource_templates_on_server(client, SERVER_URL, "cur")

        assert got is expected
        cs.list_resource_templates.assert_awaited_once_with(cursor="cur")

    async def test_read_resource_passes_a_parsed_url(self):
        cs = MagicMock()
        expected = ReadResourceResult(contents=[])
        cs.read_resource = AsyncMock(return_value=expected)
        client = _client_session_host(cs)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await read_resource_on_server(client, SERVER_URL, "ui://app/index.html")

        assert got is expected
        cs.read_resource.assert_awaited_once_with(AnyUrl("ui://app/index.html"))

    async def test_list_prompts_forwards_cursor(self):
        cs = MagicMock()
        expected = ListPromptsResult(prompts=[])
        cs.list_prompts = AsyncMock(return_value=expected)
        client = _client_session_host(cs)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await list_prompts_on_server(client, SERVER_URL, "cur")

        assert got is expected
        cs.list_prompts.assert_awaited_once_with(cursor="cur")

    async def test_unmatched_url_is_reported_with_the_url(self):
        client = FakeClient()
        with patch(f"{MODULE}.user_integration_repository.list_for_user", _repo([])):
            with pytest.raises(ValueError) as exc:
                await list_prompts_on_server(client, SERVER_URL)

        assert str(exc.value) == f"No connected MCP integration found for server_url: {SERVER_URL}"

    async def test_missing_in_memory_session_names_the_integration(self):
        client = FakeClient(sessions={})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            with pytest.raises(ValueError) as exc:
                await list_prompts_on_server(client, SERVER_URL)

        assert str(exc.value) == "MCP integration int-1 is not connected in memory"

    async def test_session_without_client_session_names_the_integration(self):
        client = _client_session_host(None)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            with pytest.raises(ValueError) as exc:
                await list_prompts_on_server(client, SERVER_URL)

        assert str(exc.value) == "MCP integration int-1 has no active session"


def _ui_client(read_resource: AsyncMock) -> FakeClient:
    session = MagicMock()
    session.read_resource = read_resource
    return FakeClient(sessions={"int-1": session})


def _result(*contents: Any) -> SimpleNamespace:
    return SimpleNamespace(contents=list(contents))


class TestReadUiResourceDetails:
    async def test_unmatched_url_returns_none_and_warns(self):
        client = FakeClient()
        with patch(f"{MODULE}.user_integration_repository.list_for_user", _repo([])):
            async with captured_wide_event() as event:
                got = await read_ui_resource_details(client, SERVER_URL, "ui://x")

        assert got is None
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} No active MCP session found for server_url",
                "server_url": SERVER_URL,
            }
        ]

    async def test_missing_session_returns_none_and_warns(self):
        client = FakeClient(sessions={})
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                got = await read_ui_resource_details(client, SERVER_URL, "ui://x")

        assert got is None
        assert client.ensure_connected_calls == ["int-1"]
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} No active MCP client found for server_url",
                "server_url": SERVER_URL,
            }
        ]

    async def test_reads_resource_with_ten_second_timeout(self):
        read = AsyncMock(return_value=_result(SimpleNamespace(text="<p>hi</p>")))
        client = _ui_client(read)
        repo_patch, resolve_patch = _route_to({})
        timeouts: list[float | None] = []
        real_wait_for = asyncio.wait_for

        async def recording_wait_for(awaitable: Any, timeout: float | None) -> Any:
            timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout)

        with (
            repo_patch,
            resolve_patch,
            patch.object(server_routing.asyncio, "wait_for", recording_wait_for),
        ):
            got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got == {"html": "<p>hi</p>", "csp": None, "permissions": None}
        read.assert_awaited_once_with("ui://app")
        assert timeouts == [10.0]

    async def test_timeout_returns_none_and_warns(self):
        read = AsyncMock(return_value=_result())
        client = _ui_client(read)
        repo_patch, resolve_patch = _route_to({})

        async def timing_out(awaitable: Any, timeout: float | None) -> Any:
            awaitable.close()
            raise TimeoutError

        with (
            repo_patch,
            resolve_patch,
            patch.object(server_routing.asyncio, "wait_for", timing_out),
        ):
            async with captured_wide_event() as event:
                got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got is None
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Timeout reading UI resource from (10s)",
                "resource_uri": "ui://app",
                "server_url": SERVER_URL,
                "error_type": "TimeoutError",
                "error": "",
            }
        ]

    async def test_read_failure_returns_none_and_warns_with_error_details(self):
        read = AsyncMock(side_effect=RuntimeError("nope"))
        client = _ui_client(read)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got is None
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Failed to read UI resource from",
                "resource_uri": "ui://app",
                "server_url": SERVER_URL,
                "error": "nope",
                "error_type": "RuntimeError",
            }
        ]

    async def test_content_without_text_is_skipped_without_a_warning(self):
        blob = BlobResourceContents(uri=AnyUrl("ui://a"), blob="AAAA")
        read = AsyncMock(return_value=_result(SimpleNamespace(), blob))
        client = _ui_client(read)
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            async with captured_wide_event() as event:
                got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got is None
        assert event.get("warnings", []) == []

    async def test_ui_hints_are_read_from_underscore_meta(self):
        content = SimpleNamespace(
            text="<b>x</b>", _meta={"ui": {"csp": {"a": 1}, "permissions": ["cam"]}}
        )
        client = _ui_client(AsyncMock(return_value=_result(content)))
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got == {"html": "<b>x</b>", "csp": {"a": 1}, "permissions": ["cam"]}

    async def test_ui_hints_fall_back_to_meta_attribute(self):
        content = SimpleNamespace(text="<b>x</b>", meta={"ui": {"csp": {"b": 2}}})
        client = _ui_client(AsyncMock(return_value=_result(content)))
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got == {"html": "<b>x</b>", "csp": {"b": 2}, "permissions": None}

    async def test_content_with_no_meta_at_all_yields_html_only(self):
        client = _ui_client(AsyncMock(return_value=_result(SimpleNamespace(text="<i>y</i>"))))
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got == {"html": "<i>y</i>", "csp": None, "permissions": None}

    async def test_real_text_resource_contents_carry_their_ui_meta(self):
        content = TextResourceContents(
            uri=AnyUrl("ui://app"),
            text="<u>z</u>",
            _meta={"ui": {"csp": {"c": 3}}},
        )
        client = _ui_client(AsyncMock(return_value=_result(content)))
        repo_patch, resolve_patch = _route_to({})

        with repo_patch, resolve_patch:
            got = await read_ui_resource_details(client, SERVER_URL, "ui://app")

        assert got == {"html": "<u>z</u>", "csp": {"c": 3}, "permissions": None}
