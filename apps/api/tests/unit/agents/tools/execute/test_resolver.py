"""resolve_tool — the three-source resolution order and its miss behavior."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.execute import resolver

MODULE = "app.agents.tools.execute.resolver"


def _registry_with(names_to_tools: dict[str, MagicMock]) -> MagicMock:
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
    return registry


@pytest.fixture(autouse=True)
def _fresh_cache():
    resolver._materialized_composio_tools.clear()
    yield
    resolver._materialized_composio_tools.clear()


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
        assert resolved == ("GMAIL_SEND_EMAIL", tool)
        mcp.assert_not_awaited()
        composio.assert_not_called()

    async def test_alias_resolves_to_canonical_registry_name(self) -> None:
        tool = MagicMock()
        with patch(
            f"{MODULE}.get_tool_registry",
            new=AsyncMock(return_value=_registry_with({"GMAIL_SEND_EMAIL": tool})),
        ):
            resolved = await resolver.resolve_tool("u1", "GMAIL-SEND-EMAIL")
        assert resolved == ("GMAIL_SEND_EMAIL", tool)

    async def test_mcp_fallback_when_registry_misses(self) -> None:
        mcp_tool = MagicMock()
        mcp_tool.name = "NOTION_MCP_SEARCH"
        client = MagicMock()
        client.find_integration.return_value = "notion-mcp"
        client.get_tools.return_value = [mcp_tool]
        with (
            patch(f"{MODULE}.get_tool_registry", new=AsyncMock(return_value=_registry_with({}))),
            patch(f"{MODULE}.get_mcp_client", new=AsyncMock(return_value=client)),
        ):
            resolved = await resolver.resolve_tool("u1", "NOTION_MCP_SEARCH")
        assert resolved == ("NOTION_MCP_SEARCH", mcp_tool)

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
        assert first == ("ASANA_CREATE_TASK", catalog_tool)
        assert second == ("ASANA_CREATE_TASK", catalog_tool)
        service.get_tools_by_name.assert_awaited_once()

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
