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
from app.agents.prompts.subagent_prompts import (
    AIRTABLE_AGENT_SYSTEM_PROMPT,
    ASANA_AGENT_SYSTEM_PROMPT,
    CALENDAR_AGENT_SYSTEM_PROMPT,
    GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
    GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
    GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
    GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
    LINEAR_AGENT_SYSTEM_PROMPT,
    LINKEDIN_AGENT_SYSTEM_PROMPT,
    MICROSOFT_TEAMS_AGENT_SYSTEM_PROMPT,
    NOTION_AGENT_SYSTEM_PROMPT,
    REDDIT_AGENT_SYSTEM_PROMPT,
    SLACK_AGENT_SYSTEM_PROMPT,
    TODOIST_AGENT_SYSTEM_PROMPT,
    TRELLO_AGENT_SYSTEM_PROMPT,
    TWITTER_AGENT_SYSTEM_PROMPT,
    ZOOM_AGENT_SYSTEM_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.subgraphs.github_subgraph import create_github_subgraph
from app.langchain.core.subgraphs.gmail_subgraph import create_gmail_subgraph
from app.langchain.core.subgraphs.hubspot_subgraph import create_hubspot_subgraph
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
    async def create_reddit_agent(llm: LanguageModelLike):
        """Create a specialized Reddit agent graph."""
        logger.info("Creating Reddit sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="reddit",
            llm=llm,
            tool_space="reddit",
            name="reddit_agent",
            prompt=REDDIT_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_airtable_agent(llm: LanguageModelLike):
        """Create a specialized Airtable agent graph."""
        logger.info("Creating Airtable sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="airtable",
            llm=llm,
            tool_space="airtable",
            name="airtable_agent",
            prompt=AIRTABLE_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_linear_agent(llm: LanguageModelLike):
        """Create a specialized Linear agent graph."""
        logger.info("Creating Linear sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="linear",
            llm=llm,
            tool_space="linear",
            name="linear_agent",
            prompt=LINEAR_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_slack_agent(llm: LanguageModelLike):
        """Create a specialized Slack agent graph."""
        logger.info("Creating Slack sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="slack",
            llm=llm,
            tool_space="slack",
            name="slack_agent",
            prompt=SLACK_AGENT_SYSTEM_PROMPT,
        )

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
    async def create_google_tasks_agent(llm: LanguageModelLike):
        """Create a specialized Google Tasks agent graph."""
        logger.info("Creating Google Tasks sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="google_tasks",
            llm=llm,
            tool_space="google_tasks",
            name="google_tasks_agent",
            prompt=GOOGLE_TASKS_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_google_sheets_agent(llm: LanguageModelLike):
        """Create a specialized Google Sheets agent graph."""
        logger.info("Creating Google Sheets sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="google_sheets",
            llm=llm,
            tool_space="google_sheets",
            name="google_sheets_agent",
            prompt=GOOGLE_SHEETS_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_todoist_agent(llm: LanguageModelLike):
        """Create a specialized Todoist agent graph."""
        logger.info("Creating Todoist sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="todoist",
            llm=llm,
            tool_space="todoist",
            name="todoist_agent",
            prompt=TODOIST_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_microsoft_teams_agent(llm: LanguageModelLike):
        """Create a specialized Microsoft Teams agent graph."""
        logger.info("Creating Microsoft Teams sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="microsoft_teams",
            llm=llm,
            tool_space="microsoft_teams",
            name="microsoft_teams_agent",
            prompt=MICROSOFT_TEAMS_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_google_meet_agent(llm: LanguageModelLike):
        """Create a specialized Google Meet agent graph."""
        logger.info("Creating Google Meet sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="google_meet",
            llm=llm,
            tool_space="google_meet",
            name="google_meet_agent",
            prompt=GOOGLE_MEET_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_zoom_agent(llm: LanguageModelLike):
        """Create a specialized Zoom agent graph."""
        logger.info("Creating Zoom sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="zoom",
            llm=llm,
            tool_space="zoom",
            name="zoom_agent",
            prompt=ZOOM_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_google_maps_agent(llm: LanguageModelLike):
        """Create a specialized Google Maps agent graph."""
        logger.info("Creating Google Maps sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="google_maps",
            llm=llm,
            tool_space="google_maps",
            name="google_maps_agent",
            prompt=GOOGLE_MAPS_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_asana_agent(llm: LanguageModelLike):
        """Create a specialized Asana agent graph."""
        logger.info("Creating Asana sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="asana",
            llm=llm,
            tool_space="asana",
            name="asana_agent",
            prompt=ASANA_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def create_trello_agent(llm: LanguageModelLike):
        """Create a specialized Trello agent graph."""
        logger.info("Creating Trello sub-agent graph")
        return await SubAgentFactory.create_provider_subagent(
            provider="trello",
            llm=llm,
            tool_space="trello",
            name="trello_agent",
            prompt=TRELLO_AGENT_SYSTEM_PROMPT,
        )

    @staticmethod
    async def get_all_subagents() -> dict[str, Any]:
        """
        Create all provider-specific sub-agent graphs.

        Args:
            llm: Language model to use

        Returns:
            Dictionary of compiled sub-agent graphs
        """
        llm = init_llm()

        results = await asyncio.gather(
            ProviderSubAgents.create_gmail_agent(llm),
            ProviderSubAgents.create_notion_agent(llm),
            ProviderSubAgents.create_twitter_agent(llm),
            ProviderSubAgents.create_linkedin_agent(llm),
            ProviderSubAgents.create_github_agent(llm),
            ProviderSubAgents.create_reddit_agent(llm),
            ProviderSubAgents.create_airtable_agent(llm),
            ProviderSubAgents.create_linear_agent(llm),
            ProviderSubAgents.create_slack_agent(llm),
            ProviderSubAgents.create_hubspot_agent(llm),
            ProviderSubAgents.create_google_tasks_agent(llm),
            ProviderSubAgents.create_google_sheets_agent(llm),
            ProviderSubAgents.create_todoist_agent(llm),
            ProviderSubAgents.create_microsoft_teams_agent(llm),
            ProviderSubAgents.create_google_meet_agent(llm),
            ProviderSubAgents.create_zoom_agent(llm),
            ProviderSubAgents.create_google_maps_agent(llm),
            ProviderSubAgents.create_asana_agent(llm),
            ProviderSubAgents.create_trello_agent(llm),
        )
        return {
            "gmail_agent": results[0],
            "notion_agent": results[1],
            "twitter_agent": results[2],
            "linkedin_agent": results[3],
            "github_agent": results[4],
            "reddit_agent": results[5],
            "airtable_agent": results[6],
            "linear_agent": results[7],
            "slack_agent": results[8],
            "hubspot_agent": results[9],
            "google_tasks_agent": results[10],
            "google_sheets_agent": results[11],
            "todoist_agent": results[12],
            "microsoft_teams_agent": results[13],
            "google_meet_agent": results[14],
            "zoom_agent": results[15],
            "google_maps_agent": results[16],
            "asana_agent": results[17],
            "trello_agent": results[18],
        }
