"""Unit tests for the tool registry (DynamicToolDict, ToolCategory, ToolRegistry)."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from app.agents.tools.core.registry import (
    DynamicToolDict,
    Tool,
    ToolCategory,
    ToolRegistry,
)


def _make_mock_tool(name: str) -> BaseTool:
    """Create a minimal mock BaseTool with the given name."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


@pytest.mark.unit
class TestToolCategory:
    def test_add_tool(self):
        category = ToolCategory(name="test_cat")
        mock_tool = _make_mock_tool("my_tool")
        category.add_tool(mock_tool)

        assert len(category.tools) == 1
        assert category.tools[0].name == "my_tool"
        assert category.tools[0].tool is mock_tool

    def test_add_tool_with_custom_name(self):
        category = ToolCategory(name="test_cat")
        mock_tool = _make_mock_tool("original_name")
        category.add_tool(mock_tool, name="custom_name")

        assert category.tools[0].name == "custom_name"

    def test_add_tools_bulk(self):
        category = ToolCategory(name="test_cat")
        tools = [_make_mock_tool(f"tool_{i}") for i in range(3)]
        category.add_tools(tools)

        assert len(category.tools) == 3

    def test_get_tool_objects_returns_base_tools(self):
        category = ToolCategory(name="test_cat")
        tools = [_make_mock_tool(f"tool_{i}") for i in range(2)]
        category.add_tools(tools)

        result = category.get_tool_objects()
        assert result == tools

    def test_get_core_tools_filters_correctly(self):
        category = ToolCategory(name="test_cat")
        core = _make_mock_tool("core_tool")
        non_core = _make_mock_tool("non_core_tool")
        category.add_tool(core, is_core=True)
        category.add_tool(non_core, is_core=False)

        core_tools = category.get_core_tools()
        assert len(core_tools) == 1
        assert core_tools[0].name == "core_tool"
        assert core_tools[0].is_core is True

    def test_category_metadata(self):
        category = ToolCategory(
            name="gmail",
            space="email",
            require_integration=True,
            integration_name="gmail",
            is_delegated=True,
        )
        assert category.name == "gmail"
        assert category.space == "email"
        assert category.require_integration is True
        assert category.integration_name == "gmail"
        assert category.is_delegated is True

    def test_empty_category_returns_empty_lists(self):
        category = ToolCategory(name="empty")
        assert category.get_tool_objects() == []
        assert category.get_core_tools() == []


@pytest.mark.unit
class TestDynamicToolDict:
    def _make_registry_with_tools(self, tool_names: list[str]) -> ToolRegistry:
        registry = ToolRegistry()
        tools = [_make_mock_tool(n) for n in tool_names]
        registry._add_category("test", tools=tools)
        return registry

    def test_getitem_from_registry(self):
        registry = self._make_registry_with_tools(["search", "fetch"])
        dtd = DynamicToolDict(registry)

        result = dtd["search"]
        assert result.name == "search"

    def test_getitem_from_extra_tools(self):
        registry = self._make_registry_with_tools(["search"])
        dtd = DynamicToolDict(registry)
        handoff = _make_mock_tool("handoff")
        dtd.update({"handoff": handoff})

        assert dtd["handoff"] is handoff

    def test_getitem_extra_takes_precedence(self):
        registry = self._make_registry_with_tools(["overlap"])
        dtd = DynamicToolDict(registry)
        override = _make_mock_tool("overlap")
        dtd.update({"overlap": override})

        assert dtd["overlap"] is override

    def test_getitem_raises_key_error(self):
        registry = self._make_registry_with_tools(["search"])
        dtd = DynamicToolDict(registry)

        with pytest.raises(KeyError):
            dtd["nonexistent"]

    def test_len_counts_all(self):
        registry = self._make_registry_with_tools(["a", "b"])
        dtd = DynamicToolDict(registry)
        dtd.update({"c": _make_mock_tool("c")})

        assert len(dtd) == 3

    def test_len_deduplicates_overlapping_keys(self):
        registry = self._make_registry_with_tools(["a", "b"])
        dtd = DynamicToolDict(registry)
        dtd.update({"a": _make_mock_tool("a")})

        assert len(dtd) == 2

    def test_iter_yields_all_keys(self):
        registry = self._make_registry_with_tools(["x", "y"])
        dtd = DynamicToolDict(registry)
        dtd.update({"z": _make_mock_tool("z")})

        assert set(dtd) == {"x", "y", "z"}

    def test_iter_no_duplicates(self):
        registry = self._make_registry_with_tools(["a"])
        dtd = DynamicToolDict(registry)
        dtd.update({"a": _make_mock_tool("a")})

        keys = list(dtd)
        assert keys == ["a"]

    def test_contains(self):
        registry = self._make_registry_with_tools(["search"])
        dtd = DynamicToolDict(registry)
        dtd.update({"handoff": _make_mock_tool("handoff")})

        assert "search" in dtd
        assert "handoff" in dtd
        assert "missing" not in dtd

    def test_keys_values_items(self):
        registry = self._make_registry_with_tools(["a"])
        dtd = DynamicToolDict(registry)
        dtd.update({"b": _make_mock_tool("b")})

        assert set(dtd.keys()) == {"a", "b"}
        assert len(list(dtd.values())) == 2
        assert len(list(dtd.items())) == 2

    def test_mapping_protocol(self):
        """DynamicToolDict satisfies the Mapping ABC."""
        registry = self._make_registry_with_tools(["t"])
        dtd = DynamicToolDict(registry)
        assert isinstance(dtd, Mapping)


