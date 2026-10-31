"""Integration activation — pull an integration into the caller's own context.

activate_integration(integration_id) gives the caller everything the
integration's own subagent used to get at startup, without a second graph: its
tools registered (or, for a per-user MCP server, connected in the user's MCP
client) with the most-used ones preloaded or bound in this same turn, its
operating prompt, the active account, standing instructions, and its skills.
Execution stays with the caller; spawn_subagent inherits it when work needs
isolating.

Preloading in-turn is the point. Returning only prose would leave the caller to
spend a whole retrieve_tools round trip rediscovering tools the config names.
"""

from dataclasses import dataclass
from typing import Annotated

import httpx
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.types import Command
from mcp.shared.exceptions import McpError
from mcp_use.client.exceptions import MCPError as McpUseError, OAuthAuthenticationError

from app.agents.context.fetchers import build_provider_metadata_block
from app.agents.context.text import ACTIVATION_MULTI_ACCOUNT_POINTER
from app.agents.core.subagents.active_integrations import mark_active
from app.agents.core.subagents.integration_resolution import (
    CustomMcpSubagent,
    check_integration_connection,
    check_mcp_connection,
    get_integration_target,
    is_per_user_mcp,
)
from app.agents.core.subagents.provider_subagents import register_integration_tools
from app.agents.core.subagents.subagent_helpers import build_subagent_system_prompt
from app.agents.prompts.user_instructions_prompts import render_user_instructions
from app.agents.skills.discovery import get_available_skills_text
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import render_preload_block, split_startup_tools
from app.agents.workspace.system_docs import integration_skills_block
from app.constants.integrations import ConnectMode
from app.constants.log_tags import LogTag
from app.constants.mcp import CUSTOM_MCP_AGENT_NAME_PREFIX, MCP_PRELOAD_ALL_MAX
from app.db.repositories.integrations import integration_repository
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.subagent_models import Subagent
from app.services.integrations.integration_accounts import get_account_record
from app.services.mcp.mcp_client import (
    MCPAuthorizationRequiredError,
    StepUpAuthRequiredError,
    get_mcp_client,
)
from app.services.user_instructions_service import get_instructions
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log

# The server refused our credential: the user has to sign in again.
_MCP_AUTH_ERRORS: tuple[type[Exception], ...] = (
    MCPAuthorizationRequiredError,
    StepUpAuthRequiredError,
    OAuthAuthenticationError,
)
# What MCPClient.ensure_connected / connect raise when the server cannot be
# reached or its session cannot be opened (ValueError: not connected in the DB,
# integration not found, refused URL; RuntimeError: no session after reconnect).
_MCP_CONNECT_ERRORS: tuple[type[Exception], ...] = (
    ValueError,
    RuntimeError,
    OSError,
    httpx.HTTPError,
    McpError,
    McpUseError,
)
_MCP_ACTIVATION_ERRORS = (*_MCP_AUTH_ERRORS, *_MCP_CONNECT_ERRORS)


@dataclass(frozen=True)
class ActivatedTools:
    """What activation made available: tool count, bound helpers, preloaded names, their docs."""

    total: int
    bind: list[str]
    preload: list[str]
    docs: str


def _display_name(target: Subagent | CustomMcpSubagent) -> str:
    if isinstance(target, CustomMcpSubagent):
        return target.name or target.id
    return target.name


