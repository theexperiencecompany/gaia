"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
Subagent identity/metadata comes from agents/core/subagents/registry.py
(unified view of OAuth-derived + builtin subagents).
"""

import asyncio
from datetime import datetime
import re
import time
from typing import Annotated
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore, PutOp

from app.agents.core.background.inbox import increment_pending_subagents
from app.agents.core.background.subagent_runner import run_subagent_background
from app.agents.core.subagents.provider_subagents import create_subagent_for_user
from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.core.subagents.subagent_helpers import (
    create_subagent_system_message,
)
from app.agents.core.subagents.subagent_runner import (
    SubagentExecutionContext,
    build_initial_messages,
    execute_subagent_stream,
)
from app.constants.cache import SUBAGENT_CACHE_PREFIX, SUBAGENT_CACHE_TTL
from app.core.lazy_loader import providers
from app.db.mongodb.collections import integrations_collection
from app.db.redis import get_cache, set_cache
from app.helpers.agent_helpers import build_agent_config
from app.helpers.namespace_utils import derive_integration_namespace
from app.services.connect_link_service import build_connect_link_url
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import (
    check_integration_status,
)
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.agent_utils import (
    IntegrationMetadata,
    format_subagent_end_event,
    format_subagent_start_event,
    parse_subagent_id,
)
from app.utils.integration_checker import build_integration_connection_message
from shared.py.wide_events import log

SUBAGENTS_NAMESPACE = ("subagents",)


def _extract_service_username(metadata: dict | None) -> str | None:
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
    """Check if integration is connected and return error message if not."""
    try:
        subagent = get_subagent_by_id(integration_id)
        if not subagent:
            return None

        is_connected = await check_integration_status(integration_id, user_id)

        if is_connected:
            return None

        writer = get_stream_writer()
        writer({"progress": f"Checking {subagent.name} connection..."})

        integration_data = {
            "integration_id": subagent.id,
            "message": f"To use {subagent.name} features, please connect your account first.",
        }

        writer({"integration_connection_required": integration_data})

        connect_url = build_connect_link_url(user_id, subagent.id)
        return build_integration_connection_message(subagent.name, connect_url)

    except Exception as e:
        log.error(f"Error checking integration status for {integration_id}: {e}")
        return None


async def _get_subagent_by_id(subagent_id: str):
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
    cached = await get_cache(cache_key)
    if cached is not None:
        # Return cached result (could be empty dict for negative cache)
        return cached if cached else None

    # Escape regex metacharacters to prevent ReDoS attacks
    escaped_search_id = re.escape(search_id)

    # Search by integration_id (case-insensitive)
    custom = await integrations_collection.find_one(
        {
            "$or": [
                {
                    "integration_id": {
                        "$regex": f"^{escaped_search_id}",
                        "$options": "i",
                    }
                },
                {"name": {"$regex": f"^{escaped_search_id}$", "$options": "i"}},
            ],
        }
    )

    if custom:
        result = {
            "id": custom.get("integration_id"),
            "name": custom.get("name"),
            "source": custom.get("source", "custom"),
            "managed_by": custom.get("managed_by", "mcp"),
            "mcp_config": custom.get("mcp_config"),
            "icon_url": custom.get("icon_url"),
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
    """
    rich_description = (
        f"{name}. Custom MCP integration. "
        f"{description}. "
        f"Use cases: data fetching, automation, API access, external services. "
        f"Examples: fetch data, scrape, query, automate"
    )

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
    log.info(f"Indexed custom MCP {name} ({integration_id}) as subagent")


async def _resolve_subagent(
    subagent_id: str,
    user_id: str | None,
) -> tuple[object | None, str | None, str | None, bool]:
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
        subagent_graph = await create_subagent_for_user(integration_id, user_id)
        if not subagent_graph:
            return (
                None,
                None,
                f"Error: Failed to create subagent for {integration_name}",
                False,
            )

        agent_name = f"custom_mcp_{integration_id}"
        return subagent_graph, agent_name, integration_id, True

    # Platform/builtin subagent (Subagent object)
    subagent = resolved
    agent_name = subagent.config.agent_name
    int_id = subagent.id

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
        is_connected = await token_store.is_connected(int_id)
        if not is_connected:
            connect_url = build_connect_link_url(user_id, int_id)
            return (
                None,
                None,
                build_integration_connection_message(subagent.name, connect_url),
                False,
            )

        # Create subagent on-the-fly with user's tokens
        subagent_graph = await create_subagent_for_user(int_id, user_id)
        if not subagent_graph:
            return (
                None,
                None,
                f"Error: Failed to create {agent_name} subagent",
                False,
            )
    else:
        # Non-MCP or non-auth-required MCP integrations
        # Skip connection check for internal integrations (always available)
        if subagent.managed_by not in ("mcp", "internal") and user_id:
            error_message = await check_integration_connection(int_id, user_id)
            if error_message:
                return None, None, error_message, False

        try:
            subagent_graph = await providers.aget(agent_name)
        except KeyError:
            return None, None, f"Error: {agent_name} not available", False
        if not subagent_graph:
            return None, None, f"Error: {agent_name} not available", False

    return subagent_graph, agent_name, int_id, False


_background_subagent_tasks: set[asyncio.Task[None]] = set()