@pytest.mark.unit
class TestToolRegistry:
    def test_add_category(self):
        registry = ToolRegistry()
        tools = [_make_mock_tool("tool_a"), _make_mock_tool("tool_b")]
        registry._add_category("my_cat", tools=tools, space="custom_space")

        cat = registry.get_category("my_cat")
        assert cat is not None
        assert cat.space == "custom_space"
        assert len(cat.tools) == 2

    def test_add_category_with_core_tools(self):
        registry = ToolRegistry()
        core = [_make_mock_tool("core_1")]
        regular = [_make_mock_tool("reg_1")]
        registry._add_category("mixed", tools=regular, core_tools=core)

        cat = registry.get_category("mixed")
        assert len(cat.tools) == 2
        core_tools = cat.get_core_tools()
        assert len(core_tools) == 1
        assert core_tools[0].name == "core_1"

    def test_get_category_returns_none_for_missing(self):
        registry = ToolRegistry()
        assert registry.get_category("nonexistent") is None

    def test_get_category_by_space(self):
        registry = ToolRegistry()
        registry._add_category("cat1", tools=[_make_mock_tool("t1")], space="email")
        registry._add_category("cat2", tools=[_make_mock_tool("t2")], space="todos")

        result = registry.get_category_by_space("email")
        assert result is not None
        assert result.name == "cat1"

    def test_get_category_by_space_returns_none(self):
        registry = ToolRegistry()
        assert registry.get_category_by_space("nonexistent") is None

    def test_get_tool_names(self):
        registry = ToolRegistry()
        registry._add_category(
            "cat1", tools=[_make_mock_tool("a"), _make_mock_tool("b")]
        )
        registry._add_category("cat2", tools=[_make_mock_tool("c")])

        names = registry.get_tool_names()
        assert set(names) == {"a", "b", "c"}

    def test_get_tool_dict_returns_dynamic(self):
        registry = ToolRegistry()
        registry._add_category("cat", tools=[_make_mock_tool("t")])

        dtd = registry.get_tool_dict()
        assert isinstance(dtd, DynamicToolDict)
        assert "t" in dtd

    def test_get_category_of_tool(self):
        registry = ToolRegistry()
        registry._add_category("search", tools=[_make_mock_tool("web_search")])
        registry._add_category("memory", tools=[_make_mock_tool("store_memory")])

        assert registry.get_category_of_tool("web_search") == "search"
        assert registry.get_category_of_tool("store_memory") == "memory"
        assert registry.get_category_of_tool("unknown_tool") == "unknown"

    def test_get_all_tools_for_search_includes_delegated(self):
        registry = ToolRegistry()
        registry._add_category("cat1", tools=[_make_mock_tool("a")])
        registry._add_category("cat2", tools=[_make_mock_tool("b")], is_delegated=True)

        all_tools = registry.get_all_tools_for_search(include_delegated=True)
        names = [t.name for t in all_tools]
        assert "a" in names
        assert "b" in names

    def test_get_all_tools_for_search_excludes_delegated(self):
        registry = ToolRegistry()
        registry._add_category("cat1", tools=[_make_mock_tool("a")])
        registry._add_category("cat2", tools=[_make_mock_tool("b")], is_delegated=True)

        non_delegated = registry.get_all_tools_for_search(include_delegated=False)
        names = [t.name for t in non_delegated]
        assert "a" in names
        assert "b" not in names

    def test_get_core_categories(self):
        registry = ToolRegistry()
        registry._add_category("builtin", tools=[_make_mock_tool("a")])
        registry._add_category(
            "integration", tools=[_make_mock_tool("b")], require_integration=True
        )

        core_cats = registry.get_core_categories()
        names = [c.name for c in core_cats]
        assert "builtin" in names
        assert "integration" not in names

    def test_get_all_category_objects_with_ignore(self):
        registry = ToolRegistry()
        registry._add_category("keep", tools=[_make_mock_tool("a")])
        registry._add_category("ignore", tools=[_make_mock_tool("b")])

        result = registry.get_all_category_objects(ignore_categories=["ignore"])
        assert "keep" in result
        assert "ignore" not in result