async def _activate_tools(subagent: Subagent, user_id: str | None = None) -> ActivatedTools:
    """Register a registry-backed integration's tools and pick what to bind and preload.

    bind is auto_bind_tools + extra_initial_tools minus execute-routed tools;
    preload are integration tools held back from binding, documented in docs.
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
    docs = await _render_preload(subagent.id, user_id, preload)
    return ActivatedTools(total=total, bind=bind, preload=preload, docs=docs)


async def _render_preload(integration_id: str, user_id: str | None, preload: list[str]) -> str:
    docs = await render_preload_block(user_id, preload)
    if preload and not docs:
        log.warning(
            f"{LogTag.AGENT} Activation preloaded tools but rendered no docs",
            integration=integration_id,
            preloaded=preload,
        )
    return docs


def _mcp_preload_names(target: Subagent | CustomMcpSubagent, tools: list[BaseTool]) -> list[str]:
    """Every tool of a small server; above the cap a platform MCP's startup tools, a custom one's none."""
    names = [t.name for t in tools]
    if len(names) <= MCP_PRELOAD_ALL_MAX:
        return names
    if isinstance(target, CustomMcpSubagent):
        return []
    exposed = set(names)
    declared = list(
        dict.fromkeys(
            [*(target.config.auto_bind_tools or []), *(target.config.extra_initial_tools or [])]
        )
    )
    missing = [name for name in declared if name not in exposed]
    if missing:
        log.warning(
            f"{LogTag.AGENT} Activation dropped startup tools the MCP server does not expose",
            integration=target.id,
            dropped_tools=missing,
        )
    return [name for name in declared if name in exposed]


async def _activate_mcp_tools(user_id: str, target: Subagent | CustomMcpSubagent) -> ActivatedTools:
    """Connect a per-user MCP server and preload its schemas; its tools always run via execute."""
    tools = await (await get_mcp_client(user_id)).tools_for(target.id)
    preload = _mcp_preload_names(target, tools)
    docs = await _render_preload(target.id, user_id, preload)
    return ActivatedTools(total=len(tools), bind=[], preload=preload, docs=docs)


async def _mcp_failure_text(
    target: Subagent | CustomMcpSubagent, user_id: str, error: Exception
) -> str:
    """Log a failed MCP connect and say what the model should do; auth failures show the connect card."""
    auth_failed = isinstance(error, _MCP_AUTH_ERRORS)
    log.set(
        activation={
            "integration": target.id,
            "connected": False,
            "error_type": type(error).__name__,
        }
    )
    log.warning(
        f"{LogTag.AGENT} Activation could not connect the MCP server",
        integration=target.id,
        auth_failed=auth_failed,
        error_type=type(error).__name__,
        error=str(error),
    )
    name = _display_name(target)
    if auth_failed:
        return await request_integration_connection(
            target.id, name, user_id, mode=ConnectMode.RECONNECT
        )
    return (
        f"Could not connect to {name} ('{target.id}'): {error}. Its tools are unavailable "
        "right now — tell the user instead of retrying it in this turn."
    )


async def _has_several_accounts(integration_id: str, user_id: str | None) -> bool:
    """Whether the user connected more than one account to this integration."""
    if not user_id:
        return False
    try:
        record = await get_account_record(user_id, integration_id)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Activation could not read the integration's accounts",
            integration=integration_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False
    return record is not None and len(record.accounts) > 1


async def _activation_context(
    target: Subagent | CustomMcpSubagent, user_id: str | None, several_accounts: bool
) -> str:
    """Best-effort enrichment prose for an activated integration.

    This is enrichment, not the tools. The tools are already registered and bound
    by the time this runs, so a transient store failure here must degrade to
    whatever sections were gathered rather than abort the activation — same
    contract as the context fetchers in app/agents/context/fetchers.py.
    """
    integration_id = target.id
    integration_name = _display_name(target)
    sections: list[str] = []
    try:
        if isinstance(target, CustomMcpSubagent):
            agent_name = f"{CUSTOM_MCP_AGENT_NAME_PREFIX}{integration_id}"
            custom_doc = await integration_repository.get(integration_id)
            if custom_doc and custom_doc.description:
                sections.append(f"## {integration_name}: what it is\n{custom_doc.description}")
        else:
            agent_name = target.config.agent_name
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
                sections.append(render_user_instructions(integration_id, instructions))

            # Which account the caller is acting as. Several accounts can change
            # mid-conversation, so those are read from the per-turn manifest instead.
            if several_accounts:
                sections.append(
                    ACTIVATION_MULTI_ACCOUNT_POINTER.format(integration=integration_name)
                )
            else:
                identity = await build_provider_metadata_block(integration_id, user_id)
                if identity:
                    sections.append(identity)

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
    configurable: AgentConfigurable, integration_id: str, activated: ActivatedTools
) -> bool:
    """Stamp the conversation while the activation is known good; return whether the stamp landed."""
    # Later retrieve_tools discovery searches this namespace too, so the tools
    # beyond the preloaded subset stay reachable from this run.
    if not (activated.bind or activated.preload or activated.total):
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
    *,
    preload_capped: bool = False,
) -> str:
    """Build the activation reply's leading section; tool schemas stay last, never interleaved."""
    # Tool schemas live in exactly one place: the trailing schemas section
    # (render_preload_block, its own header), never interleaved with the context
    # sections.
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
        elif preload_capped and stamped:
            header_parts.append(
                f"It exposes more than {MCP_PRELOAD_ALL_MAX} tools, so none are preloaded — "
                "find the ones this task needs with retrieve_tools."
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

    # Covers the static OAuth/builtin registry AND the user's custom MCP
    # integrations, which the manifest lists but the registry alone does not know.
    target = await get_integration_target(integration_id)
    if target is None:
        log.set(activation={"integration": integration_id})
        log.warning(f"{LogTag.AGENT} Activation requested for unknown integration")
        return _reply(tool_call_id, f"Unknown integration '{integration_id}'.")

    preload_capped = False
    # The isinstance check narrows the else branch to Subagent for _activate_tools.
    if isinstance(target, CustomMcpSubagent) or is_per_user_mcp(target):
        # The server issues these tools per user: they never enter the global
        # registry, so they are connected in the user's MCP client and run via execute.
        if not user_id:
            log.set(activation={"integration": target.id, "connected": False})
            return _reply(
                tool_call_id,
                f"'{target.id}' needs a signed-in user, so it cannot be activated in this run.",
            )
        connect_prompt = await check_mcp_connection(target.id, user_id)
        if connect_prompt:
            log.set(activation={"integration": target.id, "connected": False})
            return _reply(tool_call_id, connect_prompt)
        try:
            activated = await _activate_mcp_tools(user_id, target)
        except _MCP_ACTIVATION_ERRORS as e:
            return _reply(tool_call_id, await _mcp_failure_text(target, user_id, e))
        preload_capped = activated.total > MCP_PRELOAD_ALL_MAX and not activated.preload
    else:
        # Registering an unconnected integration's tools would bind tools that fail
        # at call time with an auth error, and the check is what renders the
        # connect card, so skipping it leaves the user with no button.
        if target.managed_by not in ("mcp", "internal") and user_id:
            connect_prompt = await check_integration_connection(target.id, user_id)
            if connect_prompt:
                log.set(activation={"integration": target.id, "connected": False})
                return _reply(tool_call_id, connect_prompt)
        activated = await _activate_tools(target, user_id)

    several_accounts = await _has_several_accounts(target.id, user_id)
    context = await _activation_context(target, user_id, several_accounts)
    log.set(
        activation={
            "integration": target.id,
            "tool_count": activated.total,
            "bound_now": len(activated.bind),
            "preloaded": len(activated.preload),
            "context_length": len(context),
        }
    )

    stamped = await _stamp_activation(configurable, target.id, activated)

    header = _activation_header(
        target.id,
        activated.total,
        activated.bind,
        activated.preload,
        activated.docs,
        stamped,
        preload_capped=preload_capped,
    )
    body = header + (context or "(no additional context available)")
    if activated.docs:
        body += "\n\n" + activated.docs
    return _reply(tool_call_id, body, activated.bind)


tools = [activate_integration]
