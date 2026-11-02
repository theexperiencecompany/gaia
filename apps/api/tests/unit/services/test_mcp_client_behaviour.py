"""Behaviour tests for MCPClient's connect, disconnect and name-resolution lifecycle."""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import BaseTool
import pytest

from app.constants.log_tags import LogTag
from app.constants.mcp import MCP_UNLISTED_CONNECT_MAX
from app.helpers.namespace_utils import derive_integration_namespace
from app.services.mcp import mcp_client
from app.services.mcp.mcp_client import MCPClient, get_mcp_client
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

_MODULE = "app.services.mcp.mcp_client"
USER_ID = "507f1f77bcf86cd799439011"
INTEGRATION_ID = "int-1"
SERVER_URL = "https://mcp.example.com/api"


def _closing_spawn(
    result: MagicMock | None, spawned: list[str]
) -> Callable[[Awaitable[None], str], MagicMock | None]:
    def spawn(coro: Awaitable[None], label: str) -> MagicMock | None:
        spawned.append(label)
        coro.close()  # type: ignore[attr-defined]
        return result

    return spawn


def _tool(name: str, metadata: dict[str, Any] | None = None) -> MagicMock:
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    tool.description = f"{name} docs"
    tool.metadata = metadata if metadata is not None else {}
    return tool


def _close_task(operation: str, coro: Awaitable[None], **context: Any) -> MagicMock:
    coro.close()  # type: ignore[attr-defined]
    return MagicMock()


class TestDoConnect:
    async def test_server_url_is_stamped_on_tools_that_carry_an_ui(self) -> None:
        resolved = MagicMock()
        resolved.name = "Acme"
        resolved.source = "platform"
        resolved.mcp_config.server_url = SERVER_URL
        resolved.mcp_config.requires_auth = True
        ui_tool = _tool("show", {"mcp_ui": {"resource": "ui://x"}})
        client = MCPClient(USER_ID)

        with (
            patch(f"{_MODULE}.IntegrationResolver.resolve", AsyncMock(return_value=resolved)),
            patch.object(client, "_open_session", AsyncMock(return_value=MagicMock())),
            patch.object(client, "_convert_tools_safe", AsyncMock(return_value=[ui_tool])),
            patch(f"{_MODULE}.reserved_tool_names", AsyncMock(return_value=set())),
            patch(f"{_MODULE}.connected_tool_records", AsyncMock(return_value=[])),
            patch(f"{_MODULE}.wrap_tools_with_null_filter", side_effect=lambda tools, **_: tools),
            patch(f"{_MODULE}.update_user_integration_status", AsyncMock()),
            patch(f"{_MODULE}.spawn_logged_task", side_effect=_close_task),
        ):
            await client._do_connect(INTEGRATION_ID)

        assert ui_tool.metadata["mcp_server_url"] == SERVER_URL


class TestPersistAndIndexTools:
    async def test_post_connect_failures_name_the_integration(self) -> None:
        client = MCPClient(USER_ID)
        resolved = MagicMock()
        resolved.source = "platform"

        with (
            patch(f"{_MODULE}.store_mcp_tools", AsyncMock(side_effect=RuntimeError("mongo down"))),
            patch.object(client, "_index_platform_mcp_tools", AsyncMock()),
            patch(f"{_MODULE}.invalidate_user_integration_caches", AsyncMock()),
        ):
            async with captured_wide_event() as event:
                await client._persist_and_index_tools(resolved, MagicMock(), INTEGRATION_ID, [])

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} post-connect task failed",
                "integration_id": INTEGRATION_ID,
                "label": "store_tools_mongo",
                "error": "mongo down",
                "error_type": "RuntimeError",
            }
        ]


