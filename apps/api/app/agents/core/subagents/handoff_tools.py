"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
Subagent identity/metadata comes from agents/core/subagents/registry.py
(unified view of OAuth-derived + builtin subagents).
"""

import re
import time
from typing import Annotated, Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, InjectedToolCallId, tool
from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.store.base import BaseStore, PutOp
from langgraph.types import Command

from app.agents.context.tiers import AgentTier
from app.agents.core.background.bg_results import try_claim_bg_dispatch
from app.agents.core.background.session import (
    claim_bg_integration,
    has_bg_integration,
    increment_pending_subagents,
    release_bg_integration,
)
from app.agents.core.background.subagent_runner import run_subagent_background
from app.agents.core.graph_manager import CompiledAgentGraph
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
    SubagentOutcome,
    build_initial_messages,
    execute_subagent_stream,
    recover_from_checkpoint,
    resume_for_gate,
    subagent_row_id,
)
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.constants.hil import HIL_RESUME_CONFIG_KEY
from app.constants.log_tags import LogTag
from app.core.lazy_loader import providers
from app.db.redis import get_cache, set_cache
from app.db.repositories.integrations import integration_repository
from app.helpers.agent_helpers import build_agent_config
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.agent_models import AgentConfigurable, AgentUserContext, agent_configurable
from app.models.hil_models import HILApprovalRecord, HILApprovalStatus
from app.models.subagent_models import Subagent
from app.services.hil.approvals_store import list_parked_subagents_for_conversation
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import (
    check_integration_status,
)
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.agent_utils import (
    IntegrationMetadata,
    StreamWriterCallable,
    format_subagent_end_event,
    format_subagent_start_event,
    parse_subagent_id,
)
from app.utils.background_tasks import spawn_background_task
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log

SUBAGENTS_NAMESPACE = ("subagents",)


def _extract_service_username(metadata: dict[str, Any] | None) -> str | None:
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
    """Return the connect prompt when the integration isn't connected, else None."""
    subagent = get_subagent_by_id(integration_id)
    if not subagent:
        return None

    if await check_integration_status(integration_id, user_id):
        return None

    return await request_integration_connection(subagent.id, subagent.name, user_id)


async def _get_subagent_by_id(subagent_id: str) -> Subagent | dict[str, Any] | None:
    """
    Get subagent by ID or short_name.

    Checks both platform/builtin subagents (via registry) and custom MCPs
    from MongoDB. Uses Redis caching to avoid repeated DB queries for
    custom MCPs.

    Returns:
        Subagent (platform/builtin) or dict (custom MCP info), or None if
        not found
    """
    search_id = subagent_id.lower().strip()

    # Check platform/builtin subagents first (no caching needed - in-memory)
    subagent = get_subagent_by_id(search_id)
    if subagent:
        return subagent

    # Check Redis cache for custom integrations
    cache_key = f"{SUBAGENT_CACHE_PREFIX}:{search_id}"
    cached: dict[str, Any] | None = await get_cache(cache_key)
    if cached is not None:
        # Return cached result (could be empty dict for negative cache)
        return cached or None

    # Search by integration_id (case-insensitive) or exact name
    custom = await integration_repository.find_by_id_prefix_or_name(search_id)

    if custom:
        result = {
            "id": custom.integration_id,
            "name": custom.name,
            "source": custom.source,
            "managed_by": custom.managed_by,
            "mcp_config": custom.mcp_config.model_dump() if custom.mcp_config else None,
            "icon_url": custom.icon_url,
            "subagent_config": None,
        }
        await set_cache(cache_key, result, ttl=SUBAGENT_CACHE_TTL)
        return result

    # Fallback: Try IntegrationResolver which checks multiple sources
    # This handles cases where integration is in user_integrations but not integrations

    resolved = await IntegrationResolver.resolve(search_id)
    if resolved and resolved.custom_doc:
        doc = resolved.custom_doc
        result = {
            "id": doc.get("integration_id"),
            "name": doc.get("name"),
            "source": resolved.source,
            "managed_by": "mcp",
            "mcp_config": doc.get("mcp_config"),
            "icon_url": doc.get("icon_url"),
            "subagent_config": None,
        }
        await set_cache(cache_key, result, ttl=SUBAGENT_CACHE_TTL)
        return result

    # Cache negative result to avoid repeated DB queries
    await set_cache(cache_key, {}, ttl=SUBAGENT_CACHE_TTL)
    return None


