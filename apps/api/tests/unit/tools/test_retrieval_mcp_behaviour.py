"""Exact arguments, ordering and log output of retrieval's activated-MCP handling."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.subagents.integration_resolution import CustomMcpSubagent
from app.agents.tools.core import retrieval
from app.constants.log_tags import LogTag
from app.models.mcp_config import MCPConfig
from app.services.mcp.tool_naming import stamp_tool_metadata
from tests.helpers import captured_wide_event


def _mcp(integration_id: str) -> CustomMcpSubagent:
    return CustomMcpSubagent(
        id=integration_id,
        name=integration_id.title(),
        managed_by="mcp",
        mcp_config=MCPConfig(
            server_url=f"https://{integration_id}.example.com", requires_auth=True
        ),
    )


def _live_tool(name: str, integration_id: str) -> SimpleNamespace:
    tool = SimpleNamespace(name=name, description="", metadata=None)
    stamp_tool_metadata([tool], integration_id, "https://bbb.example.com", "Bbb")
    return tool


@pytest.mark.unit
class TestUserMcpToolsAcrossSeveralActivatedServers:
    async def test_an_unreachable_server_is_logged_and_the_next_one_is_still_listed(self) -> None:
        down, up = _mcp("aaa"), _mcp("bbb")
        client = MagicMock()
        client._tools = {}

        async def _connect(integration_id: str) -> list[SimpleNamespace]:
            if integration_id == "aaa":
                raise ConnectionError("down")
            return [_live_tool("BBB_LIST", "bbb")]

        client.ensure_connected = AsyncMock(side_effect=_connect)
        tool_space = AsyncMock(return_value="mcp.bbb")
        with (
            patch.object(retrieval, "get_mcp_client", new=AsyncMock(return_value=client)),
            patch.object(retrieval, "reserved_tool_names", new=AsyncMock(return_value=set())),
            patch.object(retrieval, "_target_tool_space", new=tool_space),
        ):
            async with captured_wide_event() as event:
                tools = await retrieval._user_mcp_tools("u1", {"aaa": down, "bbb": up})

        assert tools.names == {"BBB_LIST"}
        assert tools.live_by_index_key == {"mcp.bbb": {"BBB_LIST": "BBB_LIST"}}
        tool_space.assert_awaited_once_with(up)
        (warning,) = event["warnings"]
        assert warning == {
            "msg": f"{LogTag.TOOL} Activated MCP integration unreachable; its tools are not listed",
            "integration_id": "aaa",
            "error_type": "ConnectionError",
            "error": "down",
        }


@pytest.mark.unit
class TestActiveIntegrationTargets:
    async def test_an_unresolvable_id_does_not_stop_the_ids_after_it(self) -> None:
        resolved = _mcp("bbb")

        async def _resolve(integration_id: str) -> CustomMcpSubagent | None:
            return resolved if integration_id == "bbb" else None

        with (
            patch.object(retrieval, "get_active", new=AsyncMock(return_value={"bbb", "aaa"})),
            patch.object(retrieval, "get_integration_target", new=AsyncMock(side_effect=_resolve)),
        ):
            assert await retrieval._active_integration_targets("c1") == {"bbb": resolved}


@pytest.mark.unit
class TestTargetToolSpace:
    async def test_a_custom_mcp_namespace_is_derived_from_its_id_and_server_url(self) -> None:
        derive = MagicMock(return_value="mcp.derived")
        get_server_url = AsyncMock(return_value="https://abc.example.com")
        with (
            patch.object(retrieval.IntegrationResolver, "get_server_url", new=get_server_url),
            patch.object(retrieval, "derive_integration_namespace", new=derive),
        ):
            result = await retrieval._target_tool_space(_mcp("abc"))

        assert result == "mcp.derived"
        derive.assert_called_once_with("abc", "https://abc.example.com", is_custom=True)


@pytest.mark.unit
class TestBuildSearchTasksActivatedNamespaces:
    async def test_a_refused_namespace_is_logged_and_the_later_ones_are_still_searched(
        self,
    ) -> None:
        store = MagicMock()
        scope = retrieval._RetrievalScope(
            user_id="u1", tool_space="general", include_subagents=False
        )
        async with captured_wide_event() as event:
            retrieval._build_search_tasks(
                store,
                "q",
                scope,
                {"general", "mcp.zzz"},
                limit=10,
                active_namespaces={"mcp.aaa", "mcp.zzz"},
            )

        searched = [c.args[0] for c in store.asearch.call_args_list]
        assert searched == [("general",), ("mcp.zzz",)]
        (warning,) = event["warnings"]
        assert warning == {
            "msg": f"{LogTag.TOOL} retrieve_tools refused activated namespace not in user_namespaces",
            "namespace": "mcp.aaa",
        }


@pytest.mark.unit
class TestPointerIntegrationId:
    def test_a_legacy_pointer_wrapping_the_static_key_yields_the_bare_id(self) -> None:
        assert retrieval._pointer_integration_id("mcp_integration:subagent:foo (Foo)") == "foo"


@pytest.mark.unit
@pytest.mark.asyncio
class TestActivatedTargetsReachMcpLookup:
    async def test_binding_resolves_this_conversations_targets_for_this_user(self) -> None:
        targets = {"abc": _mcp("abc")}
        resolve = AsyncMock(return_value=targets)
        mcp_tools = AsyncMock(return_value=retrieval._UserMcpTools(set(), {}))
        registry = MagicMock()
        registry.get_category_of_tool.return_value = None
        scope = retrieval._RetrievalScope(
            user_id="u1", tool_space="gmail", include_subagents=False, conversation_id="c1"
        )
        with (
            patch.object(retrieval, "_active_integration_targets", new=resolve),
            patch.object(retrieval, "_user_mcp_tools", new=mcp_tools),
            patch.object(retrieval, "_unconnected_for_tools", new=AsyncMock(return_value={})),
            patch.object(retrieval, "_render_proxied_docs", new=AsyncMock(return_value=[])),
        ):
            await retrieval._bind_exact_tools(scope, registry, set(), ["nope"], None)

        resolve.assert_awaited_once_with("c1")
        mcp_tools.assert_awaited_once_with("u1", targets)

    async def test_discovery_threads_targets_tool_space_and_live_names_into_the_hit_filter(
        self,
    ) -> None:
        target = _mcp("abc")
        targets = {"abc": target}
        live_names = {"mcp.abc": {"search": "abc_search"}}
        mcp_tools = AsyncMock(return_value=retrieval._UserMcpTools({"abc_search"}, live_names))
        process = AsyncMock(return_value=[])
        store = MagicMock()
        store.asearch = AsyncMock(return_value=[])
        registry = MagicMock()
        scope = retrieval._RetrievalScope(
            user_id="u1", tool_space="gmail", include_subagents=False, conversation_id="c1"
        )
        with (
            patch.object(
                retrieval, "_get_user_context", new=AsyncMock(return_value=({"gmail"}, {}))
            ),
            patch.object(
                retrieval, "_active_integration_targets", new=AsyncMock(return_value=targets)
            ),
            patch.object(retrieval, "_target_tool_space", new=AsyncMock(return_value="mcp.abc")),
            patch.object(retrieval, "_user_mcp_tools", new=mcp_tools),
            patch.object(retrieval, "_process_search_results", new=process),
        ):
            await retrieval._discover_tools(store, "q", scope, registry, {"global_tool"}, 5)

        mcp_tools.assert_awaited_once_with("u1", targets)
        (_, available, _, hit_filter) = process.await_args.args
        assert available == {"global_tool", "abc_search"}
        assert hit_filter == retrieval._HitFilter(
            include_subagents=False,
            connected_integration_ids=set(),
            tool_space="gmail",
            active_namespaces={"mcp.abc"},
            mcp_live_names=live_names,
        )