class TestConnectAfterOauth:
    async def test_connect_runs_in_the_background_under_a_labelled_task(self) -> None:
        client = MCPClient(USER_ID)
        spawned: list[str] = []

        with (
            patch(f"{_MODULE}._spawn_background", _closing_spawn(MagicMock(), spawned)),
            patch.object(client, "connect", AsyncMock()) as connect,
        ):
            await client.connect_after_oauth(INTEGRATION_ID)

        assert spawned == ["oauth_bg_connect_int-1"]
        connect.assert_not_awaited()

    async def test_connects_inline_when_there_is_no_event_loop_to_spawn_on(self) -> None:
        client = MCPClient(USER_ID)

        with (
            patch(f"{_MODULE}._spawn_background", _closing_spawn(None, [])),
            patch.object(client, "connect", AsyncMock()) as connect,
        ):
            await client.connect_after_oauth(INTEGRATION_ID)

        connect.assert_awaited_once_with(INTEGRATION_ID)

    @pytest.mark.parametrize(
        "message", ["401 Unauthorized", "Authentication failed", "invalid_grant"]
    )
    async def test_dead_credentials_reset_the_integration(self, message: str) -> None:
        client = MCPClient(USER_ID)

        with (
            patch(f"{_MODULE}._spawn_background", _closing_spawn(None, [])),
            patch.object(client, "connect", AsyncMock(side_effect=Exception(message))),
            patch.object(client, "_reset_to_disconnected", AsyncMock()) as reset,
        ):
            await client.connect_after_oauth(INTEGRATION_ID)

        reset.assert_awaited_once_with(INTEGRATION_ID)

    async def test_a_forbidden_before_any_refresh_is_not_terminal(self) -> None:
        client = MCPClient(USER_ID)

        with (
            patch(f"{_MODULE}._spawn_background", _closing_spawn(None, [])),
            patch.object(client, "connect", AsyncMock(side_effect=Exception("403 Forbidden"))),
            patch.object(client, "_reset_to_disconnected", AsyncMock()) as reset,
        ):
            await client.connect_after_oauth(INTEGRATION_ID)

        reset.assert_not_awaited()


def _client_with_session(close: AsyncMock) -> MCPClient:
    client = MCPClient(USER_ID)
    session_client = MagicMock()
    session_client.close_all_sessions = close
    client._clients[INTEGRATION_ID] = session_client
    return client


class TestDropLocal:
    async def test_closing_the_session_is_bounded_to_two_seconds(self) -> None:
        client = _client_with_session(AsyncMock())
        timeouts: list[float | None] = []
        real_wait_for = asyncio.wait_for

        async def recording(awaitable: Awaitable[None], timeout: float | None) -> None:
            timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout)

        with patch.object(mcp_client.asyncio, "wait_for", recording):
            await client.drop_local(INTEGRATION_ID)

        assert timeouts == [2.0]
        assert INTEGRATION_ID not in client._clients

    async def test_a_close_timeout_warns_and_still_clears_local_state(self) -> None:
        client = _client_with_session(AsyncMock())

        async def timing_out(awaitable: Any, timeout: float | None) -> None:
            awaitable.close()
            raise TimeoutError

        with patch.object(mcp_client.asyncio, "wait_for", timing_out):
            async with captured_wide_event() as event:
                await client.drop_local(INTEGRATION_ID)

        assert event["warnings"] == [
            {
                "msg": (
                    f"{LogTag.MCP} close_all_sessions timed out; proceeding with local cleanup. "
                    "Upstream session may linger until server-side timeout."
                ),
                "integration_id": INTEGRATION_ID,
                "error_type": "TimeoutError",
                "error": "",
            }
        ]
        assert INTEGRATION_ID not in client._clients

    async def test_a_close_error_warns_with_the_error_and_still_clears_local_state(self) -> None:
        client = _client_with_session(AsyncMock(side_effect=RuntimeError("socket gone")))

        async with captured_wide_event() as event:
            await client.drop_local(INTEGRATION_ID)

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Error closing MCP session",
                "error": "socket gone",
                "error_type": "RuntimeError",
                "integration_id": INTEGRATION_ID,
            }
        ]
        assert INTEGRATION_ID not in client._clients


