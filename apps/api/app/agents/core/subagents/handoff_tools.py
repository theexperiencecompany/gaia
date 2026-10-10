"""Subagent tools — per-user MCP delegation.

The handoff tool delegates ONLY to per-user MCP integrations (custom/auth-required
MCP) that run in their own per-user graph. Provider and built-in integrations
activate in-context instead and are redirected at resolve time. Subagent
identity/metadata comes from agents/core/subagents/registry.py.
"""

from dataclasses import dataclass
import re
from typing import Annotated

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.errors import GraphBubbleUp
from langgraph.store.base import BaseStore, PutOp
from pydantic import BaseModel, ConfigDict

from app.agents.context.tiers import AgentTier
from app.agents.core.graph_manager import CompiledAgentGraph
from app.agents.core.subagents.delegation import Delegation, SubagentDisplay, delegate
from app.agents.core.subagents.provider_subagents import (
    SubagentUnavailableError,
    create_subagent_for_user,
)
from app.agents.core.subagents.registry import (
    all_subagents,
    foreign_provider_named_in,
    get_subagent_by_id,
)
from app.agents.core.subagents.subagent_helpers import (
    create_subagent_system_message,
)
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    ThreadSeed,
    build_initial_messages,
    subagent_row_id,
)
from app.agents.tools.core.retrieval import preloaded_startup_docs
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.helpers.agent_helpers import AgentIdentity, AgentThread, build_agent_config
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.agent_models import (
    AgentConfigurable,
    AgentUserContext,
    SubagentKind,
    agent_configurable,
)
from app.models.subagent_models import Subagent
from app.services.hil.approvals_store import list_parked_subagents_for_conversation
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import check_integration_status
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.agent_utils import IntegrationMetadata, parse_subagent_id
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log

SUBAGENTS_NAMESPACE = ("subagents",)


@dataclass(frozen=True)
class CustomMcpIndexRequest:
    """The custom-MCP identity/description cluster indexed for handoff discovery.

    Args:
        integration_id: Unique ID of the custom integration (12-char hex)
        name: Display name of the integration
        description: Description of what the integration does
        server_url: MCP server URL for namespace derivation
        tools: The MCP's tools — their names/summaries are embedded so the
            subagent ranks for what it can actually do (e.g. a "get_meetings"
            tool surfaces on a "meetings" query) instead of generic boilerplate.
    """

    integration_id: str
    name: str
    description: str
    server_url: str | None = None
    tools: list[BaseTool] | None = None


class CustomMcpSubagent(BaseModel):
    """A custom MCP resolved as a handoff target, as cached under ``SUBAGENT_CACHE_PREFIX``.

    Fields default because the cache holds whatever an earlier resolution wrote;
    ``_resolve_custom_mcp_subagent`` refuses one with no ``id``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str | None = None
    source: str | None = None
    managed_by: str | None = None
    mcp_config: dict[str, object] | None = None
    icon_url: str | None = None
    subagent_config: None = None


class _CustomIntegrationDoc(BaseModel):
    """The ``IntegrationResolver.custom_doc`` keys a custom-MCP handoff target copies.

    ``mcp_config`` stays the stored mapping: it is cached verbatim, never read here.
    """

    model_config = ConfigDict(extra="ignore")

    integration_id: str = ""
    name: str | None = None
    mcp_config: dict[str, object] | None = None
    icon_url: str | None = None


class _RunMetadata(BaseModel):
    """The ``metadata`` key of a ``RunnableConfig`` the handoff falls back on."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None


def _extract_service_username(metadata: dict[str, str] | None) -> str | None:
    if not metadata:
        return None
    for key in ("username", "login", "handle"):
        value = metadata.get(key)
        if value:
            return str(value)
    return None