async def index_custom_mcp_as_subagent(
    store: BaseStore,
    integration_id: str,
    name: str,
    description: str,
    server_url: str | None = None,
    tools: list[BaseTool] | None = None,
) -> None:
    """
    Index a custom MCP as a subagent for handoff discovery.

    Called when user connects a custom MCP to make it immediately
    available for semantic search and handoff.

    Args:
        store: The ChromaStore instance
        integration_id: Unique ID of the custom integration (12-char hex)
        name: Display name of the integration
        description: Description of what the integration does
        server_url: MCP server URL for namespace derivation
        tools: The MCP's tools — their names/summaries are embedded so the
            subagent ranks for what it can actually do (e.g. a "get_meetings"
            tool surfaces on a "meetings" query) instead of generic boilerplate.
    """
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


async def _resolve_subagent(
    subagent_id: str,
    user_id: str | None,
) -> tuple[CompiledAgentGraph | None, str | None, str | None, bool]:
    """
    Resolve subagent from ID and get the graph.

    Accepts formats:
        - 'subagent:gmail'
        - 'subagent:fb9dfd7e05f8 (Semantic Scholar)'
        - 'gmail' (bare ID)

    Returns:
        Tuple of (subagent_graph, agent_name, integration_id, is_custom)
        or (None, None, error_message, False) on failure
    """
    clean_id, _ = parse_subagent_id(subagent_id)

    resolved = await _get_subagent_by_id(clean_id)

    if not resolved:
        available = [s.id for s in all_subagents()][:5]
        error = (
            f"Subagent '{subagent_id}' not found. "
            f"Use retrieve_tools to find available subagents. "
            f"Examples: {', '.join([f'subagent:{a}' for a in available])}{'...' if len(available) == 5 else ''}"
        )
        return None, None, error, False

    # Handle custom MCPs (returned as dict from MongoDB)
    if isinstance(resolved, dict):
        # Custom MCP - resolved is a dict
        integration_id = str(resolved.get("id", ""))
        integration_name = str(resolved.get("name", integration_id))

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

    # Platform/builtin subagent (Subagent object)
    subagent = resolved
    agent_name = subagent.config.agent_name
    integration_id = subagent.id

    # Handle auth-required MCP integrations specially
    if subagent.managed_by == "mcp" and subagent.mcp_config and subagent.mcp_config.requires_auth:
        if not user_id:
            return (
                None,
                None,
                f"Error: {agent_name} requires authentication. Please sign in first.",
                False,
            )

        # Check if user has connected this MCP integration
        token_store = MCPTokenStore(user_id=user_id)
        is_connected = await token_store.is_connected(integration_id)
        if not is_connected:
            return (
                None,
                None,
                await request_integration_connection(integration_id, subagent.name, user_id),
                False,
            )

        # Create subagent on-the-fly with user's tokens
        try:
            subagent_graph = await create_subagent_for_user(integration_id, user_id)
        except SubagentUnavailableError as e:
            return (
                None,
                None,
                f"Error: {agent_name} is unavailable: {e.reason}",
                False,
            )
    else:
        # Non-MCP or non-auth-required MCP integrations
        # Skip connection check for internal integrations (always available)
        if subagent.managed_by not in ("mcp", "internal") and user_id:
            error_message = await check_integration_connection(integration_id, user_id)
            if error_message:
                return None, None, error_message, False

        try:
            subagent_graph = await providers.aget(agent_name)
        except KeyError:
            return None, None, f"Error: {agent_name} not available", False
        if not subagent_graph:
            return None, None, f"Error: {agent_name} not available", False

    return subagent_graph, agent_name, integration_id, False


async def _build_integration_metadata(
    is_custom: bool, integration_id: str
) -> IntegrationMetadata | None:
    """Build display metadata for a resolved subagent integration."""
    if is_custom:
        integration = await _get_subagent_by_id(integration_id)
        if isinstance(integration, dict):
            return IntegrationMetadata(
                icon_url=integration.get("icon_url"),
                integration_id=integration_id,
                name=str(integration.get("name") or integration_id),
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
        str(metadata.get("name") or fallback_name),
        metadata.get("icon_url"),
        str(metadata.get("integration_id") or fallback_category),
    )


