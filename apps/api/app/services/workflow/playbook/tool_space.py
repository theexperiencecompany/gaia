"""Resolve the tools a playbook step is allowed to name.

A playbook's top-level steps run against the executor's registry, but a
handoff's children run inside that subagent's own space, and for an MCP
integration that space lives on the USER's ``MCPClient`` rather than in the
global registry. PostHog is the case that proved it: the tools its subagent
exposes are fetched per user at connect time, so a recorded ``exec`` step is
absent from the registry entirely.

The validator and the replay runner both have to resolve a handoff the same
way. When they disagree the failure is silent and one-sided: a playbook is
either refused for naming a tool that genuinely exists, or accepted and then
replayed against a tool space that never had it.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.agents.core.subagents.base_subagent import build_scoped_tool_dict
from app.agents.core.subagents.provider_subagents import register_composio_subagent_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import ToolRegistry
from app.agents.tools.core.tool_runtime_config import (
    ToolRuntimeConfig,
    build_provider_parent_tool_runtime_config,
)
from app.constants.log_tags import LogTag
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log


@dataclass(frozen=True, slots=True)
class ToolSpace:
    """Where a step's tool is looked up, and what that scope allows.

    Top level is the full registry with no runtime: anything in it may run.
    Inside a handoff it is the subagent's scoped tool set AND its runtime
    config, the boundary a delegated call already had. The scoped dict holds
    more than the subagent can bind (the always-available ``search_memory``,
    ``grep``, ``query_json``...), so "in the space" is not "runnable";
    ``tool_space_denial`` is the one answer to that question, for the validator
    at write time and the runner at replay.
    """

    tools: Mapping[str, BaseTool]
    runtime: ToolRuntimeConfig | None
    subagent_id: str | None


class SubagentTools:
    """One subagent's tools, the ids it binds at startup, and the subagent itself.

    The subagent travels with its tools so a caller never repeats the registry
    lookup: two lookups is two chances to disagree about whether a handoff
    target exists.
    """

    def __init__(
        self,
        tools: dict[str, BaseTool],
        initial_tool_ids: list[str],
        subagent: Subagent | None = None,
    ) -> None:
        self.tools = tools
        self.initial_tool_ids = initial_tool_ids
        self.subagent: Subagent | None = subagent


def handoff_tool_space(space: SubagentTools) -> ToolSpace:
    """The space a handoff's children run in, built from the resolved subagent.

    One construction for both sides: the validator building the runtime config
    one way and the runner another is exactly how a playbook is accepted at
    write time and refused at replay.
    """
    subagent = space.subagent
    if subagent is None:
        return ToolSpace(tools=space.tools, runtime=None, subagent_id=None)
    config = subagent.config
    runtime = build_provider_parent_tool_runtime_config(
        provider_tool_names=space.initial_tool_ids,
        todo_tool_names=[],
        auto_bind_tool_names=config.auto_bind_tools,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
        include_finish_task=config.include_finish_task,
    )
    return ToolSpace(tools=space.tools, runtime=runtime, subagent_id=subagent.id)


def tool_space_denial(tool_name: str, space: ToolSpace) -> str | None:
    """Why this space may not run ``tool_name``, or ``None`` when it may."""
    if tool_name not in space.tools:
        if space.subagent_id is None:
            return f"no tool named {tool_name!r} exists"
        return f"no tool named {tool_name!r} is available in this run's tool space"
    runtime = space.runtime
    if (
        runtime is not None
        and not runtime.enable_retrieve_tools
        and tool_name not in runtime.initial_tool_names
    ):
        return f"{tool_name} is outside the bound tool set of this handoff, which cannot retrieve"
    return None


async def resolve_subagent_tools(
    subagent_id: str, user_id: str, registry: ToolRegistry
) -> SubagentTools | None:
    """The tools a handoff to ``subagent_id`` can reach, or ``None`` if no such subagent.

    An MCP integration's tools are fetched from the user's own client, which is
    the only place they exist. A connection failure returns an empty tool set
    rather than raising: the caller decides what that means, and neither
    authoring nor replay should die because an integration is briefly down.
    """
    subagent = get_subagent_by_id(subagent_id)
    if subagent is None:
        return None

    # A Composio toolkit reaches the registry only when something loads it. The
    # live handoff does so on demand; on a worker that has never handed off to
    # this subagent, resolving without it finds an empty category.
    if subagent.managed_by == "composio":
        await register_composio_subagent_tools(subagent, registry)

    config = subagent.config
    scoped, initial = build_scoped_tool_dict(
        tool_registry=registry,
        tool_space=config.tool_space,
        mcp_tools=None,
        include_finish_task=config.include_finish_task,
    )

    if subagent.mcp_config is None:
        return SubagentTools(tools=scoped, initial_tool_ids=initial, subagent=subagent)

    try:
        client = await get_mcp_client(user_id=user_id)
        mcp_tools = await client.ensure_connected(subagent.id)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Could not reach an integration's tools for a playbook",
            subagent_id=subagent.id,
            error_type=type(e).__name__,
        )
        return SubagentTools(tools={}, initial_tool_ids=initial, subagent=subagent)

    # The live subagent binds its MCP tools at startup (``build_scoped_tool_dict``
    # with ``mcp_tools`` set), so they belong in ``initial_tool_ids`` here too:
    # a handoff that cannot retrieve refuses every tool outside that set, and a
    # replay bound to the registry-only ids would reject the very MCP step the
    # validator just accepted.
    bound = set(initial)
    return SubagentTools(
        tools={**scoped, **{tool.name: tool for tool in mcp_tools}},
        initial_tool_ids=[*initial, *[tool.name for tool in mcp_tools if tool.name not in bound]],
        subagent=subagent,
    )