def _sanitize_task_user_reference(
    task: str,
    gaia_name: str | None,
    provider_hint: str,
    service_username: str | None,
) -> str:
    if not gaia_name:
        return task

    lowered = task.lower()
    if provider_hint.lower() not in lowered:
        return task

    replacement = service_username or "authenticated user"
    patterns = [
        rf"(user\s*[:=]?\s*['\"]?)({re.escape(gaia_name)})(['\"]?)",
        rf"(username\s*[:=]?\s*['\"]?)({re.escape(gaia_name)})(['\"]?)",
        rf"(account\s*[:=]?\s*['\"]?)({re.escape(gaia_name)})(['\"]?)",
    ]

    updated = task
    for pattern in patterns:
        updated = re.sub(pattern, rf"\1{replacement}\3", updated, flags=re.IGNORECASE)
    return updated


async def check_integration_connection(
    integration_id: str,
    user_id: str,
) -> str | None:
    """Return the connect prompt when the integration isn't connected, else None.

    Lives here rather than in integration_checker: it needs check_integration_status
    from oauth_service, which reaches integration_checker through composio, so
    moving it down closes a real import cycle.
    """
    subagent = get_subagent_by_id(integration_id)
    if not subagent:
        return None

    if await check_integration_status(integration_id, user_id):
        return None

    return await request_integration_connection(subagent.id, subagent.name, user_id)


async def _get_subagent_by_id(subagent_id: str) -> Subagent | CustomMcpSubagent | None:
    """Get subagent by ID or short_name.

    Checks both platform/builtin subagents (via registry) and custom MCPs
    from MongoDB, with Redis caching for the latter.
    """
    search_id = subagent_id.lower().strip()

    # Check platform/builtin subagents first (no caching needed - in-memory)
    subagent = get_subagent_by_id(search_id)
    if subagent:
        return subagent

    # Check Redis cache for custom integrations
    cache_key = f"{SUBAGENT_CACHE_PREFIX}:{search_id}"
    cached = await get_cache(cache_key)
    if cached is not None:
        # Return cached result (could be empty dict for negative cache)
        return CustomMcpSubagent.model_validate(cached) if cached else None

    # Search by integration_id (case-insensitive) or exact name
    custom = await integration_repository.find_by_id_prefix_or_name(search_id)

    if custom:
        result = CustomMcpSubagent(
            id=custom.integration_id,
            name=custom.name,
            source=custom.source,
            managed_by=custom.managed_by,
            mcp_config=custom.mcp_config.model_dump() if custom.mcp_config else None,
            icon_url=custom.icon_url,
        )
        await set_cache(cache_key, result.model_dump(), ttl=SUBAGENT_CACHE_TTL)
        return result

    # Fallback: Try IntegrationResolver which checks multiple sources
    # This handles cases where integration is in user_integrations but not integrations

    resolved = await IntegrationResolver.resolve(search_id)
    if resolved and resolved.custom_doc:
        doc = _CustomIntegrationDoc.model_validate(resolved.custom_doc)
        result = CustomMcpSubagent(
            id=doc.integration_id,
            name=doc.name,
            source=resolved.source,
            managed_by="mcp",
            mcp_config=doc.mcp_config,
            icon_url=doc.icon_url,
        )
        await set_cache(cache_key, result.model_dump(), ttl=SUBAGENT_CACHE_TTL)
        return result

    # Cache negative result to avoid repeated DB queries
    await set_cache(cache_key, {}, ttl=SUBAGENT_CACHE_TTL)
    return None


async def index_custom_mcp_as_subagent(
    store: BaseStore,
    request: CustomMcpIndexRequest,
) -> None:
    """Index a custom MCP as a subagent for handoff discovery.

    Called when user connects a custom MCP to make it immediately available
    for semantic search and handoff.
    """
    integration_id = request.integration_id
    name = request.name
    description = request.description
    server_url = request.server_url
    tools = request.tools

    parts = [f"{name}."]
    if description:
        parts.append(f"{description}.")
    if tools:
        summaries = []
        for t in tools:
            first_line = (t.description or "").strip().splitlines()
            summary = first_line[0][:120] if first_line else ""
            summaries.append(f"{t.name}: {summary}" if summary else t.name)
        parts.append(f"Available tools: {'; '.join(summaries)}.")
    rich_description = " ".join(parts)

    tool_namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    put_op = PutOp(
        namespace=SUBAGENTS_NAMESPACE,
        key=integration_id,
        value={
            "id": integration_id,
            "name": name,
            "description": rich_description,
            "source": "custom",
            "tool_namespace": tool_namespace,
        },
        index=["description"],
    )

    await store.abatch([put_op])
    log.info(
        f"{LogTag.AGENT} Indexed custom MCP as subagent",
        integration_name=name,
        integration_id=integration_id,
        tool_count=len(tools or []),
    )


