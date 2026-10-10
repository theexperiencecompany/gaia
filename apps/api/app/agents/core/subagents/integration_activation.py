"""Integration activation — pull an integration into the caller's own context.

activate_integration(integration_id) gives the caller everything the
integration's own subagent used to get at startup, without the second graph: its
tools registered AND the most-used ones bound in this same turn, its operating
prompt, the active account, standing instructions, and its skills. Execution
stays with the caller — no worker graph, no handoff; spawn_subagent inherits the
bound tools when work needs isolating.

Binding in-turn is the point. Returning only prose would leave the caller to
spend a whole retrieve_tools round trip rediscovering tools the config names.
"""

from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from app.agents.context.fetchers import build_provider_metadata_block
from app.agents.core.subagents.active_integrations import mark_active
from app.agents.core.subagents.handoff_tools import (
    CustomMcpSubagent,
    _get_subagent_by_id,
    check_integration_connection,
)
from app.agents.core.subagents.provider_subagents import register_integration_tools
from app.agents.core.subagents.registry import get_subagent_by_id
from app.agents.core.subagents.subagent_helpers import build_subagent_system_prompt
from app.agents.skills.discovery import get_available_skills_text
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import render_preload_block, split_startup_tools
from app.agents.workspace.system_docs import integration_skills_block
from app.constants.log_tags import LogTag
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.subagent_models import Subagent
from app.services.integration_instructions_service import get_instructions
from shared.py.wide_events import log


def _requires_per_user_tokens(subagent: Subagent) -> bool:
    """Whether the subagent's tools live only in a per-user MCP session, never bindable."""
    return bool(
        subagent.managed_by == "mcp" and subagent.mcp_config and subagent.mcp_config.requires_auth
    )


async def _activate_tools(
    subagent: Subagent, user_id: str | None = None
) -> tuple[int, list[str], list[str], str]:
    """Register the integration's tools; return (total, bind, preloaded, docs).

    bind is auto_bind_tools + extra_initial_tools minus execute-routed tools;
    preloaded are integration tools held back from binding, with their schema docs
    in docs for the reply (run via execute). docs is "" when nothing preloaded or
    rendered; names that render no docs are reported, not silently kept.
    """
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
    known = [name for name in dict.fromkeys(wanted) if tool_registry.get_tool_meta(name)]
    dropped = [name for name in dict.fromkeys(wanted) if not tool_registry.get_tool_meta(name)]
    if dropped:
        log.warning(
            f"{LogTag.AGENT} Activation dropped unregistered startup tools",
            integration=subagent.id,
            dropped_tools=dropped,
        )
    bind, preload = await split_startup_tools(user_id, known)
    docs = await render_preload_block(user_id, preload)
    if preload and not docs:
        log.warning(
            f"{LogTag.AGENT} Activation preloaded tools but rendered no docs",
            integration=subagent.id,
            preloaded=preload,
        )
    return total, bind, preload, docs


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
            # The notes were written for this integration's worker graph, so left
            # bare they misidentify the reader; reframe them for the actual reader,
            # the executor acting with these tools in its own turn.
            sections.append(
                f"## {integration_id}: how it works\n"
                "The notes below describe this integration's tools, conventions, "
                "and standing rules — follow those. They were written for a "
                "delegated worker, which you are not: you are the executor, "
                "acting on this integration yourself in your own turn. IGNORE "
                "any instruction about receiving a delegated task, reporting "
                "to a parent, or calling finish_task (never call it — reply "
                "normally when the work is done).\n"
                f"{static_prompt}"
            )

        if user_id:
            instructions = await get_instructions(user_id, integration_id)
            if instructions:
                sections.append(
                    f"## The user's standing instructions for {integration_id}\n{instructions}"
                )

            # Which account the caller is acting as. An MCP worker gets this
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


def _reply(tool_call_id: str, text: str, bind: list[str] | None = None) -> Command[str]:
    """Build the tool's result, binding any tools it names in the same turn.

    selected_tool_ids has an append reducer, so listing names here adds them to
    what the model can call on its very next step — no discovery round trip.
    """
    update: dict[str, object] = {"messages": [ToolMessage(content=text, tool_call_id=tool_call_id)]}
    if bind:
        update["selected_tool_ids"] = bind
    return Command(update=update)


async def _stamp_activation(
    configurable: AgentConfigurable,
    integration_id: str,
    bind: list[str],
    preloaded: list[str],
    tool_count: int,
) -> bool:
    """Stamp the conversation while the activation is known good; return whether the stamp landed."""
    # Later retrieve_tools discovery searches this namespace too, so the tools
    # beyond the preloaded subset stay reachable from this run.
    if not (bind or preloaded or tool_count):
        # The header reads stamped only when one of these is non-empty.
        return False  # pragma: no mutate
    conversation_id = configurable.get("conversation_id")
    if not conversation_id:
        log.warning(
            f"{LogTag.AGENT} Activation stamp skipped: no conversation_id",
            integration=integration_id,
        )
        return False
    await mark_active(conversation_id, integration_id)
    return True


