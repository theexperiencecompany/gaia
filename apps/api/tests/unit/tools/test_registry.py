"""Unit tests for the tool registry (DynamicToolDict, ToolCategory, ToolRegistry)."""

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.tools import BaseTool
import pytest

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


class TestToolCategory:
    def test_add_tool(self):
        category = ToolCategory(name="test_cat")
        mock_tool = _make_mock_tool("my_tool")
        category.add_tool(mock_tool)

        assert len(category.tools) == 1
        assert category.tools[0].name == "my_tool"
        assert category.tools[0].tool is mock_tool
        # Defaults: not core, unclassified HIL risk, no forced gate.
        assert category.tools[0].is_core is False
        assert category.tools[0].destructive is None
        assert category.tools[0].always_gate is False

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

    def test_add_tools_classifies_destructive_by_membership(self):
        """A curated set classifies every tool by name membership; no set at
        all leaves the HIL risk unclassified (None) for the LLM classifier."""
        category = ToolCategory(name="test_cat")
        dangerous = _make_mock_tool("dangerous")
        safe = _make_mock_tool("safe")
        unclassified = _make_mock_tool("mystery")
        category.add_tools([dangerous, safe], destructive_tools={"dangerous"})
        category.add_tools([unclassified])

        by_name = {tool.name: tool.destructive for tool in category.tools}
        assert by_name == {"dangerous": True, "safe": False, "mystery": None}

    def test_add_tools_stamps_always_gate_membership(self):
        """Forced-ask is stamped per tool: members gate in EVERY mode, and
        non-members are explicitly False — never an unclassified None."""
        category = ToolCategory(name="test_cat")
        gated = _make_mock_tool("gated")
        ungated = _make_mock_tool("ungated")
        category.add_tools([gated, ungated], always_gate_tools={"gated"})

        assert category.tools[0].always_gate is True
        assert category.tools[1].always_gate is False

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

    def test_core_tools_receive_the_hil_stamps_too(self):
        """A category registers its HIL sets for BOTH tool lists.

        `_add_category` calls `add_tools` twice — once for `core_tools`, once
        for `tools` — and every existing test passes its risk sets through the
        `tools=` call only. A forced-gate tool registered as a core tool would
        silently lose its stamp and stop asking for approval, which is the
        whole point of the flag.
        """
        registry = ToolRegistry()
        registry._add_category(
            "mixed",
            core_tools=[_make_mock_tool("core_gated"), _make_mock_tool("core_plain")],
            tools=[_make_mock_tool("reg_dangerous")],
            destructive_tools={"reg_dangerous", "core_gated"},
            always_gate_tools={"core_gated"},
        )

        stamps = {t.name: t for t in registry.get_category("mixed").tools}
        assert stamps["core_gated"].always_gate is True
        assert stamps["core_gated"].destructive is True
        assert stamps["core_plain"].always_gate is False
        assert stamps["core_plain"].destructive is False
        assert stamps["reg_dangerous"].destructive is True

    def test_replacing_category_drops_stale_name_index(self):
        """Re-registering a category must evict its previous tools from the
        name index, or removed tools keep resolving to a dead category."""
        registry = ToolRegistry()
        registry._add_category("cat", tools=[_make_mock_tool("old_tool")])
        registry._add_category("cat", tools=[_make_mock_tool("new_tool")])

        assert registry.get_category_of_tool("old_tool") == "unknown"
        assert registry.get_tool_meta("old_tool") is None
        assert registry.get_category_of_tool("new_tool") == "cat"

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
        registry._add_category("cat1", tools=[_make_mock_tool("a"), _make_mock_tool("b")])
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


class TestToolWrapper:
    def test_tool_defaults_name_from_base_tool(self):
        base = _make_mock_tool("auto_name")
        tool = Tool(tool=base)
        assert tool.name == "auto_name"
        assert tool.is_core is False
        assert tool.always_gate is False

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


class TestBillingCategory:
    def test_billing_category_registers_the_subscription_tools(self):
        """The real initializer must wire the billing category to the two
        subscription tools with nothing marked destructive — a checkout link is
        inert until the user pays it, so the upgrade flow must never trip HIL."""
        registry = ToolRegistry()
        registry._initialize_categories()

        category = registry.get_category("billing")
        assert category is not None
        assert sorted(tool.name for tool in category.tools) == [
            "create_upgrade_link",
            "get_subscription_details",
        ]
        assert all(tool.destructive is False for tool in category.tools)
        assert category.internal is False


