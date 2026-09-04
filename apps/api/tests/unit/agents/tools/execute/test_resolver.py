"""resolve_tool — the three-source resolution order and its miss behavior."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.execute import resolver
from app.agents.tools.execute.resolver import ResolvedTool

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
        assert resolved == ResolvedTool(
            "GMAIL_SEND_EMAIL", tool, is_integration=True, in_registry=True
        )
        mcp.assert_not_awaited()
        composio.assert_not_called()

    async def test_alias_resolves_to_canonical_registry_name(self) -> None:
        tool = MagicMock()
        with patch(
            f"{MODULE}.get_tool_registry",
            new=AsyncMock(return_value=_registry_with({"GMAIL_SEND_EMAIL": tool})),
        ):
            resolved = await resolver.resolve_tool("u1", "GMAIL-SEND-EMAIL")
        assert resolved == ResolvedTool(
            "GMAIL_SEND_EMAIL", tool, is_integration=True, in_registry=True
        )

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
        """Resolution sits on the tool-call critical path — the HIL gate resolves a
        name twice before the call may run, plus once per sibling, and the
        approvals node replays. A hallucinated ALLCAPS name was a fresh Composio
        round trip every one of those times."""
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
        """A degraded Composio must fail this one resolution, not hold the gate —
        and therefore the whole turn — open for as long as it takes to answer."""
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