def _activation_header(
    integration_id: str,
    tool_count: int,
    bind: list[str],
    preloaded: list[str],
    docs: str,
    stamped: bool,
) -> str:
    """Build the activation reply's leading section; tool schemas stay last, never interleaved."""
    # Tool schemas live in exactly one place: the trailing schemas section
    # (render_preload_block, its own header) — the same last-position rule as
    # handoff seeding. Never interleaved with the context sections.
    header_parts = [f"Integration '{integration_id}' is now active with {tool_count} tools."]
    if bind:
        header_parts.append(
            f"{len(bind)} helper tool(s) are ALREADY BOUND and callable right now: "
            f"{', '.join(bind)}. Call those directly."
        )
    if preloaded and docs:
        # The "searches X too" promise holds only when the stamp landed: without
        # it query-mode discovery never enters this namespace (exact names still
        # validate, so name them explicitly instead of searching).
        search_guidance = (
            f"retrieve_tools searches {integration_id} too, so use it if you need "
            f"one of the other {max(tool_count - len(bind) - len(preloaded), 0)}."
            if stamped
            else "retrieve_tools query search does not cover this integration in "
            "this run — pass exact tool names from the schemas above instead of "
            "searching for them."
        )
        header_parts.append(
            f"{len(preloaded)} integration tool(s) are preloaded in the schemas section "
            "at the end of this message — NOT bound, do NOT call them by name. Run them "
            'with execute(task_description="...", tool_name="<NAME>", data={...}) '
            f"built from those schemas. {search_guidance}"
        )
    elif not bind:
        # Nothing registered (total == 0): pointing at retrieve_tools would chase
        # tools that do not exist, and the namespace is not query-searchable
        # without a stamp — say which retrieve path works instead.
        if not tool_count and not preloaded:
            header_parts.append(
                "It registered no tools of its own — everything it offers is in "
                "the context above. Use retrieve_tools only for unrelated needs."
            )
        elif stamped:
            header_parts.append("Use retrieve_tools to bind the ones this task needs.")
        else:
            header_parts.append(
                "Use retrieve_tools with exact tool names to bind the ones this "
                "task needs — query search does not cover this integration in "
                "this run."
            )
    header_parts.append("Anything you spawn inherits the bound tools.")
    return " ".join(header_parts) + "\n\n"


@tool
async def activate_integration(
    integration_id: Annotated[str, "The ID of the integration to activate (e.g., 'gmail')."],
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command[str]:
    """Load an integration's tools and expertise into this conversation.

    Preloads its most-used integration tools as schema docs (run them via
    ``execute`` — no retrieve_tools needed for those), binds its most-used
    helper tools immediately, and returns how it works, which account you are
    acting as, the user's standing preferences, and its skills. Act on it
    yourself; `spawn_subagent` inherits it.
    """
    configurable: AgentConfigurable = agent_configurable(config)
    user_id = configurable.get("user_id")

    # Repository-aware resolution: covers the static OAuth/builtin registry AND
    # user-created custom MCP integrations (a dict), which the manifest lists but
    # the registry alone does not know — same resolver handoff uses.
    resolved = await _get_subagent_by_id(integration_id)
    if resolved is None:
        log.set(activation={"integration": integration_id})
        log.warning(f"{LogTag.AGENT} Activation requested for unknown integration")
        return _reply(tool_call_id, f"Unknown integration '{integration_id}'.")

    # Custom MCP and auth-required MCP issue their tools per user, so they never
    # enter the global registry and cannot be bound in-context; route to handoff,
    # which builds their per-user graph, instead of dead-ending.
    if isinstance(resolved, CustomMcpSubagent) or _requires_per_user_tokens(resolved):
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

    tool_count, bind, preloaded, docs = await _activate_tools(subagent, user_id)
    context = await _activation_context(integration_id, user_id)
    log.set(
        activation={
            "integration": integration_id,
            "tool_count": tool_count,
            "bound_now": len(bind),
            "preloaded": len(preloaded),
            "context_length": len(context),
        }
    )

    stamped = await _stamp_activation(configurable, integration_id, bind, preloaded, tool_count)

    header = _activation_header(integration_id, tool_count, bind, preloaded, docs, stamped)
    body = header + (context or "(no additional context available)")
    if docs:
        body += "\n\n" + docs
    return _reply(tool_call_id, body, bind)


tools = [activate_integration]
