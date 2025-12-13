"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Now supports both legacy subagent architecture and new plan-and-execute subgraphs.
"""

import asyncio
from typing import Any

from app.agents.llm.client import init_llm
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.langchain.core.subgraphs.github_subgraph import create_github_subgraph
from app.langchain.core.subgraphs.gmail_subgraph import create_gmail_subgraph
from app.langchain.core.subgraphs.hubspot_subgraph import create_hubspot_subgraph
from langchain_core.language_models import LanguageModelLike

from .base_subagent import SubAgentFactory


class ProviderSubAgents:
    """Factory for creating and managing provider-specific sub-agent graphs."""

    @staticmethod
    async def create_agent(
        provider_id: str,
        llm: LanguageModelLike,
        use_direct_tools: bool = False,
        disable_retrieve_tools: bool = False,
    ):
        """
        Generic function to create any provider agent using integration config.

        Args:
            provider_id: The provider ID to look up in integrations
            llm: Language model to use
            use_direct_tools: Whether to bind all tools directly
            disable_retrieve_tools: Whether to disable retrieve_tools functionality

        Returns:
            Compiled provider sub-agent graph
        """
        integration = get_integration_by_id(provider_id)
        if not integration or not integration.subagent_config:
            raise ValueError(f"{provider_id} integration or subagent config not found")
        config = integration.subagent_config

        logger.info(
            f"Creating {config.agent_name or f'{provider_id}_agent'} "
            f"using tool space: {config.tool_space or provider_id}"
        )

        graph = await SubAgentFactory.create_provider_subagent(
            provider=integration.provider,
            llm=llm,
            tool_space=config.tool_space,
            name=config.agent_name,
            use_direct_tools=use_direct_tools,
            disable_retrieve_tools=disable_retrieve_tools,
        )

        return {config.agent_name: graph}

    @staticmethod
    async def create_gmail_agent(llm: LanguageModelLike):
        """
        Create a clean Gmail agent with simple plan-and-execute flow.

        Args:
            llm: Language model to use

        Returns:
            Compiled Gmail agent
        """
        logger.info("Creating clean Gmail plan-and-execute subgraph")
        gmail_agent = await create_gmail_subgraph(llm=llm)
        logger.info("Gmail subgraph created successfully")
        return gmail_agent

    @staticmethod
    async def create_github_agent(llm: LanguageModelLike):
        """
        Create a clean GitHub agent with plan-and-execute flow.

        Args:
            llm: Language model to use

        Returns:
            Compiled GitHub agent
        """
        logger.info("Creating clean GitHub plan-and-execute subgraph")
        github_agent = await create_github_subgraph(llm=llm)
        logger.info("GitHub subgraph created successfully")
        return github_agent

    @staticmethod
    async def create_hubspot_agent(llm: LanguageModelLike):
        """
        Create a clean HubSpot agent with plan-and-execute flow.

        Args:
            llm: Language model to use

        Returns:
            Compiled HubSpot agent
        """
        logger.info("Creating clean HubSpot plan-and-execute subgraph")
        hubspot_agent = await create_hubspot_subgraph(llm=llm)
        logger.info("HubSpot subgraph created successfully")
        return hubspot_agent

    @staticmethod
    async def get_all_subagents() -> dict[str, Any]:
        """
        Create all provider-specific sub-agent graphs.

        Returns:
            Dictionary of compiled sub-agent graphs
        """
        llm = init_llm()

        results = await asyncio.gather(
            ProviderSubAgents.create_gmail_agent(llm),
            ProviderSubAgents.create_agent(
                "google_calendar",
                llm,
                use_direct_tools=True,
                disable_retrieve_tools=True,
            ),
            ProviderSubAgents.create_agent("notion", llm),
            ProviderSubAgents.create_agent("twitter", llm),
            ProviderSubAgents.create_agent("linkedin", llm),
            ProviderSubAgents.create_github_agent(llm),
            ProviderSubAgents.create_agent("reddit", llm),
            ProviderSubAgents.create_agent("airtable", llm),
            ProviderSubAgents.create_agent("linear", llm),
            ProviderSubAgents.create_agent("slack", llm),
            ProviderSubAgents.create_hubspot_agent(llm),
            ProviderSubAgents.create_agent("googletasks", llm),
            ProviderSubAgents.create_agent("googlesheets", llm),
            ProviderSubAgents.create_agent("todoist", llm),
            ProviderSubAgents.create_agent("googlemeet", llm),
            ProviderSubAgents.create_agent("google_maps", llm),
            ProviderSubAgents.create_agent("asana", llm),
            ProviderSubAgents.create_agent("trello", llm),
            ProviderSubAgents.create_agent("clickup", llm),
            ProviderSubAgents.create_agent("instagram", llm),
        )

        subagents = {}
        for result in results:
            subagents.update(result)

        return subagents
