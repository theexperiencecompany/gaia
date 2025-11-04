"""
Provider-specific sub-agent implementations.

This module contains the factory methods for creating specialized sub-agent graphs
for different providers (Gmail, Notion, Twitter, LinkedIn, etc.) with full tool
registry and retrieval capabilities.

Now supports both legacy subagent architecture and new plan-and-execute subgraphs.
"""

import asyncio
from typing import Any

from app.agents.prompts.subagent_prompts import (
    CALENDAR_AGENT_SYSTEM_PROMPT,
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.subgraphs.gmail_subgraph import create_gmail_subgraph
from langchain_core.language_models import LanguageModelLike

from .base_subagent import SubAgentFactory


class ProviderSubAgents:
    """Factory for creating and managing provider-specific sub-agent graphs."""

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
    async def create_notion_agent(llm: LanguageModelLike):
        """
        Create a specialized Notion agent graph using tool registry filtering.

        Args:
            llm: Language model to use
            user_id: Optional user ID for tool context

        Returns:
            Compiled Notion sub-agent graph
        """
        logger.info("Creating Notion sub-agent graph using general tool space")

        # Create the Notion agent graph using entire tool registry with space filtering
        notion_agent = await SubAgentFactory.create_provider_subagent(
            provider="notion",
            llm=llm,
            tool_space="notion",
            name="notion_agent",
            prompt=NOTION_AGENT_SYSTEM_PROMPT,
        )

        return notion_agent

    @staticmethod
    async def create_twitter_agent(llm: LanguageModelLike):
        """
        Create a specialized Twitter agent graph using tool registry filtering.

        Args:
            llm: Language model to use
            user_id: Optional user ID for tool context

        Returns:
            Compiled Twitter sub-agent graph
        """
        logger.info("Creating Twitter sub-agent graph using general tool space")

        # Create the Twitter agent graph using entire tool registry with space filtering
        twitter_agent = await SubAgentFactory.create_provider_subagent(
            provider="twitter",
            llm=llm,
            tool_space="twitter",
            name="twitter_agent",
            prompt=TWITTER_AGENT_SYSTEM_PROMPT,
        )

        return twitter_agent

    @staticmethod
    async def create_linkedin_agent(llm: LanguageModelLike):
        """
        Create a specialized LinkedIn agent graph using tool registry filtering.

        Args:
            llm: Language model to use
            user_id: Optional user ID for tool context

        Returns:
            Compiled LinkedIn sub-agent graph
        """
        logger.info("Creating LinkedIn sub-agent graph using general tool space")

        # Create the LinkedIn agent graph using entire tool registry with space filtering
        linkedin_agent = await SubAgentFactory.create_provider_subagent(
            provider="linkedin",
            llm=llm,
            tool_space="linkedin",
            name="linkedin_agent",
            prompt=LINKEDIN_AGENT_SYSTEM_PROMPT,
        )

        return linkedin_agent

    @staticmethod
    async def create_calendar_agent(llm: LanguageModelLike):
        """
        Create a specialized Calendar agent with direct tool binding.

        Calendar has only 7 tools, so we bind them all directly instead of using retrieve_tools.
        This provides better performance and ensures all calendar tools are always available.

        Args:
            llm: Language model to use

        Returns:
            Compiled Calendar sub-agent graph
        """
        logger.info("Creating Calendar sub-agent graph with direct tool binding")

        # Create the Calendar agent graph with direct tool binding
        calendar_agent = await SubAgentFactory.create_provider_subagent(
            provider="calendar",
            llm=llm,
            tool_space="calendar",
            name="calendar_agent",
            prompt=CALENDAR_AGENT_SYSTEM_PROMPT,
            use_direct_tools=True,  # Bind all 7 calendar tools directly
            disable_retrieve_tools=True,  # Disable retrieve_tools functionality
        )

        return calendar_agent


    @staticmethod
    async def get_all_subagents(
        llm: LanguageModelLike, user_id: str | None = None
    ) -> dict[str, Any]:
        """
        Create all provider-specific sub-agent graphs, including MCP servers if user_id provided.

        Args:
            llm: Language model to use
            user_id: Optional user ID for MCP server subagents

        Returns:
            Dictionary of compiled sub-agent graphs
        """
        results = await asyncio.gather(
            ProviderSubAgents.create_gmail_agent(llm),
            ProviderSubAgents.create_notion_agent(llm),
            ProviderSubAgents.create_twitter_agent(llm),
            ProviderSubAgents.create_linkedin_agent(llm),
            ProviderSubAgents.create_calendar_agent(llm),
        )

        subagents = {
            "gmail_agent": results[0],
            "notion_agent": results[1],
            "twitter_agent": results[2],
            "linkedin_agent": results[3],
            "calendar_agent": results[4],
        }

        return subagents
