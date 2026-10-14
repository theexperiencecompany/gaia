"""resolve_tool — the three-source resolution order and its miss behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import StructuredTool
import pytest

from app.agents.tools.core.registry import CategoryOptions, CategoryRisk, ToolRegistry
from app.agents.tools.execute import resolver
from app.agents.tools.execute.resolver import ResolvedTool
from tests.helpers import captured_wide_event

MODULE = "app.agents.tools.execute.resolver"


def _registry_with(
    names_to_tools: dict[str, MagicMock], require_integration: bool = True
) -> MagicMock:
    registry = MagicMock()
    registry.get_tool_names.return_value = list(names_to_tools)

    def _meta(name: str) -> MagicMock | None:
        tool = names_to_tools.get(name)
        if tool is None:
            return None
        meta = MagicMock()
        meta.name = name
        meta.tool = tool
        return meta

    registry.get_tool_meta.side_effect = _meta
    category = MagicMock()
    category.require_integration = require_integration
    registry.get_category.return_value = category
    return registry


@pytest.fixture(autouse=True)
def _fresh_cache():
    resolver._materialized_composio_tools.clear()
    resolver._unknown_composio_slugs.clear()
    yield
    resolver._materialized_composio_tools.clear()
    resolver._unknown_composio_slugs.clear()


@pytest.mark.unit
class TestResolveTool:
    async def test_registry_hit_wins(self) -> None:
        tool = MagicMock()
        with (
            patch(
                f"{MODULE}.get_tool_registry",
                new=AsyncMock(return_value=_registry_with({"GMAIL_SEND_EMAIL": tool})),
            ),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock()) as mcp,
            patch(f"{MODULE}.get_composio_service") as composio,
        ):
            resolved = await resolver.resolve_tool("u1", "GMAIL_SEND_EMAIL")
        assert resolved == ResolvedTool("GMAIL_SEND_EMAIL", tool, is_integration=True)
        mcp.assert_not_awaited()
        composio.assert_not_called()

    async def test_alias_resolves_to_canonical_registry_name(self) -> None:
        tool = MagicMock()
        with patch(
            f"{MODULE}.get_tool_registry",
            new=AsyncMock(return_value=_registry_with({"GMAIL_SEND_EMAIL": tool})),
        ):
            resolved = await resolver.resolve_tool("u1", "GMAIL-SEND-EMAIL")
        assert resolved == ResolvedTool("GMAIL_SEND_EMAIL", tool, is_integration=True)

    async def test_mcp_fallback_when_registry_misses(self) -> None:
        mcp_tool = MagicMock()
        mcp_tool.name = "NOTION_MCP_SEARCH"
        client = MagicMock()
        client.find_integration.return_value = "notion-mcp"
        # get_tools is async on the real MCPClient — a sync mock here hid a
        # missing await that mypy caught; keep the mock faithful.
        client.get_tools = AsyncMock(return_value=[mcp_tool])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
        ):
            resolved = await resolver.resolve_tool("u1", "NOTION_MCP_SEARCH")
        # MCP shapes are integration-scoped: a private server's observed shapes
        # must never land in (or be read from) the global scope.
        assert resolved == ResolvedTool(
            "NOTION_MCP_SEARCH", mcp_tool, is_integration=True, shape_scope="mcp:notion-mcp"
        )

    async def test_composio_materialization_for_catalog_slug_and_cached(self) -> None:
        catalog_tool = MagicMock()
        catalog_tool.name = "ASANA_CREATE_TASK"
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[catalog_tool])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            first = await resolver.resolve_tool("u1", "ASANA_CREATE_TASK")
            second = await resolver.resolve_tool("u1", "ASANA_CREATE_TASK")
        assert first == ResolvedTool("ASANA_CREATE_TASK", catalog_tool, is_integration=True)
        assert second == ResolvedTool("ASANA_CREATE_TASK", catalog_tool, is_integration=True)
        service.get_tools_by_name.assert_awaited_once()

    async def test_a_catalog_miss_is_remembered_instead_of_re_asked(self) -> None:
        """Resolution sits on the tool-call critical path — the HIL gate resolves a name twice before the call may run, plus once per sibling, and the approvals node replays."""
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            first = await resolver.resolve_tool("u1", "GMIAL_SNED_EMAIL")
            second = await resolver.resolve_tool("u1", "GMIAL_SNED_EMAIL")
        assert first is None
        assert second is None
        service.get_tools_by_name.assert_awaited_once()

    async def test_a_hung_catalog_lookup_gives_up_instead_of_stalling_the_turn(self) -> None:
        """A degraded Composio must fail this one resolution, not hold the gate — and therefore the whole turn — open for as long as it takes to answer."""
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()

        async def never_returns(_names: list[str]) -> list[MagicMock]:
            await asyncio.sleep(5)
            raise AssertionError("the lookup was left unbounded")

        service.get_tools_by_name = never_returns
        with (
            patch(f"{MODULE}.COMPOSIO_CATALOG_LOOKUP_TIMEOUT_SECONDS", 0.01),
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
            pytest.raises(TimeoutError),
        ):
            await resolver.resolve_tool("u1", "ASANA_CREATE_TASK")

    async def test_non_catalog_shaped_unknown_never_hits_composio(self) -> None:
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            resolved = await resolver.resolve_tool("u1", "not_a_catalog_slug")
        assert resolved is None
        service.get_tools_by_name.assert_not_awaited()

    async def test_mcp_outage_degrades_to_other_sources(self) -> None:
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(side_effect=RuntimeError("down"))),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            resolved = await resolver.resolve_tool("u1", "GMAIL_SEND_EMAIL")
        assert resolved is None
        service.get_tools_by_name.assert_awaited_once()


def _named(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: None, name=name, description=name)


def _real_registry(integration: list[str], internal: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    registry._add_category(
        "GMAIL",
        tools=[_named(n) for n in integration],
        options=CategoryOptions(require_integration=True),
        risk=CategoryRisk(destructive_tools=set()),
    )
    registry._add_category(
        "development",
        tools=[_named(n) for n in internal],
        options=CategoryOptions(internal=True),
        risk=CategoryRisk(destructive_tools=set()),
    )
    return registry


@pytest.mark.unit
class TestResolveAgainstARealRegistry:
    async def test_integration_and_internal_tools_are_classified_by_their_category(
        self,
    ) -> None:
        registry = _real_registry(["GMAIL_SEND_EMAIL"], ["read"])
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)):
            gmail = await resolver.resolve_tool("u1", "GMAIL_SEND_EMAIL")
            read = await resolver.resolve_tool("u1", "read")
        assert gmail is not None and gmail.is_integration is True
        assert read is not None and read.is_integration is False

    async def test_an_exact_name_wins_over_a_canonical_alias_twin(self) -> None:
        """Two names that canonicalize alike: the alias map keeps only one, so an exact name must never go through it."""
        registry = _real_registry(["SEND-EMAIL", "SEND_EMAIL"], [])
        with patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=registry)):
            dashed = await resolver.resolve_tool("u1", "SEND-EMAIL")
            underscored = await resolver.resolve_tool("u1", "SEND_EMAIL")
        assert dashed is not None and dashed.name == "SEND-EMAIL"
        assert underscored is not None and underscored.name == "SEND_EMAIL"


@pytest.mark.unit
class TestMcpResolution:
    async def test_the_users_client_is_asked_for_the_named_tools_integration(self) -> None:
        wanted, other = MagicMock(), MagicMock()
        wanted.name, other.name = "NOTION_MCP_SEARCH", "LINEAR_MCP_SEARCH"
        client = MagicMock()
        client.find_integration.side_effect = {
            "NOTION_MCP_SEARCH": "notion-mcp",
            "LINEAR_MCP_SEARCH": "linear-mcp",
        }.get
        client.get_tools = AsyncMock(
            side_effect=lambda integration_id: {"notion-mcp": [wanted], "linear-mcp": [other]}[
                integration_id
            ]
        )
        get_client = AsyncMock(return_value=client)
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=get_client),
        ):
            resolved = await resolver.resolve_tool("u1", "NOTION_MCP_SEARCH")
        get_client.assert_awaited_once_with(user_id="u1")
        assert resolved == ResolvedTool(
            "NOTION_MCP_SEARCH", wanted, is_integration=True, shape_scope="mcp:notion-mcp"
        )

    async def test_an_mcp_outage_is_a_warning_naming_the_user_and_error(self) -> None:
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(side_effect=RuntimeError("down"))),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            async with captured_wide_event() as event:
                await resolver.resolve_tool("u1", "GMAIL_SEND_EMAIL")
        (warning,) = event["warnings"]
        assert warning["msg"].endswith("execute resolver: MCP client unavailable")
        assert warning["user_id"] == "u1"
        assert warning["error_type"] == "RuntimeError"


@pytest.mark.unit
class TestCatalogMaterialization:
    async def test_a_full_miss_cache_starts_over_so_an_evicted_slug_is_asked_again(self) -> None:
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
            patch(f"{MODULE}.UNKNOWN_CATALOG_SLUG_CACHE_MAX", 2),
        ):
            for slug in ("ASANA_CREATE_TASK", "ASANA_DELETE_TASK", "ASANA_GET_TASK"):
                await resolver.resolve_tool("u1", slug)
            await resolver.resolve_tool("u1", "ASANA_CREATE_TASK")
        asked = [c.args[0] for c in service.get_tools_by_name.await_args_list]
        assert asked.count(["ASANA_CREATE_TASK"]) == 2

    async def test_the_catalog_is_asked_for_exactly_the_named_slug(self) -> None:
        client = MagicMock()
        client.find_integration.return_value = None
        service = MagicMock()
        service.get_tools_by_name = AsyncMock(return_value=[])
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
            patch(f"{MODULE}.get_composio_service", return_value=service),
        ):
            await resolver.resolve_tool("u1", "ASANA_CREATE_TASK")
        service.get_tools_by_name.assert_awaited_once_with(["ASANA_CREATE_TASK"])