@contextmanager
def _disconnect_seams(
    client: MCPClient, resolved: MagicMock | None, spawn_result: MagicMock | None
) -> Iterator[tuple[list[str], AsyncMock, AsyncMock, AsyncMock, AsyncMock]]:
    spawned: list[str] = []
    with (
        patch(f"{_MODULE}._spawn_background", _closing_spawn(spawn_result, spawned)),
        patch(f"{_MODULE}.revoke_integration_tokens", AsyncMock()) as revoke,
        patch(f"{_MODULE}.IntegrationResolver.resolve", AsyncMock(return_value=resolved)) as res,
        patch(f"{_MODULE}.delete_cache", AsyncMock()) as delete,
        patch.object(client, "_reset_to_disconnected", AsyncMock()) as reset,
    ):
        yield spawned, revoke, res, delete, reset


def _resolved(source: str, server_url: str) -> MagicMock:
    resolved = MagicMock()
    resolved.source = source
    resolved.mcp_config.server_url = server_url
    return resolved


class TestDisconnect:
    async def test_revoke_is_spawned_in_the_background_for_this_users_tokens(self) -> None:
        client = MCPClient(USER_ID)

        with _disconnect_seams(client, None, MagicMock()) as (spawned, revoke, _, _, _):
            await client.disconnect(INTEGRATION_ID)

        assert spawned == ["revoke_int-1"]
        revoke.assert_called_once_with(client.token_store, INTEGRATION_ID)
        revoke.assert_not_awaited()

    async def test_revoke_is_awaited_inline_when_nothing_can_be_spawned(self) -> None:
        client = MCPClient(USER_ID)

        with _disconnect_seams(client, None, None) as (_, revoke, _, _, _):
            await client.disconnect(INTEGRATION_ID)

        revoke.assert_awaited_once_with(client.token_store, INTEGRATION_ID)

    async def test_custom_integration_drops_its_url_derived_chroma_marker(self) -> None:
        client = MCPClient(USER_ID)

        with _disconnect_seams(client, _resolved("custom", SERVER_URL), MagicMock()) as (
            _,
            _,
            resolve,
            delete,
            reset,
        ):
            await client.disconnect(INTEGRATION_ID)

        namespace = derive_integration_namespace(INTEGRATION_ID, SERVER_URL, is_custom=True)
        assert namespace != INTEGRATION_ID
        resolve.assert_awaited_once_with(INTEGRATION_ID)
        delete.assert_awaited_once_with(f"chroma:indexed:{namespace}")
        reset.assert_awaited_once_with(INTEGRATION_ID)

    async def test_custom_integration_without_a_url_is_keyed_by_its_id(self) -> None:
        client = MCPClient(USER_ID)

        with _disconnect_seams(client, _resolved("custom", ""), MagicMock()) as (
            _,
            _,
            _,
            delete,
            _,
        ):
            await client.disconnect(INTEGRATION_ID)

        delete.assert_awaited_once_with("chroma:indexed:int-1")

    async def test_platform_integration_is_keyed_by_its_id(self) -> None:
        client = MCPClient(USER_ID)

        with _disconnect_seams(client, _resolved("platform", SERVER_URL), MagicMock()) as (
            _,
            _,
            _,
            delete,
            _,
        ):
            await client.disconnect(INTEGRATION_ID)

        delete.assert_awaited_once_with("chroma:indexed:int-1")

    @pytest.mark.parametrize("resolved", [None, MagicMock(mcp_config=None)])
    async def test_an_integration_without_mcp_config_has_no_chroma_marker_to_drop(
        self, resolved: MagicMock | None
    ) -> None:
        client = MCPClient(USER_ID)

        async with captured_wide_event() as event:
            with _disconnect_seams(client, resolved, MagicMock()) as (_, _, _, delete, _):
                await client.disconnect(INTEGRATION_ID)

        delete.assert_not_awaited()
        assert event.get("warnings", []) == []

    async def test_a_chroma_marker_failure_warns_and_the_teardown_still_runs(self) -> None:
        client = MCPClient(USER_ID)

        async with captured_wide_event() as event:
            with _disconnect_seams(client, _resolved("platform", SERVER_URL), MagicMock()) as (
                _,
                _,
                _,
                delete,
                reset,
            ):
                delete.side_effect = RuntimeError("redis down")
                await client.disconnect(INTEGRATION_ID)

        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} Failed to invalidate ChromaDB cache",
                "error": "redis down",
                "error_type": "RuntimeError",
                "integration_id": INTEGRATION_ID,
            }
        ]
        reset.assert_awaited_once_with(INTEGRATION_ID)