async def _build_integration_metadata(is_custom: bool, int_id: str) -> IntegrationMetadata | None:
    """Build display metadata for a resolved subagent integration."""
    if is_custom:
        integration = await _get_subagent_by_id(int_id)
        if isinstance(integration, dict):
            return IntegrationMetadata(
                icon_url=integration.get("icon_url"),
                integration_id=int_id,
                name=str(integration.get("name") or int_id),
            )
        return None
    platform_integ = get_subagent_by_id(int_id)
    if platform_integ:
        return IntegrationMetadata(
            icon_url=getattr(platform_integ, "icon_url", None),
            integration_id=int_id,
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


async def _run_blocking_handoff(
    ctx: SubagentExecutionContext,
    metadata: IntegrationMetadata | None,
    agent_name: str,
    int_id: str,
) -> str:
    """Run a handoff subagent synchronously, emitting lifecycle SSE events."""
    writer = get_stream_writer()
    sa_id = str(uuid4())
    display, icon_url, tool_category = _resolve_display_metadata(metadata, agent_name, int_id)

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
    result = await execute_subagent_stream(
        ctx=ctx,
        stream_writer=writer,
        integration_metadata=metadata,
        subagent_id=sa_id,
    )
    writer(
        {
            "subagent_end": format_subagent_end_event(
                subagent_id=sa_id,
                duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        }
    )
    return result


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
        "Use for parallel subagent dispatch — call wait_for_subagents() after "
        "all background handoffs to collect results. Default False (blocking).",
    ] = False,
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
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id")

        # Fallback: try to get user_id from metadata if not in configurable
        if not user_id:
            metadata = config.get("metadata", {})
            user_id = metadata.get("user_id")
            if user_id and "configurable" in config:
                # Update configurable with user_id for consistency
                config["configurable"]["user_id"] = user_id

        stream_id = configurable.get("stream_id")  # Extract stream_id for cancellation

        # Resolve subagent and get graph
        (
            subagent_graph,
            resolved_agent_name,
            int_id_or_error,
            is_custom,
        ) = await _resolve_subagent(subagent_id, user_id)

        if subagent_graph is None or resolved_agent_name is None or int_id_or_error is None:
            return int_id_or_error or "Unknown error resolving subagent"

        agent_name: str = resolved_agent_name
        int_id: str = int_id_or_error
        log.set(
            subagent={
                "name": agent_name,
                "provider": int_id,
                "is_custom": is_custom,
                "task_length": len(task),
            }
        )

        # Build config
        thread_id = configurable.get("thread_id", "")
        subagent_thread_id = f"{int_id}_{thread_id}"

        user = {
            "user_id": user_id,
            "email": configurable.get("email"),
            "name": configurable.get("user_name"),
        }
        user_time_str = configurable.get("user_time", "")
        user_time = datetime.fromisoformat(user_time_str) if user_time_str else datetime.now()

        subagent_config = build_agent_config(
            conversation_id=thread_id,
            user=user,
            user_time=user_time,
            thread_id=subagent_thread_id,
            base_configurable=configurable,
            agent_name=agent_name,
            subagent_id=agent_name,
        )
        new_configurable = subagent_config.get("configurable", {})

        # Create system message
        system_message = await create_subagent_system_message(
            integration_id=int_id,
            agent_name=agent_name,
            user_id=user_id,
        )

        # Avoid passing Gaia display name as a service username
        provider_meta = None
        provider_name = None
        platform_subagent = get_subagent_by_id(int_id)
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
            provider_hint=(provider_name or int_id),
            service_username=service_username,
        )

        # Build messages using shared helper (includes context message - fixes the bug!)
        messages = await build_initial_messages(
            system_message=system_message,
            agent_name=agent_name,
            configurable=new_configurable,
            task=sanitized_task,
            user_id=user_id,
            subagent_id=agent_name,
        )

        # Create execution context with stream_id for cancellation
        ctx = SubagentExecutionContext(
            subagent_graph=subagent_graph,
            agent_name=agent_name,
            config=subagent_config,
            configurable=new_configurable,
            integration_id=int_id,
            initial_state={
                "messages": messages,
                "todos": [],
                "intent": sanitized_task,
                "integration_usernames": integration_usernames,
            },
            user_id=user_id,
            stream_id=stream_id,
        )

        integration_metadata = await _build_integration_metadata(is_custom, int_id)

        # Background mode: spawn subagent as asyncio task and return immediately.
        # Caller must use wait_for_subagents() to collect results.
        #
        # Requires stream_id to be propagated into the executor configurable so
        # the result can be routed back via _bg_subagent_results[stream_id].
        if background:
            if not stream_id:
                log.warning(
                    "handoff background=True but stream_id is missing — "
                    "falling back to blocking execution"
                )
                blocking_result = await _run_blocking_handoff(
                    ctx, integration_metadata, agent_name, int_id
                )
                return (
                    "[WARNING: background handoff fell back to blocking — "
                    "stream_id not propagated into executor configurable] "
                    f"{blocking_result}"
                )
            sid: str = str(stream_id)
            bg_sa_id = str(uuid4())
            bg_display, bg_icon, bg_cat = _resolve_display_metadata(
                integration_metadata, agent_name, int_id
            )
            increment_pending_subagents(sid)
            bg_task = asyncio.create_task(
                run_subagent_background(
                    ctx=ctx,
                    stream_id=sid,
                    integration_metadata=integration_metadata,
                    subagent_id=bg_sa_id,
                    display_name=bg_display,
                    tool_category=bg_cat,
                    icon_url=bg_icon,
                )
            )
            _background_subagent_tasks.add(bg_task)
            bg_task.add_done_callback(_background_subagent_tasks.discard)
            log.info(f"Subagent {agent_name} dispatched to background for stream {sid}")
            return (
                f"Subagent {agent_name} started in background. "
                "Call wait_for_subagents() when ready to collect results."
            )

        # Blocking (default): execute synchronously and return result.
        return await _run_blocking_handoff(ctx, integration_metadata, agent_name, int_id)

    except Exception as e:
        log.error(
            "handoff_failed",
            subagent_id=subagent_id,
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e)[:500],
            exc_info=True,
        )
        return f"Error executing task: {e!s}"
