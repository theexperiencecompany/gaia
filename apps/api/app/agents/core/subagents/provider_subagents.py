"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Subagents are lazy-loaded on first access via providers.
Configuration comes from the subagent registry (OAuth-derived + builtins).
Tools are registered on-demand when subagent is first created.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.agents.core.subagents.registry import all_subagents, get_subagent_by_id
from app.agents.llm.client import init_llm
from app.agents.tools.core.registry import get_tool_registry
from app.config.oauth_config import get_integration_by_id
from app.core.lazy_loader import providers
from app.db.mongodb.collections import integrations_collection
from app.helpers.namespace_utils import derive_integration_namespace
from app.models.subagent_models import Subagent
from app.services.mcp.mcp_client import get_mcp_client
from shared.py.wide_events import log

from .base_subagent import SubAgentFactory

# In-memory cache for per-user subagent graphs.
#
# **Why in-memory (not Redis)?** Values are compiled LangGraph objects that
# embed ``functools.partial`` closures, bound-method references, and live
# Pydantic models. These are NOT pickleable. Process-local memo is the only
# viable option.
#
# Keyed by ``(integration_id, user_id)``. Invalidated on process restart,
# explicit calls to ``invalidate_user_subagent_cache()``, or MCP config
# change (callers must invalidate explicitly).
_USER_SUBAGENT_CACHE: dict[tuple[str, str], CompiledStateGraph] = {}
_USER_SUBAGENT_LOCK = asyncio.Lock()


def invalidate_user_subagent_cache(integration_id: str, user_id: str | None = None) -> None:
    """Drop cached subagent graphs for a given integration.

    If user_id is None, invalidates every user's graph for that integration
    (useful when an MCP config changes globally).
    """
    if user_id is not None:
        _USER_SUBAGENT_CACHE.pop((integration_id, user_id), None)
        return
    for key in list(_USER_SUBAGENT_CACHE.keys()):
        if key[0] == integration_id:
            _USER_SUBAGENT_CACHE.pop(key, None)


async def create_subagent(subagent: Subagent) -> CompiledStateGraph:
    """
    Create a provider subagent graph on-demand.
    Registers provider tools to registry if not already present.

    Note: For auth-required MCP integrations, use create_subagent_for_user instead.

    Args:
        subagent: The Subagent to materialize a graph for

    Returns:
        Compiled subagent graph
    """
    config = subagent.config
    tool_registry = await get_tool_registry()

    # Handle internal integrations (like todos) - tools are already registered
    if subagent.managed_by == "internal":
        # Internal integrations use core tools that are registered at startup
        # No additional setup needed - tools are already in the registry
        log.info(f"Internal integration {subagent.id}: using pre-registered tools")

    # Handle MCP-managed integrations (like DeepWiki)
    elif subagent.managed_by == "mcp" and subagent.mcp_config:
        mcp_config = subagent.mcp_config
        category_name = subagent.id

        # Skip auth-required MCPs here - they need user-specific tokens
        # loaded via create_subagent_for_user() with actual user_id
        if mcp_config.requires_auth:
            raise ValueError(
                f"{subagent.id} requires authentication - use create_subagent_for_user"
            )
        if category_name not in tool_registry._categories:
            mcp_client = await get_mcp_client(user_id="_system")
            tools = await mcp_client.connect(subagent.id)
            if tools:
                tool_registry._add_category(
                    name=category_name,
                    tools=tools,
                    space=config.tool_space,
                    integration_name=subagent.id,
                )
                await tool_registry._index_category_tools(category_name)
                log.info(f"Registered {len(tools)} MCP tools for {subagent.id}")

    # Handle Composio-managed integrations
    # `Subagent` does not carry composio_config; look up the OAuth integration
    # for this branch (composio is OAuth-only). The OAuthIntegration model
    # validator enforces composio_config when managed_by="composio", so the
    # only way to land here without one is a builtin Subagent declaring
    # managed_by="composio" — which would silently produce a tool-less agent.
    # Fail loudly instead.
    elif subagent.managed_by == "composio":
        integration = get_integration_by_id(subagent.id)
        if integration is None or integration.composio_config is None:
            raise ValueError(
                f"Composio subagent {subagent.id!r} has no matching OAuth "
                f"integration with composio_config. managed_by='composio' "
                f"must correspond to an OAUTH_INTEGRATIONS entry."
            )
        toolkit_name = integration.composio_config.toolkit
        await tool_registry.register_provider_tools(
            toolkit_name=toolkit_name,
            space_name=config.tool_space,
            specific_tools=config.specific_tools,
        )

    llm = init_llm()

    log.set(subagent={"name": config.agent_name, "provider": subagent.provider})
    log.info(f"Creating {config.agent_name} on-demand using tool space: {config.tool_space}")

    graph = await SubAgentFactory.create_provider_subagent(
        provider=subagent.provider,
        llm=llm,
        tool_space=config.tool_space,
        name=config.agent_name,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
        auto_bind_tools=config.auto_bind_tools,
        include_finish_task=config.include_finish_task,
    )

    log.info(f"Subagent {config.agent_name} created successfully")
    return graph


