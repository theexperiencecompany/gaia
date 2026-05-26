"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Subagents are built on-demand each turn. Per-user MCP tools are read live from
MCPClient (the source of truth) rather than copied into a process-global cache.
"""

from collections.abc import Awaitable, Callable

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
    """Build a per-user subagent graph.

    No memoization — every handoff rebuilds the graph from live MCPClient state.
    The build itself is sub-second; the cost that used to motivate caching
    (MCP connect + Chroma indexing) now lives in MCPClient where it belongs and
    is paid once per worker lifetime per integration.
    """
    return await _build_user_subagent(integration_id, user_id)


async def _build_user_subagent(integration_id: str, user_id: str) -> CompiledStateGraph | None:
    """Build a per-user subagent graph for an MCP integration.

    Pulls live tools from MCPClient. Lazy-connects on first use per integration;
    subsequent builds reuse the warm session. No registry-side state is written
    — tool objects only live inside MCPClient.
    """
    subagent = get_subagent_by_id(integration_id)

    # Custom MCPs from MongoDB (not in static registry) — IDs can be 'custom_'
    # prefixed or 12-char hex.
    if not subagent:
        return await _create_custom_mcp_subagent(integration_id, user_id)

    mcp_config = subagent.mcp_config
    if not (subagent.managed_by == "mcp" and mcp_config):
        log.error(f"{integration_id} is not an MCP integration")
        return None

    config = subagent.config
    mcp_client = await get_mcp_client(user_id=user_id)

    if subagent.id in mcp_client._tools:
        tools = mcp_client._tools[subagent.id]
        log.info(
            f"_build_user_subagent: integration={integration_id} user={user_id} "
            f"using warm MCPClient tools ({len(tools)})"
        )
    else:
        try:
            tools = await mcp_client.connect(subagent.id)
            log.info(
                f"_build_user_subagent: integration={integration_id} user={user_id} "
                f"cold connect, got {len(tools)} tools"
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
        mcp_tools=tools,
    )

    log.info(f"User-specific subagent {config.agent_name} created successfully")
    return graph


async def _create_custom_mcp_subagent(
    integration_id: str, user_id: str
) -> CompiledStateGraph | None:
    """Build a subagent graph for a custom MCP integration from MongoDB.

    Pulls live tools from MCPClient (lazy-connects on first use). Namespace
    derives from the custom integration's server URL.
    """
    custom_doc = await integrations_collection.find_one({"integration_id": integration_id})
    if not custom_doc:
        log.error(f"Custom integration {integration_id} not found in MongoDB")
        return None

    mcp_config = custom_doc.get("mcp_config", {})
    server_url = mcp_config.get("server_url", "")
    tool_namespace = derive_integration_namespace(integration_id, server_url, is_custom=True)

    mcp_client = await get_mcp_client(user_id=user_id)

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

    llm = init_llm()
    agent_name = f"custom_mcp_{integration_id}"

    log.set(subagent={"name": agent_name, "provider": integration_id})

    # Dynamic tool-count override: if actual tool count is small (1-10),
    # bind all tools directly and skip retrieve_tools for lower latency.
    tool_count = len(tools)
    use_direct = 0 < tool_count <= 10

    log.info(
        f"Custom MCP {integration_id} has {tool_count} tools — "
        f"using {'direct binding' if use_direct else 'retrieve_tools'}"
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration_id,
        llm=llm,
        tool_space=tool_namespace,
        name=agent_name,
        use_direct_tools=use_direct,
        disable_retrieve_tools=use_direct,
        mcp_tools=tools,
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
