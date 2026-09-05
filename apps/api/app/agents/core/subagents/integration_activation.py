"""Integration activation — pull an integration into the caller's own context.

`activate_integration(integration_id)` gives the caller everything the
integration's own subagent used to get at startup, without the second graph:
its tools registered AND the most-used ones bound in this same turn, its
operating prompt, which account the user is on it, their standing instructions,
and its skills. Execution stays with the caller — no worker graph, no handoff.
`spawn_subagent` inherits the bound tools when work needs isolating.

Binding in-turn is the point. Returning only prose would leave the caller to
spend a whole `retrieve_tools` round trip rediscovering tools the integration's
config already names.
"""

from typing import Annotated, Any, cast

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from app.agents.context.fetchers import build_provider_metadata_block
from app.agents.core.subagents.handoff_tools import (
    _get_subagent_by_id,
    check_integration_connection,
)
from app.agents.core.subagents.provider_subagents import register_integration_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.core.subagents.subagent_helpers import build_subagent_system_prompt
from app.agents.skills.discovery import get_available_skills_text
from app.agents.tools.core.registry import get_tool_registry
from app.agents.workspace.system_docs import integration_skills_block
from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable
from app.models.subagent_models import Subagent
from app.services.integration_instructions_service import get_instructions
from shared.py.wide_events import log


def _requires_per_user_tokens(subagent: Subagent) -> bool:
    """Tools that live only in a per-user MCP session, never in the global
    registry — so activation can never make them bindable."""
    return bool(
        subagent.managed_by == "mcp" and subagent.mcp_config and subagent.mcp_config.requires_auth
    )


async def _activate_tools(subagent: Subagent) -> tuple[int, list[str]]:
    """Register the integration's tools; return (how many exist, which to bind now).

    The bind set is the integration's own ``auto_bind_tools`` + ``extra_initial_tools``
    — exactly what its subagent gets pre-bound at startup."""
    category_name = await register_integration_tools(subagent)
    tool_registry = await get_tool_registry()

    total = 0
    if category_name is not None:
        category = tool_registry.get_category(category_name)
        total = len(category.tools) if category else 0

    config = subagent.config
    wanted = [*(config.auto_bind_tools or []), *(config.extra_initial_tools or [])]
    # A name the registry does not hold cannot be bound, and passing it on would
    # only be silently dropped later — drop it here so the reported set is honest.
    bind = [name for name in dict.fromkeys(wanted) if tool_registry.get_tool_meta(name)]
    return total, bind


async def _activation_context(integration_id: str, user_id: str | None) -> str:
    """Best-effort enrichment prose for an activated integration.

    This is enrichment, not the tools. The tools are already registered and bound
    by the time this runs, so a transient store failure here must degrade to
    whatever sections were gathered rather than abort the activation — same
    contract as the context fetchers in app/agents/context/fetchers.py.
    """
    sections: list[str] = []
    try:
        static_prompt = await build_subagent_system_prompt(integration_id=integration_id)
        if static_prompt:
            sections.append(f"## {integration_id}: how it works\n{static_prompt}")

        if user_id:
            instructions = await get_instructions(user_id, integration_id)
            if instructions:
                sections.append(
                    f"## The user's standing instructions for {integration_id}\n{instructions}"
                )

            # Which account the caller is acting as. A provider subagent gets this
            # as its own context section; without it the executor operates an
            # integration without knowing whose inbox/repo/workspace it is in.
            identity = await build_provider_metadata_block(integration_id, user_id)
            if identity:
                sections.append(identity)

            agent_name = ""
            subagent = get_subagent_by_id(integration_id)
            if subagent:
                agent_name = subagent.config.agent_name
            skills = await get_available_skills_text(user_id, agent_name)
            if skills:
                sections.append(f"## {integration_id} skills available to read on demand\n{skills}")

        workspace_skills = integration_skills_block(integration_id)
        if workspace_skills:
            sections.append(workspace_skills)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Activation context enrichment failed; degrading to partial",
            integration=integration_id,
            error_type=type(e).__name__,
            error=str(e),
        )

    return "\n\n".join(sections)


