"""Behavior spec for app/agents/tools/core/tool_runtime_config.py.

This module builds the tool-runtime configuration that decides which tools a
parent provider-agent and its spawned children bind, and how create_agent is
wired for retrieval. The exact ordering, dedup, and toggle behaviour is a
contract relied on by base_subagent.py and build_graph.py.

UNIT: ToolRuntimeConfig (dataclass)
EXPECTED: A field-default holder; default config enables retrieve tools, keeps
          subagents out of retrieve scope, and starts with no initial tools.
MECHANISM: dataclass(slots=True) with defaults enable_retrieve_tools=True,
           include_subagents_in_retrieve=False, initial_tool_names=[].
MUST-CATCH:
  - default enable_retrieve_tools is True (not False)
  - default include_subagents_in_retrieve is False (not True)
  - default initial_tool_names is an independent empty list (not shared)

UNIT: build_create_agent_tool_kwargs(config, *, tool_space)
EXPECTED: Always pass initial_tool_ids through unchanged. When retrieval is
          enabled, attach a retrieve_tools_coroutine built for the given
          tool_space and subagent scope and DO NOT disable retrieval. When
          disabled, set disable_retrieve_tools=True and omit the coroutine.
MECHANISM: kwargs["initial_tool_ids"] = config.initial_tool_names; branch on
           config.enable_retrieve_tools -> get_retrieve_tools_function(
           tool_space=tool_space, include_subagents=...) or
           kwargs["disable_retrieve_tools"] = True.
MUST-CATCH:
  - initial_tool_ids equals the config's initial_tool_names exactly
  - enabled branch produces "retrieve_tools_coroutine" and no disable flag
  - disabled branch produces disable_retrieve_tools=True and no coroutine
  - the retrieval factory receives the passed tool_space (not a constant)
  - the retrieval factory receives include_subagents from the config flag

UNIT: build_provider_parent_tool_runtime_config(...)
EXPECTED: Assemble the parent's initial tool list with the right ordering for
          direct vs dynamic mode, append finish_task only when requested, and
          dedup auto-bind names already covered by provider tools. enable
          retrieve = not disable_retrieve_tools; never expose subagents in
          retrieve.
MECHANISM: finish branch; provider_tool_set dedup of auto_bind_tool_names;
           direct list [provider, extra_auto_bind, todo, finish, vfs_read,
           vfs_cmd] vs dynamic list [search_memory, vfs_read, vfs_cmd, finish,
           todo, extra_auto_bind]; ToolRuntimeConfig(enable=not disable,
           include_subagents_in_retrieve=False).
MUST-CATCH:
  - direct mode ordering and membership exactly
  - dynamic mode ordering and membership exactly (search_memory leads)
  - auto-bind names overlapping provider tools are dropped (dedup)
  - None auto_bind_tool_names is treated as empty (no crash, nothing added)
  - include_finish_task=False removes finish_task from initial
  - disable_retrieve_tools maps to enable_retrieve_tools = not disable
  - include_subagents_in_retrieve is always False

UNIT: build_child_tool_runtime_config(parent, *, use_direct_tools, disable_retrieve_tools)
EXPECTED: In direct+disabled mode the child inherits the parent's exact tool
          list with retrieval off. In every other mode the child is reset to
          the minimal vfs+finish set and retrieval follows the disable flag.
MECHANISM: if use_direct_tools and disable_retrieve_tools -> inherit parent
           list, enable=False; else minimal ["vfs_read","vfs_cmd",finish],
           enable=not disable.
MUST-CATCH:
  - direct+disabled inherits parent.initial_tool_names and disables retrieval
  - direct+enabled falls through to minimal set (both conditions required)
  - dynamic+disabled falls through to minimal set, retrieval off
  - dynamic+enabled falls through to minimal set, retrieval on
  - the minimal set is exactly ["vfs_read","vfs_cmd","finish_task"]
  - include_subagents_in_retrieve is always False

UNIT: build_executor_child_tool_runtime_config()
EXPECTED: Executor-spawned children always get the minimal vfs+finish toolset
          with retrieval enabled and subagents excluded.
MECHANISM: ToolRuntimeConfig(["vfs_read","vfs_cmd",finish], enable=True,
           include_subagents=False).
MUST-CATCH:
  - initial list is exactly ["vfs_read","vfs_cmd","finish_task"]
  - enable_retrieve_tools is True
  - include_subagents_in_retrieve is False

EQUIVALENT MUTANTS (allowed survivors, justified): none.
"""

