"""Google Calendar plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.calendar_node_prompts import (
    CALENDAR_MANAGEMENT_PROMPT,
    EVENT_MANAGEMENT_PROMPT,
    EVENT_RETRIEVAL_PROMPT,
    SCHEDULING_TOOLS_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    OrchestratorNodeConfig,
    OrchestratorSubgraphConfig,
    build_orchestrator_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of Google Calendar node configurations."""
    composio_service = get_composio_service()

    (
        event_management_tools,
        event_retrieval_tools,
        calendar_management_tools,
        scheduling_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(
            [
                "GOOGLECALENDAR_CREATE_EVENT",
                "GOOGLECALENDAR_QUICK_ADD",
                "GOOGLECALENDAR_UPDATE_EVENT",
                "GOOGLECALENDAR_PATCH_EVENT",
                "GOOGLECALENDAR_DELETE_EVENT",
                "GOOGLECALENDAR_EVENTS_MOVE",
                "GOOGLECALENDAR_REMOVE_ATTENDEE",
            ],
        ),
        composio_service.get_tools_by_name(
            [
                "GOOGLECALENDAR_EVENTS_LIST",
                "GOOGLECALENDAR_FIND_EVENT",
                "GOOGLECALENDAR_EVENTS_INSTANCES",
                "GOOGLECALENDAR_GET_CURRENT_DATE_TIME",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GOOGLECALENDAR_LIST_CALENDARS",
                "GOOGLECALENDAR_GET_CALENDAR",
                "GOOGLECALENDAR_CALENDARS_UPDATE",
                "GOOGLECALENDAR_PATCH_CALENDAR",
                "GOOGLECALENDAR_CALENDARS_DELETE",
                "GOOGLECALENDAR_DUPLICATE_CALENDAR",
                "GOOGLECALENDAR_CLEAR_CALENDAR",
                "GOOGLECALENDAR_LIST_ACL_RULES",
                "GOOGLECALENDAR_UPDATE_ACL_RULE",
                "GOOGLECALENDAR_ACL_PATCH",
                "GOOGLECALENDAR_CALENDAR_LIST_INSERT",
                "GOOGLECALENDAR_CALENDAR_LIST_UPDATE",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GOOGLECALENDAR_FIND_FREE_SLOTS",
                "GOOGLECALENDAR_FREE_BUSY_QUERY",
                "GOOGLECALENDAR_GET_CURRENT_DATE_TIME",
                "GOOGLECALENDAR_SETTINGS_LIST",
                "GOOGLECALENDAR_SYNC_EVENTS",
            ]
        ),
    )

    return (
        OrchestratorNodeConfig(
            name="event_management",
            description="Create, update, delete, and manage calendar events with proper time zones and recurrence",
            system_prompt=EVENT_MANAGEMENT_PROMPT,
            tools=event_management_tools,
        ),
        OrchestratorNodeConfig(
            name="event_retrieval",
            description="Search, list, and find calendar events with various filters and time ranges",
            system_prompt=EVENT_RETRIEVAL_PROMPT,
            tools=event_retrieval_tools,
        ),
        OrchestratorNodeConfig(
            name="calendar_management",
            description="Manage calendars, access control, and calendar settings",
            system_prompt=CALENDAR_MANAGEMENT_PROMPT,
            tools=calendar_management_tools,
        ),
        OrchestratorNodeConfig(
            name="scheduling_tools",
            description="Find free time slots, check availability, and optimize scheduling",
            system_prompt=SCHEDULING_TOOLS_PROMPT,
            tools=scheduling_tools,
        ),
    )


async def create_calendar_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the Google Calendar sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating Google Calendar subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="Google Calendar",
        agent_name="calendar_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("Google Calendar subgraph created successfully")

    return graph
