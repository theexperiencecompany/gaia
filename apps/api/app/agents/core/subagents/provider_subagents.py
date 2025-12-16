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

    Args:
        integration_id: The integration ID from oauth_config

    Returns:
        Compiled subagent graph
    """
    integration = get_integration_by_id(integration_id)
    if not integration or not integration.subagent_config:
        raise ValueError(f"{integration_id} integration or subagent config not found")

    config = integration.subagent_config

    toolkit_name = (
        integration.composio_config.toolkit if integration.composio_config else None
    )

    if toolkit_name:
        tool_registry = await get_tool_registry()
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


def register_subagent_providers(integration_ids: Optional[list[str]] = None) -> int:
    """
    Register lazy providers for subagents from oauth_config.
    Subagents are created on-demand when first accessed via providers.

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
