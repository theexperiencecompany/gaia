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

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Annotated

import httpx
from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from mcp.shared.exceptions import McpError
from mcp_use.client.exceptions import MCPError as McpUseError, OAuthAuthenticationError
from pydantic import BaseModel, ConfigDict

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
from app.agents.prompts.user_instructions_prompts import render_user_instructions
from app.agents.skills.discovery import get_available_skills_text
from app.agents.tools.core.registry import get_tool_registry
from app.agents.tools.core.retrieval import render_preload_block, split_startup_tools
from app.agents.workspace.system_docs import integration_skills_block
from app.constants.execute import ACTIVATE_INTEGRATION_TOOL_NAME
from app.constants.integrations import ConnectMode
from app.constants.log_tags import LogTag
from app.constants.mcp import CUSTOM_MCP_AGENT_NAME_PREFIX, MCP_PRELOAD_ALL_MAX
from app.db.repositories.integrations import integration_repository
from app.models.agent_models import AgentConfigurable, agent_configurable
from app.models.subagent_models import Subagent
from app.services.integrations.integration_accounts import get_account_record
from app.services.integrations.user_integrations import check_user_has_integration
from app.services.mcp.mcp_client import get_mcp_client
from app.services.mcp.mcp_errors import MCPAuthorizationRequiredError, StepUpAuthRequiredError
from app.services.user_instructions_service import get_instructions
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log

#: Tool call id prefix of the activations a spawn is started with (see preload_integrations).
PRELOAD_CALL_ID_PREFIX = "call_preload_"
#: The reply to activating an integration whose activation is still in this run's history.
ALREADY_ACTIVE_REPLY = (
    "'{integration_id}' is already active in this conversation. Its tool schemas, notes "
    "and accounts are in the earlier activate_integration result, its helpers are still "
    "bound, and retrieve_tools still searches it: use those. Activating it again loads "
    "nothing new, so it will not fix a failing tool call or connect another account."
)


class ActivationRecord(BaseModel):
    """Marks a reply that loaded an integration, so a later call can tell it is still loaded.

    Stored as the reply's artifact in plain form, so the checkpoint keeps it; any
    other artifact parses to activated_integration=None.
    """

    model_config = ConfigDict(extra="ignore")

    activated_integration: str | None = None


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
    """What activation made available; preload_capped marks an MCP server too large to preload."""

    total: int
    bind: list[str]
    preload: list[str]
    docs: str
    preload_capped: bool = False


def _display_name(target: Subagent | CustomMcpSubagent) -> str:
    if isinstance(target, CustomMcpSubagent):
        return target.name or target.id
    return target.name