async def prepare_subagent_execution(
    subagent_id: str,
    task: str,
    configurable: AgentConfigurable,
    stream_id: str | None = None,
) -> tuple[SubagentExecutionContext | None, IntegrationMetadata | None, str | None]:
    """Resolve a subagent and build everything needed to execute it.

    The single preparation path for running one subagent — used by the
    executor's `handoff` tool and the dev direct-invocation endpoint.
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
        conversation_id=thread_id,
        user=user,
        thread_id=subagent_thread_id,
        base_configurable=configurable,
        agent_name=agent_name,
        subagent_id=agent_name,
    )
    new_configurable = agent_configurable(subagent_config)

    system_message = await create_subagent_system_message(integration_id=integration_id)

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
        tier=AgentTier.PROVIDER_SUBAGENT,
        agent_name=agent_name,
        configurable=new_configurable,
        task=sanitized_task,
        user_id=user_id,
        subagent_id=agent_name,
        # Without this the custom-instructions/provider-metadata lookup falls
        # back to agent_name ("gmail_agent"), which never matches the stored
        # integration id ("gmail"), so the user's instructions are dropped.
        integration_id=integration_id,
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


async def _run_blocking_handoff(
    ctx: SubagentExecutionContext,
    metadata: IntegrationMetadata | None,
    agent_name: str,
    integration_id: str,
    tool_call_id: str,
    probe_parked: bool = False,
) -> str:
    """Run a handoff subagent synchronously, emitting lifecycle SSE events."""
    writer = get_stream_writer()
    # Stable across replays so an approval pause reuses the same UI row instead of
    # orphaning the paused one and opening a duplicate on resume.
    sa_id = subagent_row_id(tool_call_id)
    display, icon_url, tool_category = _resolve_display_metadata(
        metadata, agent_name, integration_id
    )

    # Propagate this subagent's UUID into config so nested spawned subagents
    # can reference it as parent_subagent_id.
    ctx.configurable["subagent_id"] = sa_id
    ctx.config.setdefault("configurable", {})["subagent_id"] = sa_id

    writer(
        {
            "subagent_start": format_subagent_start_event(
                subagent_name=display,
                agent_type="handoff",
                subagent_id=sa_id,
                icon_url=icon_url,
                tool_category=tool_category,
            )
        }
    )
    start_time = time.monotonic()

    # When the executor resumes, THIS node re-runs from the top over a subagent thread
    # that already holds work — parked on its interrupt, or finished before a LATER
    # sibling in the same node paused. Either way, re-invoking it fresh would redo
    # everything it already did, so an existing checkpoint means "recover, don't rerun".
    # A recoverable checkpoint can only exist on a resume replay, so fresh runs skip the
    # probe (a per-handoff Postgres read) entirely.
    recovered = await recover_from_checkpoint(ctx) if probe_parked else None
    if recovered is not None:
        outcome = recovered
    else:
        outcome = await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=metadata,
            subagent_id=sa_id,
        )

    # The subagent was invoked imperatively, so its GraphInterrupt never reaches
    # the executor's runtime — bubble each pause up explicitly. A LOOP, not an if:
    # one task can gate several destructive calls in sequence ("send both emails"),
    # and each pause must suspend the executor again. resume_for_gate() raises on the
    # first pass (pausing the executor) and returns THIS gate's own decision on the
    # replay — recovery fast-forwards to the latest park, so an earlier gate's already
    # -applied decision must not be replayed onto it (matched out by approval_id).
    while outcome.paused:
        decision = resume_for_gate(outcome.interrupt)
        outcome = await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=metadata,
            subagent_id=sa_id,
            resume=Command(resume=decision),
        )

    writer(
        {
            "subagent_end": format_subagent_end_event(
                subagent_id=sa_id,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        }
    )
    return outcome.text


async def _has_parked_subagent(ctx: SubagentExecutionContext) -> bool:
    """Whether an uncollected HIL-parked subagent owns this ctx's checkpoint thread.

    Durable check (Mongo), so it holds across executor pause/resume and process
    restarts — the session slot only tracks live tasks in this invocation.
    """
    conversation_id = str(ctx.configurable.get("conversation_id") or "")
    thread_id = str(ctx.configurable.get("thread_id") or "")
    if not conversation_id or not thread_id:
        return False
    records = await list_parked_subagents_for_conversation(conversation_id)
    return any(record.subagent_thread_id == thread_id for record in records)


async def resume_parked_subagent(
    record: "HILApprovalRecord",
    configurable: AgentConfigurable,
    stream_writer: StreamWriterCallable,
) -> SubagentOutcome:
    """Resume a HIL-parked background subagent with its decided approval.

    Everything is reconstructed from durable state — the approval record plus the
    current executor configurable — because the run that parked it (its session,
    stream and asyncio task) is gone. Crash-safe: a thread that already completed
    (a prior collect crashed between resume and stamp) yields its checkpointed
    final answer instead of being driven again, so the underlying action can
    never re-execute.
    """
    agent_ref = record.subagent_agent_name or ""
    graph, agent_name, int_id_or_error, _ = await _resolve_subagent(agent_ref, record.user_id)
    if graph is None or agent_name is None or int_id_or_error is None:
        return SubagentOutcome(
            text=f"Error resuming {agent_ref}: {int_id_or_error or 'subagent not resolvable'}"
        )

    user: AgentUserContext = {
        "user_id": record.user_id,
        "email": configurable.get("email"),
        "name": configurable.get("user_name"),
    }
    subagent_config = await build_agent_config(
        conversation_id=record.conversation_id,
        user=user,
        thread_id=record.subagent_thread_id,
        base_configurable=configurable,
        agent_name=agent_name,
        subagent_id=agent_name,
    )
    ctx = SubagentExecutionContext(
        subagent_graph=graph,
        agent_name=agent_name,
        config=subagent_config,
        configurable=agent_configurable(subagent_config),
        integration_id=int_id_or_error,
        initial_state={},
        user_id=record.user_id,
        stream_id=str(configurable.get("stream_id") or "") or None,
    )

    recovered = await recover_from_checkpoint(ctx)
    if recovered is None:
        # The record says a subagent parked on this thread, but the thread holds no
        # state — its checkpoint is gone. Nothing to resume, and starting fresh would
        # run the task again from an empty initial state, so say so instead.
        return SubagentOutcome(text=f"Error resuming {agent_name}: its checkpoint is missing.")
    if not recovered.paused:
        return recovered

    decision = {
        "status": _subagent_resume_status(record.status),
        "feedback": record.feedback,
        "scope": record.scope,
    }
    return await execute_subagent_stream(
        ctx=ctx, stream_writer=stream_writer, resume=Command(resume=decision)
    )


def _subagent_resume_status(status: HILApprovalStatus) -> HILApprovalStatus:
    """Map a record's terminal status onto the gate's resumable statuses.

    ``abandoned`` resumes as a denial — the gate accepts only
    approved/denied/timeout, and abandonment means "do not act."
    """
    if status in (HILApprovalStatus.APPROVED, HILApprovalStatus.TIMEOUT):
        return status
    return HILApprovalStatus.DENIED


@tool
async def handoff(
    subagent_id: Annotated[
        str,
        "The ID of the subagent to delegate to (e.g., 'gmail', 'subagent:gmail'). "
        "Get this from retrieve_tools results (subagent IDs have 'subagent:' prefix).",
    ],
    task: Annotated[
        str,
        "Detailed description of the task for the subagent, including all relevant context.",
    ],
    config: RunnableConfig,
    background: Annotated[
        bool,
        "If True, run the subagent in the background and return immediately. "
        "Use for parallel subagent dispatch: call wait_for_subagents() after "
        "all background handoffs to collect results. Default False (blocking).",
    ] = False,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> str:
    """Delegate a task to a specialized subagent.

    Use this tool to hand off tasks to expert subagents that specialize in specific domains.
    First use retrieve_tools to find available subagents (they appear with 'subagent:' prefix).

    The subagent will:
    1. Process the task using its specialized tools
    2. Return the result of the completed task

    For parallel execution, set background=True on multiple handoff calls, then
    call wait_for_subagents() to collect all results once.

    Args:
        subagent_id: ID of the subagent from retrieve_tools (e.g., 'subagent:gmail', 'gmail')
        task: Complete task description with all necessary context
        background: If True, run non-blocking and return immediately
    """
    try:
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id")

        # Fallback: try to get user_id from metadata if not in configurable
        if not user_id:
            user_id = config.get("metadata", {}).get("user_id")
            if user_id:
                configurable["user_id"] = user_id

        stream_id = configurable.get("stream_id")  # Extract stream_id for cancellation

        # Only a resume replay can have left a parked subagent behind, so the
        # per-handoff checkpoint probe in _run_blocking_handoff is gated on this.
        probe_parked = bool(configurable.get(HIL_RESUME_CONFIG_KEY))

        ctx, integration_metadata, error = await prepare_subagent_execution(
            subagent_id=subagent_id,
            task=task,
            configurable=configurable,
            stream_id=stream_id,
        )
        if ctx is None:
            return error or "Unknown error resolving subagent"

        agent_name: str = ctx.agent_name
        integration_id: str = ctx.integration_id

        # A task naming one provider while routed to another is a routing mistake
        # that survives the whole run: the subagent does the work on ITS system and
        # the executor writes the name it was told into the summary, so the user is
        # told their data went somewhere it never went. Refuse before dispatch —
        # the executor can re-route or drop the name, but it cannot un-say it.
        foreign = foreign_provider_named_in(task, integration_id)
        if foreign is not None:
            return (
                f"HANDOFF REJECTED: this task is routed to the {agent_name} subagent "
                f"({integration_id}) but its text names {foreign.name}. {foreign.name} is a "
                f"separate integration with its own subagent, and nothing you hand to "
                f"{integration_id} touches it: leaving the name in makes the result claim "
                f"{foreign.name} did work it never did. Either re-issue this handoff to "
                f"subagent:{foreign.id} if that is where the work belongs, or send it again "
                f"with every mention of {foreign.name} removed from the task."
            )

        # An uncollected parked subagent owns this integration's checkpoint thread.
        # Running ANY new handoff on it (blocking or background) would feed fresh
        # input to an interrupted thread — LangGraph discards the pending interrupt,
        # orphaning the user's approval card. Refuse until the join collects it.
        if await _has_parked_subagent(ctx):
            return (
                f"The {agent_name} subagent is paused waiting for the user's approval. "
                "Call wait_for_subagents() to collect its outcome before sending it "
                "new tasks."
            )

        # Same collision for a BLOCKING handoff while a live background task holds
        # this integration's thread (the background branch guards itself via the
        # session slot claim).
        if not background and has_bg_integration(str(stream_id or ""), integration_id):
            return (
                f"A background {agent_name} subagent is already running on this "
                "integration. Call wait_for_subagents() to collect it first."
            )

        # Background mode: spawn subagent as asyncio task and return immediately.
        # Caller must use wait_for_subagents() to collect results.
        #
        # Requires stream_id to be propagated into the executor configurable so
        # the result can be routed back to this conversation's results bucket.
        if background:
            if not stream_id:
                log.warning(
                    f"{LogTag.AGENT} handoff background=True but stream_id is missing — "
                    "falling back to blocking execution"
                )
                blocking_result = await _run_blocking_handoff(
                    ctx,
                    integration_metadata,
                    agent_name,
                    integration_id,
                    tool_call_id,
                    probe_parked,
                )
                return (
                    "[WARNING: background handoff fell back to blocking: "
                    "stream_id not propagated into executor configurable] "
                    f"{blocking_result}"
                )
            sid: str = str(stream_id)
            # execution_mode is inherited, NOT forced to "background": a detached
            # subagent in a live conversation now has a pause path — its gate parks the
            # subagent's own checkpointed thread and wait_for_subagents collects the
            # approval into one executor pause. A genuinely headless run (workflow/cron)
            # is already "background" in the parent configurable, so its subagents
            # inherit that and the gate still fails closed (no live user to ask).
            #
            # One detached subagent per integration at a time: a concurrent duplicate
            # would share the deterministic checkpoint thread id and corrupt it. A
            # blocking run would collide identically, so refuse rather than fall back.
            if not claim_bg_integration(sid, integration_id):
                return (
                    f"A background {agent_name} subagent is already running. Call "
                    "wait_for_subagents() to collect it before sending it new tasks."
                )
            # Idempotent across node replays: when this handoff shares its node run
            # with the wait_for_subagents interrupt, the node re-runs on resume and
            # must not spawn the subagent a second time. tool_call_id is stable (it
            # lives in the checkpointed AI message); the claim is durable in Redis.
            conversation_id = str(ctx.configurable.get("conversation_id") or "")
            if (
                tool_call_id
                and conversation_id
                and not await try_claim_bg_dispatch(conversation_id, tool_call_id)
            ):
                release_bg_integration(sid, integration_id)
                return (
                    f"Subagent {agent_name} started in background. "
                    "Call wait_for_subagents() when ready to collect results."
                )
            bg_sa_id = str(uuid4())
            bg_display, bg_icon, bg_cat = _resolve_display_metadata(
                integration_metadata, agent_name, integration_id
            )
            increment_pending_subagents(sid)
            spawn_background_task(
                run_subagent_background(
                    ctx=ctx,
                    stream_id=sid,
                    integration_metadata=integration_metadata,
                    subagent_id=bg_sa_id,
                    display_name=bg_display,
                    tool_category=bg_cat,
                    icon_url=bg_icon,
                    integration_id=integration_id,
                )
            )
            log.info(
                f"{LogTag.AGENT} Subagent dispatched to background",
                agent_name=agent_name,
                stream_id=sid,
            )
            return (
                f"Subagent {agent_name} started in background. "
                "Call wait_for_subagents() when ready to collect results."
            )

        # Blocking (default): execute synchronously and return result.
        return await _run_blocking_handoff(
            ctx, integration_metadata, agent_name, integration_id, tool_call_id, probe_parked
        )

    except GraphBubbleUp:
        # The HIL gate's interrupt bubbling up from _run_blocking_handoff. Control
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
