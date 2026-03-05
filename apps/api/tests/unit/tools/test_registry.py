"""Unit tests for the tool registry (DynamicToolDict, ToolCategory, ToolRegistry)."""

from collections.abc import Mapping

import pytest
from unittest.mock import MagicMock

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

        keys = list(dtd)
        assert set(keys) == {"x", "y", "z"}

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