def _available_startup_tools(
    subagent: Subagent, available: Callable[[str], bool], dropped_message: str
) -> list[str]:
    """Return the subagent's declared startup tools that are available, warning with the rest."""
    config = subagent.config
    declared = dict.fromkeys([*(config.auto_bind_tools or []), *(config.extra_initial_tools or [])])
    kept = [name for name in declared if available(name)]
    if dropped := [name for name in declared if not available(name)]:
        log.warning(dropped_message, integration=subagent.id, dropped_tools=dropped)
    return kept


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

    # A name the registry does not hold cannot be bound, and passing it on would
    # only be silently dropped later — drop it here so the reported set is honest.
    known = _available_startup_tools(
        subagent,
        lambda name: tool_registry.get_tool_meta(name) is not None,
        f"{LogTag.AGENT} Activation dropped unregistered startup tools",
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
    return _available_startup_tools(
        target,
        exposed.__contains__,
        f"{LogTag.AGENT} Activation dropped startup tools the MCP server does not expose",
    )


async def _activate_mcp_tools(user_id: str, target: Subagent | CustomMcpSubagent) -> ActivatedTools:
    """Connect a per-user MCP server and preload its schemas; its tools always run via execute."""
    tools = await (await get_mcp_client(user_id)).ensure_connected(target.id)
    preload = _mcp_preload_names(target, tools)
    docs = await _render_preload(target.id, user_id, preload)
    # `>=` is equivalent: at len == MAX every tool is preloaded, so `not preload` is False.
    over_cap = len(tools) > MCP_PRELOAD_ALL_MAX  # pragma: no mutate
    return ActivatedTools(
        total=len(tools),
        bind=[],
        preload=preload,
        docs=docs,
        preload_capped=over_cap and not preload,
    )


async def _mcp_failure_text(
    target: Subagent | CustomMcpSubagent, user_id: str, error: Exception
) -> str:
    """Log a failed MCP connect and say what the model should do; auth failures show the connect card."""
    auth_failed = isinstance(error, _MCP_AUTH_ERRORS)
    log.set_ns("activation", error_type=type(error).__name__)
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


async def _overview_section(target: Subagent | CustomMcpSubagent) -> str:
    """Return a custom MCP's own description, or a platform integration's reframed operating notes."""
    if isinstance(target, CustomMcpSubagent):
        doc = await integration_repository.get(target.id)
        if not (doc and doc.description):
            return ""
        return f"## {_display_name(target)}: what it is\n{doc.description}"
    notes = target.config.system_prompt
    if not notes:
        return ""
    return f"## {target.id}: how it works\n{notes}"


def _agent_name(target: Subagent | CustomMcpSubagent) -> str:
    if isinstance(target, CustomMcpSubagent):
        return f"{CUSTOM_MCP_AGENT_NAME_PREFIX}{target.id}"
    return target.config.agent_name


async def _context_sections(
    target: Subagent | CustomMcpSubagent, user_id: str | None, several_accounts: bool
) -> AsyncIterator[str]:
    """Yield each enrichment section in reply order; an empty string means the section has nothing."""
    yield await _overview_section(target)
    if user_id:
        instructions = await get_instructions(user_id, target.id)
        if instructions:
            yield render_user_instructions(target.id, instructions)
        # Several accounts can change mid-conversation, so those are read from
        # the per-turn manifest instead of copied here.
        if several_accounts:
            yield ACTIVATION_MULTI_ACCOUNT_POINTER.format(integration=_display_name(target))
        else:
            yield await build_provider_metadata_block(target.id, user_id)
        skills = await get_available_skills_text(user_id, _agent_name(target))
        if skills:
            yield f"## {target.id} skills available to read on demand\n{skills}"
    yield integration_skills_block(target.id)


async def _activation_context(
    target: Subagent | CustomMcpSubagent, user_id: str | None, several_accounts: bool
) -> str:
    """Best-effort enrichment prose; a store failure keeps the sections gathered so far.

    The tools are already registered and bound by the time this runs, so a
    transient failure here must not abort the activation.
    """
    sections: list[str] = []
    try:
        async for section in _context_sections(target, user_id, several_accounts):
            if section:
                sections.append(section)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Activation context enrichment failed; degrading to partial",
            integration=target.id,
            error_type=type(e).__name__,
            error=str(e),
        )
    return "\n\n".join(sections)


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


def _activation_header(integration_id: str, activated: ActivatedTools, stamped: bool) -> str:
    """Build the activation reply's leading section; tool schemas stay last, never interleaved."""
    tool_count, bind, preloaded = activated.total, activated.bind, activated.preload
    header_parts = [f"Integration '{integration_id}' is now active with {tool_count} tools."]
    if bind:
        header_parts.append(
            f"{len(bind)} helper tool(s) are ALREADY BOUND and callable right now: "
            f"{', '.join(bind)}. Call those directly."
        )
    if preloaded and activated.docs:
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
        elif activated.preload_capped and stamped:
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


async def _connect_and_activate(
    target: Subagent | CustomMcpSubagent, user_id: str | None
) -> ActivatedTools | str:
    """Activate target's tools, or return the reply text when it cannot be activated."""
    if isinstance(target, CustomMcpSubagent) or is_per_user_mcp(target):
        # The server issues these tools per user: they never enter the global
        # registry, so they are connected in the user's MCP client and run via execute.
        if not user_id:
            return f"'{target.id}' needs a signed-in user, so it cannot be activated in this run."
        # A custom MCP is private to whoever added it: anyone else gets the same
        # answer as for an id that does not exist, so ids cannot be probed.
        if isinstance(target, CustomMcpSubagent) and not await check_user_has_integration(
            user_id, target.id
        ):
            return f"Unknown integration '{target.id}'."
        if connect_prompt := await check_mcp_connection(target.id, user_id):
            return connect_prompt
        try:
            return await _activate_mcp_tools(user_id, target)
        except _MCP_ACTIVATION_ERRORS as e:
            return await _mcp_failure_text(target, user_id, e)
    # Registering an unconnected integration's tools would bind tools that fail at
    # call time with an auth error, and the check is what renders the connect card.
    if target.managed_by not in ("mcp", "internal") and user_id:
        if connect_prompt := await check_integration_connection(target.id, user_id):
            return connect_prompt
    return await _activate_tools(target, user_id)


def _still_active(messages: Sequence[AnyMessage], integration_id: str) -> bool:
    """Whether a reply that loaded integration_id is still in the run's history.

    The executor's thread outlives a turn, so a follow-up request still sees the
    earlier activation. Whatever drops that reply (summarization, a tracked-todo
    run's thread reset) drops the evidence with it, and the next call reloads.
    """
    return any(
        isinstance(message, ToolMessage)
        and message.name == ACTIVATE_INTEGRATION_TOOL_NAME
        and isinstance(message.artifact, dict)
        and ActivationRecord.model_validate(message.artifact).activated_integration
        == integration_id
        for message in messages
    )