@pytest.mark.unit
class TestToolWrapper:
    def test_tool_defaults_name_from_base_tool(self):
        base = _make_mock_tool("auto_name")
        tool = Tool(tool=base)
        assert tool.name == "auto_name"
        assert tool.is_core is False

    def test_tool_custom_name_override(self):
        base = _make_mock_tool("original")
        tool = Tool(tool=base, name="override", is_core=True)
        assert tool.name == "override"
        assert tool.is_core is True


# ---------------------------------------------------------------------------
# Helpers shared by async tests
# ---------------------------------------------------------------------------

_CORE_CATEGORY_NAMES = [
    "search",
    "documents",
    "notifications",
    "todos",
    "reminders",
    "goal_tracking",
    "skills",
    "workflows",
    "support",
    "memory",
    "filesystem",
    "integrations",
    "development",
    "creative",
    "weather",
    "context",
]


def _patch_initialize_categories():
    """
    Return a patcher that replaces _initialize_categories with a lightweight
    stub, avoiding imports of all production tool modules.

    The stub registers exactly the categories listed in _CORE_CATEGORY_NAMES so
    tests can assert on category presence without pulling in tool dependencies.
    """

    def _stub_initialize(self: ToolRegistry):
        for cat_name in _CORE_CATEGORY_NAMES:
            self._add_category(cat_name, tools=[_make_mock_tool(f"{cat_name}_tool")])

    return patch.object(ToolRegistry, "_initialize_categories", _stub_initialize)


