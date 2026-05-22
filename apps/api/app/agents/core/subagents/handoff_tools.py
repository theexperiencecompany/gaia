"""
Subagent Tools - Consolidated Delegation Pattern

This module provides two tools for subagent delegation:
1. search_subagents - Semantic search for available subagents
2. handoff - Generic handoff tool that delegates to any subagent

Subagents are lazy-loaded on first invocation via providers.aget().
Subagent identity/metadata comes from agents/core/subagents/registry.py
(unified view of OAuth-derived + builtin subagents).
"""

from datetime import datetime
import re
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.store.base import BaseStore, PutOp

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
from app.services.integrations.integration_resolver import IntegrationResolver
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.oauth.oauth_service import (
    check_integration_status,
)
from app.services.provider_metadata_service import get_provider_metadata
from app.utils.agent_utils import parse_subagent_id
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

        return f"Integration {subagent.name} is not connected. Please connect it first."

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
            return (
                None,
                None,
                (
                    f"Error: {agent_name} requires OAuth connection. "
                    f"Please connect {subagent.name} first via settings."
                ),
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
) -> str:
    """Delegate a task to a specialized subagent.

    Use this tool to hand off tasks to expert subagents that specialize in specific domains.
    First use retrieve_tools to find available subagents (they appear with 'subagent:' prefix).

    The subagent will:
    1. Process the task using its specialized tools
    2. Return the result of the completed task

    Args:
        subagent_id: ID of the subagent from retrieve_tools (e.g., 'subagent:gmail', 'gmail')
        task: Complete task description with all necessary context
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

        # Type assertion after null check - these are guaranteed to be str at this point
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

        writer = get_stream_writer()

        integration_metadata = None
        if is_custom:
            custom_meta = await _get_subagent_by_id(int_id)
            if isinstance(custom_meta, dict):
                integration_metadata = {
                    "icon_url": custom_meta.get("icon_url"),
                    "integration_id": int_id,
                    "name": str(custom_meta.get("name", int_id)),
                }
        else:
            platform_subagent = get_subagent_by_id(int_id)
            if platform_subagent:
                integration_metadata = {
                    "icon_url": None,
                    "integration_id": int_id,
                    "name": platform_subagent.name,
                }

        # Execute using shared streaming function
        # Note: handoff tool_data is emitted by parent graph's updates stream
        return await execute_subagent_stream(
            ctx=ctx,
            stream_writer=writer,
            integration_metadata=integration_metadata,
        )

    except Exception as e:
        log.error(f"Error in handoff to {subagent_id}: {e}", exc_info=True)
        return f"Error executing task: {e!s}"