async def _resolve_custom_mcp_subagent(
    resolved: CustomMcpSubagent,
    user_id: str | None,
) -> tuple[CompiledAgentGraph | None, str | None, str | None, bool]:
    """Resolve a custom MCP into the _resolve_subagent tuple."""
    integration_id = resolved.id
    integration_name = resolved.name if resolved.name is not None else integration_id

    if not integration_id:
        return None, None, "Error: Custom integration has no ID", False

    if not user_id:
        return (
            None,
            None,
            f"Error: {integration_name} requires authentication. Please sign in first.",
            False,
        )

    # Create subagent for custom MCP
    try:
        subagent_graph = await create_subagent_for_user(integration_id, user_id)
    except SubagentUnavailableError as e:
        return (
            None,
            None,
            f"Error: {integration_name} is unavailable: {e.reason}",
            False,
        )

    agent_name = f"custom_mcp_{integration_id}"
    return subagent_graph, agent_name, integration_id, True


async def _resolve_auth_mcp_graph(
    subagent: Subagent,
    agent_name: str,
    integration_id: str,
    user_id: str | None,
) -> tuple[CompiledAgentGraph | None, str | None]:
    """Graph for an auth-required MCP integration, or (None, error_message)."""
    if not user_id:
        return None, f"Error: {agent_name} requires authentication. Please sign in first."

    # Check if user has connected this MCP integration
    token_store = MCPTokenStore(user_id=user_id)
    is_connected = await token_store.is_connected(integration_id)
    if not is_connected:
        return None, await request_integration_connection(integration_id, subagent.name, user_id)

    # Create subagent on-the-fly with user's tokens
    try:
        return await create_subagent_for_user(integration_id, user_id), None
    except SubagentUnavailableError as e:
        return None, f"Error: {agent_name} is unavailable: {e.reason}"


async def _resolve_subagent(
    subagent_id: str,
    user_id: str | None,
) -> tuple[CompiledAgentGraph | None, str | None, str | None, bool]:
    """Resolve subagent from ID and get the graph.

    Accepts 'subagent:gmail', 'subagent:fb9dfd7e05f8 (Semantic Scholar)', or
    a bare id. Returns (None, None, error_message, False) on failure.
    """
    clean_id, _ = parse_subagent_id(subagent_id)

    resolved = await _get_subagent_by_id(clean_id)

    if not resolved:
        available = [s.id for s in all_subagents()][:5]
        known = get_subagent_by_id(clean_id)
        if known is not None:
            error = (
                f"'{subagent_id}' is not a handoff target. Use "
                f"activate_integration(integration_id='{known.id}') to load it "
                "in-context, then act on it yourself."
            )
        else:
            error = (
                f"Unknown integration '{subagent_id}'. "
                f"Examples: {', '.join(available)}{'...' if len(available) == 5 else ''}"
            )
        return None, None, error, False

    # Handle custom MCPs (resolved from MongoDB)
    if isinstance(resolved, CustomMcpSubagent):
        return await _resolve_custom_mcp_subagent(resolved, user_id)

    # Platform/builtin subagent (Subagent object)
    subagent = resolved
    agent_name = subagent.config.agent_name
    integration_id = subagent.id

    # Handle auth-required MCP integrations specially
    if subagent.managed_by == "mcp" and subagent.mcp_config and subagent.mcp_config.requires_auth:
        subagent_graph, graph_error = await _resolve_auth_mcp_graph(
            subagent, agent_name, integration_id, user_id
        )
    else:
        # Only per-user MCP integrations run as subagents (their tools are issued
        # per user and never load in-context). Provider and built-in integrations
        # activate in-context instead — handing one off resurrects the old model.
        log.set(handoff={"integration": integration_id, "routed_to_activation": True})
        return (
            None,
            None,
            f"'{integration_id}' is not a handoff target. Load it in-context with "
            f"activate_integration(integration_id='{integration_id}'), then act on "
            "it yourself with its tools.",
            False,
        )
    if graph_error is not None:
        return None, None, graph_error, False

    return subagent_graph, agent_name, integration_id, False