def _handoff_redirect(integration_id: str) -> str:
    """Tell the model to run a per-user integration through handoff instead.

    Per-user MCP integrations (auth-required or custom) cannot be activated
    in-context; handoff runs them in their own per-user graph and returns the
    result. handoff stays bound under the flag for exactly this case.
    """
    return (
        f"'{integration_id}' is a per-user integration, so its tools cannot be activated "
        f"in-context. Delegate it with handoff(subagent_id='{integration_id}', task=...): that "
        "runs it in its own per-user graph and returns the result."
    )


def _reply(tool_call_id: str, text: str, bind: list[str] | None = None) -> Command[Any]:
    """The tool's result, plus any tools it bound in the same turn.

    ``selected_tool_ids`` has an append reducer, so listing names here adds them
    to what the model can call on its very next step — no discovery round trip.
    """
    update: dict[str, Any] = {"messages": [ToolMessage(content=text, tool_call_id=tool_call_id)]}
    if bind:
        update["selected_tool_ids"] = bind
    return Command(update=update)


@tool
async def activate_integration(
    integration_id: Annotated[str, "The ID of the integration to activate (e.g., 'gmail')."],
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command[Any]:
    """Load an integration's tools and expertise into this conversation.

    Binds its most-used tools immediately (no retrieve_tools needed for those),
    and returns how it works, which account you are acting as, the user's standing
    preferences, and its skills. Act on it yourself; `spawn_subagent` inherits it.
    """
    if not settings.ENABLE_INTEGRATION_ACTIVATION:
        return _reply(tool_call_id, "activate_integration is disabled.")

    # Repository-aware resolution: covers the static OAuth/builtin registry AND
    # user-created custom MCP integrations (a dict), which the manifest lists but
    # the registry alone does not know — same resolver handoff uses.
    resolved = await _get_subagent_by_id(integration_id)
    if resolved is None:
        log.set(activation={"integration": integration_id})
        log.warning(f"{LogTag.AGENT} Activation requested for unknown integration")
        return _reply(tool_call_id, f"Unknown integration '{integration_id}'.")

    configurable = cast(AgentConfigurable, config.get("configurable", {}))
    user_id = configurable.get("user_id")

    # Custom MCP (a dict, not a registry Subagent) and auth-required MCP both
    # issue their tools per user, so they never enter the global registry and
    # cannot be bound in-context. handoff builds their per-user graph — route
    # there instead of dead-ending.
    if isinstance(resolved, dict) or _requires_per_user_tokens(resolved):
        log.set(activation={"integration": integration_id, "routed_to_handoff": True})
        return _reply(tool_call_id, _handoff_redirect(integration_id))

    subagent = resolved

    # Registering an unconnected integration's tools would bind tools that fail at
    # call time with an auth error. `handoff` gates on this too — and the check is
    # what renders the connect card, so skipping it leaves the user with no button.
    if subagent.managed_by not in ("mcp", "internal") and user_id:
        connect_prompt = await check_integration_connection(integration_id, user_id)
        if connect_prompt:
            log.set(activation={"integration": integration_id, "connected": False})
            return _reply(tool_call_id, connect_prompt)

    tool_count, bind = await _activate_tools(subagent)
    context = await _activation_context(integration_id, user_id)
    log.set(
        activation={
            "integration": integration_id,
            "tool_count": tool_count,
            "bound_now": len(bind),
            "context_length": len(context),
        }
    )

    if bind:
        bound_line = (
            f"{len(bind)} of them are ALREADY BOUND and callable right now: "
            f"{', '.join(bind)}. Call those directly; only use retrieve_tools if you need "
            f"one of the other {max(tool_count - len(bind), 0)}."
        )
    else:
        bound_line = "Use retrieve_tools to bind the ones this task needs."
    header = (
        f"Integration '{integration_id}' is now active with {tool_count} tools. "
        f"{bound_line} Anything you spawn inherits them.\n\n"
    )
    return _reply(tool_call_id, header + (context or "(no additional context available)"), bind)


tools = [activate_integration]
