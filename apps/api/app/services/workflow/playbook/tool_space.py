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

from langchain_core.tools import BaseTool

from app.agents.core.subagents.base_subagent import build_scoped_tool_dict
from app.agents.core.subagents.provider_subagents import register_composio_subagent_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.tools.core.registry import ToolRegistry
from app.constants.log_tags import LogTag
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log


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

    return SubagentTools(
        tools={**scoped, **{tool.name: tool for tool in mcp_tools}},
        initial_tool_ids=initial,
        subagent=subagent,
    )