async def _build_integration_metadata(
    is_custom: bool, integration_id: str
) -> IntegrationMetadata | None:
    """Build display metadata for a resolved subagent integration."""
    if is_custom:
        integration = await _get_subagent_by_id(integration_id)
        if isinstance(integration, CustomMcpSubagent):
            return IntegrationMetadata(
                icon_url=integration.icon_url,
                integration_id=integration_id,
                name=integration.name or integration_id,
            )
        return None
    platform_integ = get_subagent_by_id(integration_id)
    if platform_integ:
        return IntegrationMetadata(
            icon_url=getattr(platform_integ, "icon_url", None),
            integration_id=integration_id,
            name=platform_integ.name,
        )
    return None


def _resolve_display_metadata(
    metadata: IntegrationMetadata | None,
    fallback_name: str,
    fallback_category: str,
) -> tuple[str, str | None, str]:
    """Extract display name, icon URL, and tool category from integration metadata."""
    if not metadata:
        return fallback_name, None, fallback_category
    return (
        str(metadata.name or fallback_name),
        metadata.icon_url,
        str(metadata.integration_id or fallback_category),
    )


async def prepare_subagent_execution(
    subagent_id: str,
    task: str,
    configurable: AgentConfigurable,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, IntegrationMetadata | None, str | None]:
    """Resolve a subagent and build everything needed to execute it.

    The single preparation path for running one subagent — used by the
    executor's handoff tool and the dev direct-invocation endpoint.
    Returns (ctx, integration_metadata, None) on success or
    (None, None, error_message) when the subagent can't be resolved.
    """
    user_id = configurable.get("user_id")

    (
        subagent_graph,
        resolved_agent_name,
        int_id_or_error,
        is_custom,
    ) = await _resolve_subagent(subagent_id, user_id)

    if subagent_graph is None or resolved_agent_name is None or int_id_or_error is None:
        return None, None, int_id_or_error or "Unknown error resolving subagent"

    agent_name: str = resolved_agent_name
    integration_id: str = int_id_or_error
    log.set(
        subagent={
            "name": agent_name,
            "provider": integration_id,
            "is_custom": is_custom,
            "task_length": len(task),
        }
    )

    thread_id = configurable.get("thread_id", "")
    subagent_thread_id = f"{integration_id}_{thread_id}"

    user: AgentUserContext = {
        "user_id": user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }

    subagent_config = await build_agent_config(
        identity=AgentIdentity(
            conversation_id=thread_id,
            user=user,
            agent_name=agent_name,
        ),
        thread=AgentThread(
            thread_id=subagent_thread_id,
            base_configurable=configurable,
            subagent_id=agent_name,
        ),
    )
    new_configurable = agent_configurable(subagent_config)

    system_message = await create_subagent_system_message(integration_id=integration_id)

    # Declared startup tools load as schema docs appended to the static prompt, so
    # the slot stays singleton and cache-stable. Degrades to no docs (with a
    # warning) rather than failing: the agent can still retrieve_tools + execute.
    try:
        preload_block = await preloaded_startup_docs(user_id, integration_id)
    except Exception as e:
        log.warning(
            f"{LogTag.AGENT} Startup tool docs unavailable; continuing without them",
            integration_id=integration_id,
            error_type=type(e).__name__,
        )
        preload_block = ""
    if preload_block:
        system_message = SystemMessage(content=f"{system_message.content}\n\n{preload_block}")

    # Avoid passing Gaia display name as a service username
    provider_meta = None
    provider_name = None
    platform_subagent = get_subagent_by_id(integration_id)
    if platform_subagent and platform_subagent.provider and user_id:
        provider_name = platform_subagent.provider
        provider_meta = await get_provider_metadata(user_id, platform_subagent.provider)
    service_username = _extract_service_username(provider_meta)
    integration_usernames: dict[str, str] = {}
    if provider_name and service_username:
        integration_usernames[provider_name] = service_username
    sanitized_task = _sanitize_task_user_reference(
        task=task,
        gaia_name=user.get("name"),
        provider_hint=(provider_name or integration_id),
        service_username=service_username,
    )

    messages = await build_initial_messages(
        system_message=system_message,
        agent_name=agent_name,
        task=sanitized_task,
        seed=ThreadSeed(
            tier=AgentTier.PROVIDER_SUBAGENT,
            configurable=new_configurable,
            user_id=user_id,
            subagent_id=agent_name,
            # Without this the custom-instructions/provider-metadata lookup falls
            # back to agent_name ("gmail_agent"), which never matches the stored
            # integration id ("gmail"), so the user's instructions are dropped.
            integration_id=integration_id,
        ),
    )

    ctx = SubagentExecutionContext(
        subagent_graph=subagent_graph,
        agent_name=agent_name,
        config=subagent_config,
        configurable=new_configurable,
        integration_id=integration_id,
        initial_state={
            "messages": messages,
            "todos": [],
            "intent": sanitized_task,
            "integration_usernames": integration_usernames,
        },
        user_id=user_id,
        stream_id=stream_id,
    )

    integration_metadata = await _build_integration_metadata(is_custom, integration_id)
    return ctx, integration_metadata, None