class TestCoreInitializationContract:
    """The real initializer's HIL contract, pinned by name.

    These assertions are deliberately exact: a renamed/mangled category, a
    dropped tool list, or an uncurated destructive set would silently change
    which tools the executor can reach and how the HIL gate judges them.
    """

    def test_search_documents_and_notifications_register_expected_tools(self):
        registry = ToolRegistry()
        registry._initialize_categories()

        search = registry.get_category("search")
        documents = registry.get_category("documents")
        notifications = registry.get_category("notifications")
        assert search is not None
        assert documents is not None
        assert notifications is not None

        assert [tool.name for tool in search.tools] == [
            "web_search_tool",
            "fetch_webpages",
            "deep_research",
            "download",
        ]
        assert [tool.name for tool in documents.tools] == ["search_uploaded_files"]
        assert [tool.name for tool in notifications.tools] == [
            "get_notifications",
            "search_notifications",
            "get_notification_count",
            "mark_notifications_read",
            "send_notification",
            "get_notification_preferences",
        ]

    def test_every_initialized_tool_has_an_explicit_hil_classification(self):
        """No built-in tool may ship unclassified (destructive=None): the HIL
        gate would fall to the LLM classifier for code-reviewed tools."""
        registry = ToolRegistry()
        registry._initialize_categories()

        unclassified = [
            (category.name, tool.name)
            for category in registry.get_all_category_objects().values()
            for tool in category.tools
            if tool.destructive is None
        ]
        assert unclassified == []

        assert registry.is_tool_destructive("send_notification") is True
        assert registry.is_tool_destructive("web_search_tool") is False
        assert registry.is_tool_destructive("search_uploaded_files") is False

    def test_account_category_pins_the_forced_ask_settings_tools(self):
        """The account settings tools are stamped forced-ask (settings on the
        user's own account ask in EVERY mode); manage_linked_account rides the
        argument gate instead and nothing here is destructive. A renamed
        category, a mangled member, or a lost stamp silently changes what the
        HIL gate may wave through."""
        registry = ToolRegistry()
        registry._initialize_categories()

        category = registry.get_category("account")
        assert category is not None
        assert [tool.name for tool in category.tools] == [
            "update_notification_settings",
            "update_preferences",
            "update_custom_instructions",
            "set_selected_voice",
            "manage_linked_account",
        ]
        assert {tool.name for tool in category.tools if tool.always_gate} == {
            "update_notification_settings",
            "update_preferences",
            "update_custom_instructions",
            "set_selected_voice",
        }
        assert all(tool.destructive is False for tool in category.tools)


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


class TestToolRegistryAsync:
    async def test_setup_initializes_all_categories(self):
        """setup() must populate registry.categories with the expected structure."""
        registry = ToolRegistry()

        with _patch_initialize_categories():
            registry.setup()

        for name in _CORE_CATEGORY_NAMES:
            cat = registry.get_category(name)
            assert cat is not None, f"category '{name}' missing after setup()"
            assert isinstance(cat, ToolCategory)
            assert len(cat.tools) > 0, f"category '{name}' has no tools after setup()"

    async def test_setup_idempotent(self):
        """Calling setup() twice must not duplicate tools."""
        registry = ToolRegistry()

        with _patch_initialize_categories():
            registry.setup()
            counts_after_first = {
                name: len(registry.get_category(name).tools) for name in _CORE_CATEGORY_NAMES
            }

            registry.setup()
            counts_after_second = {
                name: len(registry.get_category(name).tools) for name in _CORE_CATEGORY_NAMES
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
                "app.agents.tools.core.registry.get_composio_service",
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
        mock_composio_service.get_tools.assert_awaited_once_with(
            tool_kit="GMAIL", exclude_tools=None
        )

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

    # Tests for load_user_mcp_tools were removed when the per-user MCP cache
    # was deleted in the resilience rewrite. MCP tools now live exclusively
    # inside MCPClient; per-subagent builds read them live. Coverage for that
    # path lives in tests/integration/agents/test_subagent_handoff.py.