async def create_subagent_for_user(integration_id: str, user_id: str) -> CompiledStateGraph | None:
    """
    Create (or retrieve from in-memory cache) a per-user subagent graph.

    The compiled graph is memoised in-process keyed by
    ``(integration_id, user_id)`` so repeat handoffs skip the expensive
    MCP-connect + ChromaDB-indexing rebuild. Invalidation happens on:
      - process restart
      - ``invalidate_user_subagent_cache(integration_id, user_id=?)``
      - MCP config change (callers must invalidate explicitly)
    """
    cache_key = (integration_id, user_id)
    cached = _USER_SUBAGENT_CACHE.get(cache_key)
    if cached is not None:
        log.set(
            subagent_graph_cache={
                "integration_id": integration_id,
                "user_id": user_id,
                "outcome": "hit",
            }
        )
        return cached

    async with _USER_SUBAGENT_LOCK:
        # Double-check: another task may have populated while we waited.
        cached = _USER_SUBAGENT_CACHE.get(cache_key)
        if cached is not None:
            log.set(
                subagent_graph_cache={
                    "integration_id": integration_id,
                    "user_id": user_id,
                    "outcome": "hit_after_wait",
                }
            )
            return cached

        graph = await _build_user_subagent(integration_id, user_id)
        if graph is not None:
            _USER_SUBAGENT_CACHE[cache_key] = graph
        log.set(
            subagent_graph_cache={
                "integration_id": integration_id,
                "user_id": user_id,
                "outcome": "miss_built" if graph is not None else "miss_failed",
            }
        )
        return graph


async def _build_user_subagent(integration_id: str, user_id: str) -> CompiledStateGraph | None:
    """Build a per-user subagent graph from scratch (called on cache miss).

    Used for:
    - MCP integrations (platform) that require OAuth authentication
    - Custom MCP integrations created by users
    """
    subagent = get_subagent_by_id(integration_id)

    # Handle custom MCPs from MongoDB (not in registry)
    # Custom MCPs can have either "custom_" prefix or 12-char hex IDs
    if not subagent:
        return await _create_custom_mcp_subagent(integration_id, user_id)

    mcp_config = subagent.mcp_config
    if not (subagent.managed_by == "mcp" and mcp_config):
        log.error(f"{integration_id} is not an MCP integration")
        return None

    config = subagent.config
    tool_registry = await get_tool_registry()

    # Use user-specific category name to avoid conflicts
    category_name = f"mcp_{subagent.id}_{user_id}"

    if category_name not in tool_registry._categories:
        mcp_client = await get_mcp_client(user_id=user_id)

        # Fast path: connect ONLY the needed integration instead of all
        if subagent.id in mcp_client._tools:
            tools = mcp_client._tools[subagent.id]
            log.info(
                f"_build_user_subagent: integration={integration_id} user={user_id} "
                f"using cached in-memory tools ({len(tools)})"
            )
        else:
            try:
                tools = await mcp_client.connect(subagent.id)
                log.info(
                    f"_build_user_subagent: integration={integration_id} user={user_id} "
                    f"connected MCP, got {len(tools)} tools"
                )
            except Exception as e:
                log.error(
                    f"_build_user_subagent: integration={integration_id} user={user_id} "
                    f"connect FAILED: {type(e).__name__}: {e}"
                )
                return None

        if not tools:
            log.error(
                f"_build_user_subagent: integration={integration_id} user={user_id} "
                f"got 0 tools — cannot create subagent"
            )
            return None

        # Background: warm up other integrations for future handoffs
        asyncio.create_task(mcp_client.get_all_connected_tools())

        log.set(
            subagent_register={
                "integration_id": integration_id,
                "user_id": user_id,
                "category_name": category_name,
                "tool_space": config.tool_space,
                "tools_count": len(tools),
            }
        )
        tool_registry._add_category(
            name=category_name,
            tools=tools,
            space=config.tool_space,
            integration_name=subagent.id,
        )
        await tool_registry._index_category_tools(category_name)
        log.info(
            f"_build_user_subagent: registered {len(tools)} user-specific MCP tools "
            f"for {integration_id} user={user_id} category={category_name} "
            f"space={config.tool_space}"
        )

    llm = init_llm()

    log.set(subagent={"name": config.agent_name, "provider": subagent.provider})
    log.info(
        f"Creating {config.agent_name} for user {user_id} using tool space: {config.tool_space}"
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=subagent.provider,
        llm=llm,
        tool_space=config.tool_space,
        name=config.agent_name,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
        auto_bind_tools=config.auto_bind_tools,
        include_finish_task=config.include_finish_task,
    )

    log.info(f"User-specific subagent {config.agent_name} created successfully")
    return graph