def _patch_index_category_tools():
    """Return a patcher that makes _index_category_tools a no-op coroutine."""
    return patch.object(
        ToolRegistry,
        "_index_category_tools",
        new_callable=lambda: lambda *_: AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# Async tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToolRegistryAsync:
    async def test_setup_initializes_all_categories(self):
        """setup() must populate registry.categories with the expected structure."""
        registry = ToolRegistry()

        with _patch_initialize_categories():
            await registry.setup()

        for name in _CORE_CATEGORY_NAMES:
            cat = registry.get_category(name)
            assert cat is not None, f"category '{name}' missing after setup()"
            assert isinstance(cat, ToolCategory)
            assert len(cat.tools) > 0, f"category '{name}' has no tools after setup()"

    async def test_setup_idempotent(self):
        """Calling setup() twice must not duplicate tools."""
        registry = ToolRegistry()

        with _patch_initialize_categories():
            await registry.setup()
            counts_after_first = {
                name: len(registry.get_category(name).tools)
                for name in _CORE_CATEGORY_NAMES
            }

            await registry.setup()
            counts_after_second = {
                name: len(registry.get_category(name).tools)
                for name in _CORE_CATEGORY_NAMES
            }

        # _initialize_categories replaces the dict entry each call, so counts
        # stay equal — duplicates would manifest as a larger count.
        assert counts_after_first == counts_after_second

    async def test_register_provider_tools_with_composio(self):
        """register_provider_tools() must store composio tools in the registry."""
        fake_tools = [_make_mock_tool("GMAIL_SEND"), _make_mock_tool("GMAIL_READ")]
        mock_composio_service = MagicMock()
        mock_composio_service.get_tools = AsyncMock(return_value=fake_tools)

        registry = ToolRegistry()

        with (
            patch(
                "app.services.composio.composio_service.get_composio_service",
                return_value=mock_composio_service,
            ),
            patch.object(
                registry,
                "_index_category_tools",
                new=AsyncMock(return_value=None),
            ),
        ):
            category = await registry.register_provider_tools(
                toolkit_name="GMAIL",
                space_name="email",
            )

        assert category is not None
        tool_names = [t.name for t in category.tools]
        assert "GMAIL_SEND" in tool_names
        assert "GMAIL_READ" in tool_names
        assert len(category.tools) == 2
        mock_composio_service.get_tools.assert_awaited_once_with(tool_kit="GMAIL")

    async def test_register_provider_tools_skips_existing_category(self):
        """register_provider_tools() must not re-register an already-loaded toolkit."""
        registry = ToolRegistry()
        existing_tool = _make_mock_tool("EXISTING_TOOL")
        registry._add_category("GITHUB", tools=[existing_tool])

        mock_composio_service = MagicMock()
        mock_composio_service.get_tools = AsyncMock(return_value=[])

        # The early-return path fires before any composio import, so no patch needed.
        result = await registry.register_provider_tools(
            toolkit_name="GITHUB",
            space_name="github",
        )

        # Must return the existing category without calling get_tools
        assert result is registry.get_category("GITHUB")
        mock_composio_service.get_tools.assert_not_awaited()

    async def test_load_all_provider_tools_handles_one_failure(self):
        """
        If one provider raises an exception, the others still load successfully.

        We construct three fake integrations:
        - integration_a  -> loads fine (returns two tools)
        - integration_b  -> composio raises RuntimeError
        - integration_c  -> loads fine (returns one tool)
        """
        from app.models.mcp_config import ComposioConfig, SubAgentConfig
        from app.models.oauth_models import OAuthIntegration

        def _make_integration(toolkit: str, space: str) -> OAuthIntegration:
            return OAuthIntegration(
                id=toolkit.lower(),
                name=toolkit,
                description="test",
                category="productivity",
                provider="test",
                scopes=[],
                managed_by="composio",
                composio_config=ComposioConfig(
                    auth_config_id="ac_test",
                    toolkit=toolkit,
                ),
                subagent_config=SubAgentConfig(
                    has_subagent=True,
                    agent_name=f"{toolkit}_agent",
                    tool_space=space,
                    handoff_tool_name=f"handoff_{toolkit.lower()}",
                    domain="test",
                    capabilities="test",
                    use_cases="test",
                    system_prompt="test",
                ),
            )

        integration_a = _make_integration("TOOLKIT_A", "space_a")
        integration_b = _make_integration("TOOLKIT_B", "space_b")
        integration_c = _make_integration("TOOLKIT_C", "space_c")
        fake_integrations = [integration_a, integration_b, integration_c]

        tools_a = [_make_mock_tool("TOOLKIT_A_ACTION")]
        tools_c = [_make_mock_tool("TOOLKIT_C_ACTION")]

        mock_composio_service = MagicMock()

        async def _get_tools_side_effect(tool_kit: str):
            if tool_kit == "TOOLKIT_A":
                return tools_a
            if tool_kit == "TOOLKIT_B":
                raise RuntimeError("Composio unavailable for TOOLKIT_B")
            return tools_c

        mock_composio_service.get_tools = AsyncMock(side_effect=_get_tools_side_effect)

        registry = ToolRegistry()

        with (
            patch(
                "app.config.oauth_config.OAUTH_INTEGRATIONS",
                fake_integrations,
            ),
            patch(
                "app.services.composio.composio_service.get_composio_service",
                return_value=mock_composio_service,
            ),
            patch.object(
                registry,
                "_index_category_tools",
                new=AsyncMock(return_value=None),
            ),
        ):
            await registry.load_all_provider_tools()

        # Successful providers must be registered
        assert registry.get_category("TOOLKIT_A") is not None
        assert registry.get_category("TOOLKIT_C") is not None
        # Failed provider must NOT be registered
        assert registry.get_category("TOOLKIT_B") is None

        a_names = [t.name for t in registry.get_category("TOOLKIT_A").tools]
        assert "TOOLKIT_A_ACTION" in a_names
        c_names = [t.name for t in registry.get_category("TOOLKIT_C").tools]
        assert "TOOLKIT_C_ACTION" in c_names

    async def test_load_user_mcp_tools_registers_tools(self):
        """
        load_user_mcp_tools() must register MCP tools under the correct category
        name and track them under the given user_id.
        """
        from app.models.mcp_config import MCPConfig, SubAgentConfig
        from app.models.oauth_models import OAuthIntegration

        user_id = "user-mcp-42"
        integration_id = "my_mcp_server"
        fake_tools = [_make_mock_tool("MCP_ACTION_1"), _make_mock_tool("MCP_ACTION_2")]

        mock_mcp_client = MagicMock()
        mock_mcp_client.get_all_connected_tools = AsyncMock(
            return_value={integration_id: fake_tools}
        )

        # Provide a platform integration with a subagent_config so the registry
        # uses the configured space name rather than hitting IntegrationResolver.
        fake_integration = OAuthIntegration(
            id=integration_id,
            name="My MCP Server",
            description="test",
            category="productivity",
            provider="mcp",
            scopes=[],
            managed_by="mcp",
            mcp_config=MCPConfig(server_url="https://example.com/mcp"),
            subagent_config=SubAgentConfig(
                has_subagent=True,
                agent_name="my_mcp_agent",
                tool_space="mcp_space",
                handoff_tool_name="handoff_mcp",
                domain="test",
                capabilities="test",
                use_cases="test",
                system_prompt="test",
            ),
        )

        registry = ToolRegistry()

        with (
            patch(
                "app.services.mcp.mcp_client.get_mcp_client",
                new=AsyncMock(return_value=mock_mcp_client),
            ),
            patch(
                "app.config.oauth_config.get_integration_by_id",
                return_value=fake_integration,
            ),
            patch.object(
                registry,
                "_index_category_tools",
                new=AsyncMock(return_value=None),
            ),
        ):
            loaded = await registry.load_user_mcp_tools(user_id)

        expected_category = f"mcp_{integration_id}"

        # Returned mapping must include the integration
        assert integration_id in loaded
        assert len(loaded[integration_id]) == 2

        # Category must exist with correct name and space
        cat = registry.get_category(expected_category)
        assert cat is not None
        assert cat.space == "mcp_space"
        assert cat.integration_name == integration_id
        tool_names = [t.name for t in cat.tools]
        assert "MCP_ACTION_1" in tool_names
        assert "MCP_ACTION_2" in tool_names

        # User association must be tracked
        assert expected_category in registry._user_mcp_categories[user_id]

    async def test_load_user_mcp_tools_skips_empty_tool_list(self):
        """load_user_mcp_tools() must not register a category when a server returns
        no tools."""
        user_id = "user-mcp-empty"
        mock_mcp_client = MagicMock()
        mock_mcp_client.get_all_connected_tools = AsyncMock(
            return_value={"empty_server": []}
        )

        registry = ToolRegistry()

        with patch(
            "app.services.mcp.mcp_client.get_mcp_client",
            new=AsyncMock(return_value=mock_mcp_client),
        ):
            loaded = await registry.load_user_mcp_tools(user_id)

        assert loaded == {}
        assert registry.get_category("mcp_empty_server") is None
