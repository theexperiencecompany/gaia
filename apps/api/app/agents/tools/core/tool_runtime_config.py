"""Shared tool runtime configuration for agent and child-agent execution."""

from dataclasses import dataclass, field
from typing import Any

from app.agents.tools.core.retrieval import get_retrieve_tools_function


@dataclass(slots=True)
class ToolRuntimeConfig:
    """Tool runtime behavior shared by parent and spawned child execution.

    - `initial_tool_names`: regular tools bound immediately (e.g. vfs_read)
    - `enable_retrieve_tools`: whether retrieve_tools should be available
    - `include_subagents_in_retrieve`: retrieve_tools discovery scope toggle
    """

    initial_tool_names: list[str] = field(default_factory=list)
    enable_retrieve_tools: bool = True
    include_subagents_in_retrieve: bool = False


def build_create_agent_tool_kwargs(
    tool_runtime_config: ToolRuntimeConfig,
    *,
    tool_space: str,
) -> dict[str, Any]:
    """Build create_agent kwargs from shared tool runtime config."""
    kwargs: dict[str, Any] = {
        "initial_tool_ids": tool_runtime_config.initial_tool_names,
    }
    if tool_runtime_config.enable_retrieve_tools:
        kwargs["retrieve_tools_coroutine"] = get_retrieve_tools_function(
            tool_space=tool_space,
            include_subagents=tool_runtime_config.include_subagents_in_retrieve,
        )
    else:
        kwargs["disable_retrieve_tools"] = True
    return kwargs


def build_provider_parent_tool_runtime_config(
    *,
    provider_tool_names: list[str],
    todo_tool_names: list[str],
    auto_bind_tool_names: list[str] | None,
    use_direct_tools: bool,
    disable_retrieve_tools: bool,
) -> ToolRuntimeConfig:
    """Build parent provider-agent tool runtime config."""
    if use_direct_tools:
        initial = [*provider_tool_names, *todo_tool_names, "vfs_read"]
    else:
        initial = ["search_memory", "vfs_read", *todo_tool_names]
        if auto_bind_tool_names and not disable_retrieve_tools:
            initial.extend(auto_bind_tool_names)

    return ToolRuntimeConfig(
        initial_tool_names=initial,
        enable_retrieve_tools=not disable_retrieve_tools,
        include_subagents_in_retrieve=False,
    )


def build_child_tool_runtime_config(
    parent_tool_runtime_config: ToolRuntimeConfig,
    *,
    use_direct_tools: bool,
    disable_retrieve_tools: bool,
) -> ToolRuntimeConfig:
    """Build spawned child tool runtime config from parent mode."""
    if use_direct_tools and disable_retrieve_tools:
        return ToolRuntimeConfig(
            initial_tool_names=parent_tool_runtime_config.initial_tool_names,
            enable_retrieve_tools=False,
            include_subagents_in_retrieve=False,
        )
    return ToolRuntimeConfig(
        initial_tool_names=["vfs_read"],
        enable_retrieve_tools=True,
        include_subagents_in_retrieve=False,
    )


def build_executor_child_tool_runtime_config() -> ToolRuntimeConfig:
    """Build child tool runtime config for executor-spawned subagents."""
    return ToolRuntimeConfig(
        initial_tool_names=["vfs_read"],
        enable_retrieve_tools=True,
        include_subagents_in_retrieve=False,
    )