async def _has_parked_subagent(ctx: SubagentExecutionContext) -> bool:
    """Whether an uncollected HIL-parked subagent owns this ctx's checkpoint thread.

    Durable check (Mongo), so it holds across executor pause/resume and process
    restarts — the session slot only tracks live tasks in this invocation.
    """
    configurable: AgentConfigurable = ctx.configurable
    conversation_id = str(configurable.get("conversation_id") or "")
    thread_id = str(configurable.get("thread_id") or "")
    if not conversation_id or not thread_id:
        return False
    records = await list_parked_subagents_for_conversation(conversation_id)
    return any(record.subagent_thread_id == thread_id for record in records)


async def _handoff_rejection(ctx: SubagentExecutionContext, task: str) -> str | None:
    """Return the pre-dispatch refusal for one handoff, or None when it may run."""
    agent_name: str = ctx.agent_name
    integration_id: str = ctx.integration_id

    # A task naming one provider while routed to another tells the user their data
    # went somewhere it never did. Refuse before dispatch — the executor can
    # re-route or drop the name, but once said it cannot un-say it.
    foreign = foreign_provider_named_in(task, integration_id)
    if foreign is not None:
        return (
            f"HANDOFF REJECTED: this task is routed to the {agent_name} subagent "
            f"({integration_id}) but its text names {foreign.name}. {foreign.name} is a "
            f"separate integration with its own tools, and nothing you hand to "
            f"{integration_id} touches it: leaving the name in makes the result claim "
            f"{foreign.name} did work it never did. Either activate {foreign.id} with "
            f"activate_integration and do that part yourself, or send this handoff "
            f"again with every mention of {foreign.name} removed from the task."
        )

    # A parked subagent owns this integration's checkpoint thread; feeding it any
    # new handoff makes LangGraph discard the pending interrupt and orphan the
    # user's approval card. Refuse until the decision resumes it.
    if await _has_parked_subagent(ctx):
        return (
            f"The {agent_name} subagent is paused waiting for the user's approval. "
            "It resumes on its own once the user decides and its result arrives in your "
            "inbox; send it nothing meanwhile."
        )
    return None