@dataclass(frozen=True)
class IntegrationLoad:
    """What activating one integration produced: the reply text, the tools it binds, its marker."""

    text: str
    bind: list[str] = field(default_factory=list)
    #: Set only when the integration loaded, so a later call can tell it is still active.
    record: ActivationRecord | None = None

    def reply(self, tool_call_id: str) -> ToolMessage:
        """Build the activate_integration reply carrying this load, marked when it loaded."""
        return ToolMessage(
            content=self.text,
            tool_call_id=tool_call_id,
            name=ACTIVATE_INTEGRATION_TOOL_NAME,
            artifact=self.record.model_dump() if self.record else None,
        )


def _reply(tool_call_id: str, loaded: IntegrationLoad) -> Command[str]:
    """Build the tool's result, binding any tools it names in the same turn.

    selected_tool_ids has an append reducer, so listing names here adds them to
    what the model can call on its very next step — no discovery round trip.
    """
    update: dict[str, object] = {"messages": [loaded.reply(tool_call_id)]}
    if loaded.bind:
        update["selected_tool_ids"] = loaded.bind
    return Command(update=update)


async def load_integration(
    integration_id: str, configurable: AgentConfigurable, history: Sequence[AnyMessage]
) -> IntegrationLoad:
    """Activate integration_id for the run configurable describes, given that run's history so far."""
    user_id = configurable.get("user_id")

    # Covers the static OAuth/builtin registry AND the user's custom MCP
    # integrations, which the manifest lists but the registry alone does not know.
    target = await get_integration_target(integration_id)
    if target is None:
        log.set(activation={"integration": integration_id})
        log.warning(f"{LogTag.AGENT} Activation requested for unknown integration")
        return IntegrationLoad(text=f"Unknown integration '{integration_id}'.")

    if _still_active(history, target.id):
        log.set(activation={"integration": target.id, "already_active": True})
        return IntegrationLoad(text=ALREADY_ACTIVE_REPLY.format(integration_id=target.id))

    activated = await _connect_and_activate(target, user_id)
    if isinstance(activated, str):
        log.set(activation={"integration": target.id, "connected": False})
        return IntegrationLoad(text=activated)

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

    body = _activation_header(target.id, activated, stamped) + (
        context or "(no additional context available)"
    )
    if activated.docs:
        body += "\n\n" + activated.docs
    return IntegrationLoad(
        text=body,
        bind=activated.bind,
        record=ActivationRecord(activated_integration=target.id),
    )


@tool
async def activate_integration(
    integration_id: Annotated[str, "The ID of the integration to activate (e.g., 'gmail')."],
    config: RunnableConfig,
    tool_call_id: Annotated[str, InjectedToolCallId],
    messages: Annotated[list[AnyMessage], InjectedState("messages")],
) -> Command[str]:
    """Load an integration's tools and expertise into this conversation.

    Preloads its most-used integration tools as schema docs (run them via
    ``execute`` — no retrieve_tools needed for those), binds its most-used
    helper tools immediately, and returns how it works, which account you are
    acting as, the user's standing preferences, and its skills. Act on it
    yourself, or pass its id to spawn_subagent's integration_ids.
    """
    loaded = await load_integration(integration_id, agent_configurable(config), messages)
    return _reply(tool_call_id, loaded)


@dataclass(frozen=True)
class PreloadedIntegrations:
    """Integrations activated for a spawn before it starts: its opening history and the tools bound."""

    messages: list[AnyMessage]
    bind: list[str]


async def preload_integrations(
    integration_ids: Sequence[str], configurable: AgentConfigurable
) -> PreloadedIntegrations:
    """Activate each integration once, rendered as the spawn's own activate_integration call and reply.

    Written as a call and its result, the spawn reads them exactly as if it had
    activated them itself, and a later activate_integration of the same one sees
    them and answers that it is already active.
    """
    unique = list(dict.fromkeys(integration_ids))
    loads = await asyncio.gather(*(load_integration(i, configurable, []) for i in unique))
    messages: list[AnyMessage] = []
    bind: list[str] = []
    for index, integration_id in enumerate(unique):
        loaded = loads[index]
        call_id = f"{PRELOAD_CALL_ID_PREFIX}{index}"
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": ACTIVATE_INTEGRATION_TOOL_NAME,
                        "args": {"integration_id": integration_id},
                        "id": call_id,
                    }
                ],
            )
        )
        messages.append(loaded.reply(call_id))
        bind.extend(name for name in loaded.bind if name not in bind)
    return PreloadedIntegrations(messages=messages, bind=bind)


tools = [activate_integration]