from unittest.mock import patch

import pytest

from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_child_tool_runtime_config,
    build_create_agent_tool_kwargs,
    build_executor_child_tool_runtime_config,
    build_provider_parent_tool_runtime_config,
)
from app.constants.general import FINISH_TASK_NAME

# The single I/O boundary: a factory that (later) hits the tool store. Patched
# at the module under test so we assert the args it receives without touching
# ChromaDB / the store.
_RETRIEVAL_FACTORY = "app.agents.tools.core.tool_runtime_config.get_retrieve_tools_function"

_MINIMAL_CHILD_TOOLS = ["vfs_read", "vfs_cmd", FINISH_TASK_NAME]


# ---------------------------------------------------------------------------
# ToolRuntimeConfig dataclass defaults
# ---------------------------------------------------------------------------


class TestToolRuntimeConfigDefaults:
    def test_defaults(self):
        config = ToolRuntimeConfig()
        assert config.initial_tool_names == []
        assert config.enable_retrieve_tools is True
        assert config.include_subagents_in_retrieve is False

    def test_default_list_is_not_shared_between_instances(self):
        first = ToolRuntimeConfig()
        second = ToolRuntimeConfig()
        first.initial_tool_names.append("leak")
        assert second.initial_tool_names == []


# ---------------------------------------------------------------------------
# build_create_agent_tool_kwargs
# ---------------------------------------------------------------------------


class TestBuildCreateAgentToolKwargs:
    def test_enabled_attaches_retrieve_coroutine_and_passes_through_initial(self):
        sentinel = object()
        config = ToolRuntimeConfig(
            initial_tool_names=["vfs_read", "todo_add"],
            enable_retrieve_tools=True,
            include_subagents_in_retrieve=True,
        )
        with patch(_RETRIEVAL_FACTORY, return_value=sentinel) as factory:
            kwargs = build_create_agent_tool_kwargs(config, tool_space="gmail_space")

        assert kwargs["initial_tool_ids"] == ["vfs_read", "todo_add"]
        assert kwargs["retrieve_tools_coroutine"] is sentinel
        assert "disable_retrieve_tools" not in kwargs
        # Factory is configured for the caller's space and subagent scope, not constants.
        factory.assert_called_once_with(tool_space="gmail_space", include_subagents=True)

    def test_enabled_forwards_include_subagents_false(self):
        config = ToolRuntimeConfig(enable_retrieve_tools=True, include_subagents_in_retrieve=False)
        with patch(_RETRIEVAL_FACTORY, return_value=object()) as factory:
            build_create_agent_tool_kwargs(config, tool_space="general")
        factory.assert_called_once_with(tool_space="general", include_subagents=False)

    def test_disabled_sets_disable_flag_and_no_coroutine(self):
        config = ToolRuntimeConfig(initial_tool_names=["vfs_read"], enable_retrieve_tools=False)
        with patch(_RETRIEVAL_FACTORY) as factory:
            kwargs = build_create_agent_tool_kwargs(config, tool_space="general")

        assert kwargs["disable_retrieve_tools"] is True
        assert "retrieve_tools_coroutine" not in kwargs
        assert kwargs["initial_tool_ids"] == ["vfs_read"]
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# build_provider_parent_tool_runtime_config
# ---------------------------------------------------------------------------