def _unlisted_client(
    connected: list[str], warm: list[str]
) -> tuple[MCPClient, AsyncMock, AsyncMock]:
    client = MCPClient(USER_ID)
    for integration_id in warm:
        client._tools[integration_id] = [_tool("t")]
    connect = AsyncMock()
    get_connected = AsyncMock(return_value=connected)
    client.connect = connect  # type: ignore[method-assign]
    return client, connect, get_connected


class TestConnectUnlisted:
    @contextmanager
    def _seams(self, get_connected: AsyncMock) -> Iterator[None]:
        with (
            patch(f"{_MODULE}.get_connected_integration_ids", get_connected),
            patch(
                f"{_MODULE}.IntegrationResolver.resolve",
                AsyncMock(side_effect=lambda _: MagicMock()),
            ),
        ):
            yield

    async def test_only_the_integrations_no_source_covers_are_connected(self) -> None:
        client, connect, get_connected = _unlisted_client(
            ["listed", "warm", "fresh"], warm=["warm"]
        )

        with self._seams(get_connected):
            await client._connect_unlisted(listed=["listed"])

        get_connected.assert_awaited_once_with(USER_ID)
        connect.assert_awaited_once_with("fresh")

    async def test_exactly_the_cap_connects_all_and_does_not_warn(self) -> None:
        ids = [f"mcp-{n}" for n in range(MCP_UNLISTED_CONNECT_MAX)]
        client, connect, get_connected = _unlisted_client(ids, warm=[])

        with self._seams(get_connected):
            async with captured_wide_event() as event:
                await client._connect_unlisted(listed=[])

        assert [call.args[0] for call in connect.await_args_list] == ids
        assert event.get("warnings", []) == []

    async def test_beyond_the_cap_connects_the_first_ids_and_warns_with_the_skipped_count(
        self,
    ) -> None:
        ids = [f"mcp-{n}" for n in range(MCP_UNLISTED_CONNECT_MAX + 1)]
        client, connect, get_connected = _unlisted_client(ids, warm=[])

        with self._seams(get_connected):
            async with captured_wide_event() as event:
                await client._connect_unlisted(listed=[])

        assert [call.args[0] for call in connect.await_args_list] == ids[:-1]
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.MCP} More unlisted MCPs than one tool lookup connects",
                "skipped": 1,
            }
        ]


class TestSessionFor:
    def test_asks_the_clients_session_for_that_integration(self) -> None:
        client = MCPClient(USER_ID)
        session_client = MagicMock()
        client._clients[INTEGRATION_ID] = session_client

        session = client.session_for(INTEGRATION_ID)

        assert session is session_client.get_session.return_value
        session_client.get_session.assert_called_once_with(INTEGRATION_ID)

    def test_none_without_a_client(self) -> None:
        assert MCPClient(USER_ID).session_for(INTEGRATION_ID) is None


class TestGetMcpClient:
    async def test_returns_the_pools_client_for_that_user(self) -> None:
        pool = MagicMock()
        pool.get = AsyncMock(return_value="the-users-client")

        with patch(f"{_MODULE}.get_mcp_client_pool", AsyncMock(return_value=pool)):
            result = await get_mcp_client(USER_ID)

        assert result == "the-users-client"
        pool.get.assert_awaited_once_with(USER_ID)