async def build_handoff_delegation(
    subagent_id: str,
    task: str,
    parent_configurable: AgentConfigurable,
    tool_call_id: str,
) -> Delegation | str:
    """Build the delegation one handoff call runs, or the reason it cannot.

    Also how a parked MCP subagent is rebuilt to resume: everything here is keyed
    by the user, the integration id and the tool call, never by live process state.
    """
    ctx, integration_metadata, error = await prepare_subagent_execution(
        subagent_id=subagent_id,
        task=task,
        configurable=parent_configurable,
        stream_id=parent_configurable.get("stream_id"),
    )
    if ctx is None:
        return error or "Unknown error resolving subagent"
    display, icon_url, tool_category = _resolve_display_metadata(
        integration_metadata, ctx.agent_name, ctx.integration_id
    )
    return Delegation(
        ctx=ctx,
        kind=SubagentKind.MCP,
        # Stable across replays, so an approval pause reuses its UI row.
        subagent_id=subagent_row_id(tool_call_id),
        tool_call_id=tool_call_id,
        task=task,
        integration_id=subagent_id,
        integration_metadata=integration_metadata,
        parent_configurable=parent_configurable,
        display=SubagentDisplay(
            name=display,
            agent_type="handoff",
            tool_category=tool_category,
            icon_url=icon_url,
            integration=ctx.integration_id,
        ),
    )


@tool
async def handoff(
    subagent_id: Annotated[
        str,
        "The ID of a per-user MCP integration to delegate to (custom MCP "
        "connections only — e.g. 'my-notion-mcp'). Discovered via "
        "retrieve_tools as subagent: entries (only per-user MCP integrations "
        "appear there). Provider and built-in integrations (gmail, github, "
        "todos, ...) are NOT handoff targets: load those with "
        "activate_integration instead.",
    ],
    task: Annotated[
        str,
        "Detailed description of the task for the subagent, including all relevant context.",
    ],
    config: RunnableConfig,
    background: Annotated[
        bool,
        "True (default): return at once and keep working; the result arrives in "
        "your inbox on its own. Steer or stop it by id with message_subagent / "
        "cancel_subagent. False: wait for the result here. A headless run "
        "(workflow, scheduled todo) always waits.",
    ] = True,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> str:
    """Delegate a task to a per-user MCP integration's own subagent.

    This is the ONLY path for custom/auth-required MCP integrations, whose
    tools are issued per user and can never load in-context (activate_integration
    tells you to come here for exactly those). Every other integration is
    activated in-context with activate_integration and acted on directly —
    never handed off.

    Runs on the same runner as spawn_subagent: in the background by default,
    so several handoffs run side by side while you keep working.
    """
    try:
        configurable: AgentConfigurable = agent_configurable(config)
        user_id = configurable.get("user_id")

        # Fallback: try to get user_id from metadata if not in configurable
        if not user_id:
            user_id = _RunMetadata.model_validate(config.get("metadata") or {}).user_id
            if user_id:
                configurable["user_id"] = user_id

        delegation = await build_handoff_delegation(subagent_id, task, configurable, tool_call_id)
        if isinstance(delegation, str):
            return delegation
        rejection = await _handoff_rejection(delegation.ctx, task)
        if rejection is not None:
            return rejection
        return await delegate(
            delegation,
            background=background,
            # Only a resume replay can find this subagent's thread already run.
            probe_parked=bool(configurable.get(HIL_RESUME_CONFIG_KEY)),
        )

    except GraphBubbleUp:
        # The HIL gate's interrupt bubbling up from a blocking handoff. Control
        # flow, not a failure — swallowing it here would convert the approval pause
        # into a tool error and run the executor on without ever pausing.
        raise
    except Exception as e:
        log.error(
            f"{LogTag.AGENT} handoff_failed",
            subagent_id=subagent_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e)[:500],
            exc_info=True,
        )
        return f"Error executing task: {e!s}"