class TestBuildProviderParentToolRuntimeConfig:
    def test_direct_mode_ordering_and_membership(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=["p1", "p2"],
            todo_tool_names=["todo_add"],
            auto_bind_tool_names=["auto1"],
            use_direct_tools=True,
            disable_retrieve_tools=False,
        )
        assert config.initial_tool_names == [
            "p1",
            "p2",
            "auto1",
            "todo_add",
            FINISH_TASK_NAME,
            "vfs_read",
            "vfs_cmd",
        ]
        assert config.enable_retrieve_tools is True
        assert config.include_subagents_in_retrieve is False

    def test_dynamic_mode_ordering_and_membership(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=["p1"],
            todo_tool_names=["todo_add"],
            auto_bind_tool_names=["auto1"],
            use_direct_tools=False,
            disable_retrieve_tools=False,
        )
        # Dynamic mode does NOT bind provider tools directly; search_memory leads.
        assert config.initial_tool_names == [
            "search_memory",
            "vfs_read",
            "vfs_cmd",
            FINISH_TASK_NAME,
            "todo_add",
            "auto1",
        ]

    def test_auto_bind_overlapping_provider_is_deduped_direct(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=["shared", "p2"],
            todo_tool_names=[],
            auto_bind_tool_names=["shared", "unique"],
            use_direct_tools=True,
            disable_retrieve_tools=False,
        )
        # "shared" is already a provider tool, so it must not be re-added as auto-bind.
        assert config.initial_tool_names == [
            "shared",
            "p2",
            "unique",
            FINISH_TASK_NAME,
            "vfs_read",
            "vfs_cmd",
        ]

    def test_none_auto_bind_treated_as_empty(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=["p1"],
            todo_tool_names=[],
            auto_bind_tool_names=None,
            use_direct_tools=True,
            disable_retrieve_tools=False,
        )
        assert config.initial_tool_names == [
            "p1",
            FINISH_TASK_NAME,
            "vfs_read",
            "vfs_cmd",
        ]

    def test_include_finish_task_false_omits_finish(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=["p1"],
            todo_tool_names=[],
            auto_bind_tool_names=None,
            use_direct_tools=True,
            disable_retrieve_tools=False,
            include_finish_task=False,
        )
        assert FINISH_TASK_NAME not in config.initial_tool_names
        assert config.initial_tool_names == ["p1", "vfs_read", "vfs_cmd"]

    def test_disable_retrieve_tools_maps_to_enable_false(self):
        config = build_provider_parent_tool_runtime_config(
            provider_tool_names=[],
            todo_tool_names=[],
            auto_bind_tool_names=None,
            use_direct_tools=False,
            disable_retrieve_tools=True,
        )
        assert config.enable_retrieve_tools is False


# ---------------------------------------------------------------------------
# build_child_tool_runtime_config
# ---------------------------------------------------------------------------


class TestBuildChildToolRuntimeConfig:
    def _parent(self) -> ToolRuntimeConfig:
        return ToolRuntimeConfig(
            initial_tool_names=["p1", "p2", "vfs_read"],
            enable_retrieve_tools=True,
        )

    def test_direct_and_disabled_inherits_parent_tools_and_disables_retrieve(self):
        parent = self._parent()
        child = build_child_tool_runtime_config(
            parent, use_direct_tools=True, disable_retrieve_tools=True
        )
        assert child.initial_tool_names == ["p1", "p2", "vfs_read"]
        assert child.enable_retrieve_tools is False
        assert child.include_subagents_in_retrieve is False

    def test_direct_but_retrieve_enabled_falls_through_to_minimal(self):
        # use_direct_tools=True but disable_retrieve_tools=False -> NOT the inherit branch.
        parent = self._parent()
        child = build_child_tool_runtime_config(
            parent, use_direct_tools=True, disable_retrieve_tools=False
        )
        assert child.initial_tool_names == _MINIMAL_CHILD_TOOLS
        assert child.enable_retrieve_tools is True

    def test_dynamic_and_disabled_falls_through_to_minimal_retrieve_off(self):
        # disable_retrieve_tools=True but use_direct_tools=False -> NOT the inherit branch.
        parent = self._parent()
        child = build_child_tool_runtime_config(
            parent, use_direct_tools=False, disable_retrieve_tools=True
        )
        assert child.initial_tool_names == _MINIMAL_CHILD_TOOLS
        assert child.enable_retrieve_tools is False

    def test_dynamic_and_enabled_minimal_retrieve_on(self):
        parent = self._parent()
        child = build_child_tool_runtime_config(
            parent, use_direct_tools=False, disable_retrieve_tools=False
        )
        assert child.initial_tool_names == _MINIMAL_CHILD_TOOLS
        assert child.enable_retrieve_tools is True
        assert child.include_subagents_in_retrieve is False


# ---------------------------------------------------------------------------
# build_executor_child_tool_runtime_config
# ---------------------------------------------------------------------------


class TestBuildExecutorChildToolRuntimeConfig:
    def test_minimal_toolset_retrieve_on_no_subagents(self):
        config = build_executor_child_tool_runtime_config()
        assert config.initial_tool_names == _MINIMAL_CHILD_TOOLS
        assert config.enable_retrieve_tools is True
        assert config.include_subagents_in_retrieve is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
