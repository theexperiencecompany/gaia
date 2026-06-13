"""Shared tool runtime configuration for agent and child-agent execution."""

from dataclasses import dataclass, field
from typing import Any

from app.agents.tools.core.retrieval import get_retrieve_tools_function
from app.constants.general import FINISH_TASK_NAME


@dataclass(slots=True)
class ToolRuntimeConfig:
    """Tool runtime behavior shared by parent and spawned child execution.

    - `initial_tool_names`: regular tools bound immediately (e.g. read, bash)
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
    include_finish_task: bool = True,
) -> ToolRuntimeConfig:
    """Build parent provider-agent tool runtime config."""
    finish = [FINISH_TASK_NAME] if include_finish_task else []
    # When `use_direct_tools=True`, `provider_tool_names` already contains every
    # tool in the subagent's tool_space, so any overlap with `auto_bind_tool_names`
    # would duplicate entries in `initial`. Filter the auto-bind list against
    # the provider tools to keep `initial` deduplicated.
    provider_tool_set = set(provider_tool_names)
    extra_auto_bind = [
        name for name in (auto_bind_tool_names or []) if name not in provider_tool_set
    ]
    if use_direct_tools:
        initial = [
            *provider_tool_names,
            *extra_auto_bind,
            *todo_tool_names,
            *finish,
            "read",
            "bash",
        ]
    else:
        initial = [
            "search_memory",
            "read",
            "bash",
            *finish,
            *todo_tool_names,
            *extra_auto_bind,
        ]

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
        initial_tool_names=["read", "bash", FINISH_TASK_NAME],
        enable_retrieve_tools=not disable_retrieve_tools,
        include_subagents_in_retrieve=False,
    )


def build_executor_child_tool_runtime_config() -> ToolRuntimeConfig:
    """Build child tool runtime config for executor-spawned subagents."""
    return ToolRuntimeConfig(
        initial_tool_names=["read", "bash", FINISH_TASK_NAME],
        enable_retrieve_tools=True,
        include_subagents_in_retrieve=False,
    )