async def _create_custom_mcp_subagent(
    integration_id: str, user_id: str
) -> CompiledStateGraph | None:
    """
    Create a subagent graph for a custom MCP integration from MongoDB.

    Custom MCPs don't have static SubAgentConfig in the registry.
    They use the universal prompt and have all their tools loaded directly.

    Args:
        integration_id: The custom integration ID (starts with 'custom_')
        user_id: The user's ID for token lookup and tool loading

    Returns:
        Compiled subagent graph, or None if creation fails
    """
    # Fetch custom integration from MongoDB
    custom_doc = await integrations_collection.find_one({"integration_id": integration_id})
    if not custom_doc:
        log.error(f"Custom integration {integration_id} not found in MongoDB")
        return None

    tool_registry = await get_tool_registry()

    # Use user-specific category name to avoid conflicts
    category_name = f"mcp_{integration_id}_{user_id}"
    tools: list[Any] | None = None  # Track tools for count-based strategy decision
    tool_namespace: str = ""  # Will be set in either branch below

    # Derive namespace upfront from mcp_config (needed regardless of cache branch)
    mcp_config = custom_doc.get("mcp_config", {})
    server_url = mcp_config.get("server_url", "")
    tool_namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    if category_name not in tool_registry._categories:
        mcp_client = await get_mcp_client(user_id=user_id)

        # Fast path: connect ONLY the needed integration instead of all
        if integration_id in mcp_client._tools:
            tools = mcp_client._tools[integration_id]
        else:
            try:
                tools = await mcp_client.connect(integration_id)
            except Exception as e:
                log.error(f"Failed to get MCP tools for {integration_id}: {e}")
                return None

        if not tools:
            log.error(f"No tools available for {integration_id}")
            return None

        # Background: warm up other integrations for future handoffs
        asyncio.create_task(mcp_client.get_all_connected_tools())

        tool_registry._add_category(
            name=category_name,
            tools=tools,
            space=tool_namespace,  # Use URL domain to match mcp_client.py indexing
            integration_name=integration_id,
        )
        await tool_registry._index_category_tools(category_name)
        log.info(
            f"Registered {len(tools)} custom MCP tools for {integration_id} in namespace '{tool_namespace}'"
        )
    else:
        # Category exists - get tool count and namespace from registry
        category = tool_registry.get_category(category_name)
        if category:
            tools = category.tools
            tool_namespace = category.space

    if not tool_namespace:
        # Fallback: derive namespace if not set from either branch
        mcp_cfg = custom_doc.get("mcp_config", {})
        tool_namespace = derive_integration_namespace(
            integration_id, mcp_cfg.get("server_url", ""), is_custom=True
        )

    llm = init_llm()
    agent_name = f"custom_mcp_{integration_id}"

    log.set(subagent={"name": agent_name, "provider": integration_id})
    log.info(f"Creating custom MCP subagent {agent_name} for user {user_id}")

    # Dynamic tool-count override: if actual tool count is small (1-10),
    # bind all tools directly and skip retrieve_tools for lower latency.
    tool_count = len(tools) if tools else 0
    use_direct = 0 < tool_count <= 10

    log.info(
        f"Custom MCP {integration_id} has {tool_count} tools - "
        f"using {'direct binding' if use_direct else 'retrieve_tools'}"
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration_id,
        llm=llm,
        tool_space=tool_namespace,
        name=agent_name,
        use_direct_tools=use_direct,
        disable_retrieve_tools=use_direct,
    )

    log.info(f"Custom MCP subagent {agent_name} created successfully")
    return graph


def _make_subagent_loader(
    subagent: Subagent,
) -> Callable[[], Awaitable[CompiledStateGraph]]:
    """Bind the subagent into a zero-arg async loader for `providers.register`."""

    async def _loader() -> CompiledStateGraph:
        return await create_subagent(subagent)

    return _loader


def register_subagent_providers(integration_ids: list[str] | None = None) -> int:
    """
    Register lazy providers for all subagents (OAuth-derived + builtins).
    Subagents are created on-demand when first accessed via providers.

    Note: Auth-required MCP subagents are NOT registered here - they are created
    on-the-fly via create_subagent_for_user() when the handoff tool is invoked.

    Args:
        integration_ids: Optional list of specific subagent IDs to register.
                        If None, registers all subagents.

    Returns:
        Number of registered subagent providers.
    """
    registered_count = 0

    for subagent in all_subagents():
        # Skip if not in the requested list (when list is provided)
        if integration_ids is not None and subagent.id not in integration_ids:
            continue

        # Skip auth-required MCP integrations - they are created on-the-fly
        # via create_subagent_for_user() when the handoff tool is invoked
        if (
            subagent.managed_by == "mcp"
            and subagent.mcp_config
            and subagent.mcp_config.requires_auth
        ):
            log.info(
                f"Auth-required MCP subagent {subagent.config.agent_name} "
                f"will be created on-demand via handoff"
            )
            continue

        agent_name = subagent.config.agent_name

        # mypy can't solve TypeVar T on the Union loader signature
        # against a concrete async function; cast keeps the loader's
        # actual return type while satisfying the registry overload.
        providers.register(
            name=agent_name,
            loader_func=_make_subagent_loader(subagent),  # type: ignore[arg-type]
            required_keys=[],
        )
        registered_count += 1

    log.info(f"Registered {registered_count} subagent lazy providers")
    return registered_count
