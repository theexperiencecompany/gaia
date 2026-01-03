"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Subagents are lazy-loaded on first access via providers.
Configuration comes from oauth_config.py OAUTH_INTEGRATIONS.
Tools are registered on-demand when subagent is first created.
"""

from typing import Optional

from app.agents.llm.client import init_llm
from app.agents.tools.core.registry import get_tool_registry
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS, get_integration_by_id
from app.core.lazy_loader import providers

from .base_subagent import SubAgentFactory


async def create_subagent(integration_id: str):
    """
    Create a provider subagent graph on-demand.
    Registers provider tools to registry if not already present.

    Note: For auth-required MCP integrations, use create_subagent_for_user instead.

    Args:
        integration_id: The integration ID from oauth_config

    Returns:
        Compiled subagent graph
    """
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.subagent_config:
        raise ValueError(f"{integration_id} integration or subagent config not found")

    config = integration.subagent_config
    tool_registry = await get_tool_registry()

    # Handle MCP-managed integrations (like DeepWiki)
    if integration.managed_by == "mcp" and integration.mcp_config:
        from app.services.mcp.mcp_client import get_mcp_client

        category_name = integration.id

        # Skip auth-required MCPs here - they need user-specific tokens
        # loaded via create_subagent_for_user() with actual user_id
        if integration.mcp_config.requires_auth:
            raise ValueError(
                f"{integration_id} requires authentication - use create_subagent_for_user"
            )
        elif category_name not in tool_registry._categories:
            mcp_client = get_mcp_client(user_id="_system")
            tools = await mcp_client.connect(integration.id)
            if tools:
                tool_registry._add_category(
                    name=category_name,
                    tools=tools,
                    space=config.tool_space,
                    integration_name=integration.id,
                )
                await tool_registry._index_category_tools(category_name)
                logger.info(f"Registered {len(tools)} MCP tools for {integration_id}")

    # Handle Composio-managed integrations
    elif integration.composio_config:
        toolkit_name = integration.composio_config.toolkit
        await tool_registry.register_provider_tools(
            toolkit_name=toolkit_name,
            space_name=config.tool_space,
            specific_tools=config.specific_tools,
        )

    llm = init_llm()

    logger.info(
        f"Creating {config.agent_name} on-demand using tool space: {config.tool_space}"
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration.provider,
        llm=llm,
        tool_space=config.tool_space,
        name=config.agent_name,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
    )

    logger.info(f"Subagent {config.agent_name} created successfully")
    return graph


async def create_subagent_for_user(integration_id: str, user_id: str):
    """
    Create a subagent for auth-required MCP integrations with user-specific tokens.

    This is used for MCP integrations that require OAuth authentication.
    Uses cached tools when available to avoid reconnecting to MCP server.

    Args:
        integration_id: The integration ID from oauth_config
        user_id: The user's ID for token lookup

    Returns:
        Compiled subagent graph, or None if creation fails
    """
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.subagent_config:
        logger.error(f"{integration_id} integration or subagent config not found")
        return None

    if not (integration.managed_by == "mcp" and integration.mcp_config):
        logger.error(f"{integration_id} is not an MCP integration")
        return None

    config = integration.subagent_config
    tool_registry = await get_tool_registry()

    from app.services.mcp.mcp_client import get_mcp_client

    # Use user-specific category name to avoid conflicts
    category_name = f"mcp_{integration.id}_{user_id}"

    if category_name not in tool_registry._categories:
        mcp_client = get_mcp_client(user_id=user_id)

        # get_all_connected_tools uses cached tools when available
        all_tools = await mcp_client.get_all_connected_tools()

        # Defensive check - all_tools should be dict
        if not isinstance(all_tools, dict):
            logger.error(
                f"get_all_connected_tools returned {type(all_tools).__name__} instead of dict"
            )
            all_tools = {}

        tools = all_tools.get(integration.id)

        if not tools:
            # Try direct connect as fallback
            try:
                tools = await mcp_client.connect(integration.id)
            except Exception as e:
                logger.error(f"Failed to get MCP tools for {integration_id}: {e}")
                return None

        if not tools:
            logger.error(f"No tools available for {integration_id}")
            return None

        tool_registry._add_category(
            name=category_name,
            tools=tools,
            space=config.tool_space,
            integration_name=integration.id,
        )
        await tool_registry._index_category_tools(category_name)
        logger.info(
            f"Registered {len(tools)} user-specific MCP tools for {integration_id}"
        )

    llm = init_llm()

    logger.info(
        f"Creating {config.agent_name} for user {user_id} using tool space: {config.tool_space}"
    )

    graph = await SubAgentFactory.create_provider_subagent(
        provider=integration.provider,
        llm=llm,
        tool_space=config.tool_space,
        name=config.agent_name,
        use_direct_tools=config.use_direct_tools,
        disable_retrieve_tools=config.disable_retrieve_tools,
    )

    logger.info(f"User-specific subagent {config.agent_name} created successfully")
    return graph


def register_subagent_providers(integration_ids: Optional[list[str]] = None) -> int:
    """
    Register lazy providers for subagents from oauth_config.
    Subagents are created on-demand when first accessed via providers.

    Note: Auth-required MCP subagents are NOT registered here - they are created
    on-the-fly via create_subagent_for_user() when the handoff tool is invoked.

    Args:
        integration_ids: Optional list of specific integration IDs to register.
                        If None, registers all subagents.

    Returns:
        Number of registered subagent providers.
    """
    registered_count = 0

    for integration in OAUTH_INTEGRATIONS:
        if (
            not integration.subagent_config
            or not integration.subagent_config.has_subagent
        ):
            continue

        # Skip if not in the requested list (when list is provided)
        if integration_ids is not None and integration.id not in integration_ids:
            continue

        # Skip auth-required MCP integrations - they are created on-the-fly
        # via create_subagent_for_user() when the handoff tool is invoked
        if (
            integration.managed_by == "mcp"
            and integration.mcp_config
            and integration.mcp_config.requires_auth
        ):
            logger.info(
                f"Auth-required MCP subagent {integration.subagent_config.agent_name} "
                f"will be created on-demand via handoff"
            )
            continue

        agent_name = integration.subagent_config.agent_name
        integration_id = integration.id

        async def create_agent_closure(int_id: str = integration_id):
            return await create_subagent(int_id)

        providers.register(
            name=agent_name,
            loader_func=create_agent_closure,
            required_keys=[],
        )
        registered_count += 1

    logger.info(f"Registered {registered_count} subagent lazy providers")
    return registered_count
