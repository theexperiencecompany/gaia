"""ClickUp plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.clickup_node_prompts import (
    COLLABORATION_PROMPT,
    GOALS_PROMPT,
    SPACES_FOLDERS_PROMPT,
    TASKS_PROMPT,
    TIME_TRACKING_PROMPT,
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

# Spaces & Folders Management Tools
SPACES_FOLDERS_TOOLS = [
    "CLICKUP_GET_SPACES",
    "CLICKUP_CREATE_SPACE",
    "CLICKUP_GET_SPACE",
    "CLICKUP_UPDATE_SPACE",
    "CLICKUP_DELETE_SPACE",
    "CLICKUP_CREATE_FOLDER",
    "CLICKUP_GET_FOLDERS",
    "CLICKUP_GET_FOLDER",
    "CLICKUP_UPDATE_FOLDER",
    "CLICKUP_DELETE_FOLDER",
    "CLICKUP_CREATE_LIST",
    "CLICKUP_GET_LISTS",
    "CLICKUP_GET_LIST",
    "CLICKUP_UPDATE_LIST",
    "CLICKUP_DELETE_LIST",
    "CLICKUP_CREATE_FOLDERLESS_LIST",
    "CLICKUP_GET_FOLDERLESS_LISTS",
]

# Task Management Tools
TASKS_TOOLS = [
    "CLICKUP_CREATE_TASK",
    "CLICKUP_GET_TASKS",
    "CLICKUP_GET_TASK",
    "CLICKUP_UPDATE_TASK",
    "CLICKUP_DELETE_TASK",
    "CLICKUP_ADD_TASK_TO_LIST",
    "CLICKUP_REMOVE_TASK_FROM_LIST",
    "CLICKUP_CREATE_CHECKLIST",
    "CLICKUP_EDIT_CHECKLIST",
    "CLICKUP_DELETE_CHECKLIST",
    "CLICKUP_CREATE_CHECKLIST_ITEM",
    "CLICKUP_EDIT_CHECKLIST_ITEM",
    "CLICKUP_DELETE_CHECKLIST_ITEM",
    "CLICKUP_ADD_DEPENDENCY",
    "CLICKUP_DELETE_DEPENDENCY",
    "CLICKUP_ADD_TAG_TO_TASK",
    "CLICKUP_REMOVE_TAG_FROM_TASK",
    "CLICKUP_SET_CUSTOM_FIELD_VALUE",
    "CLICKUP_GET_ACCESSIBLE_CUSTOM_FIELDS",
]

# Time Tracking Tools
TIME_TRACKING_TOOLS = [
    "CLICKUP_START_A_TIME_ENTRY",
    "CLICKUP_STOP_A_TIME_ENTRY",
    "CLICKUP_CREATE_A_TIME_ENTRY",
    "CLICKUP_GET_TIME_ENTRIES_WITHIN_A_DATE_RANGE",
    "CLICKUP_GET_RUNNING_TIME_ENTRY",
    "CLICKUP_UPDATE_A_TIME_ENTRY",
    "CLICKUP_DELETE_A_TIME_ENTRY",
    "CLICKUP_GET_TRACKED_TIME",
]

# Goals Management Tools
GOALS_TOOLS = [
    "CLICKUP_CREATE_GOAL",
    "CLICKUP_GET_GOALS",
    "CLICKUP_GET_GOAL",
    "CLICKUP_UPDATE_GOAL",
    "CLICKUP_DELETE_GOAL",
    "CLICKUP_CREATE_KEY_RESULT",
    "CLICKUP_EDIT_KEY_RESULT",
    "CLICKUP_DELETE_KEY_RESULT",
]

# Collaboration Tools
COLLABORATION_TOOLS = [
    "CLICKUP_CREATE_TASK_COMMENT",
    "CLICKUP_GET_TASK_COMMENTS",
    "CLICKUP_UPDATE_COMMENT",
    "CLICKUP_DELETE_COMMENT",
    "CLICKUP_CREATE_LIST_COMMENT",
    "CLICKUP_GET_LIST_COMMENTS",
    "CLICKUP_CREATE_TASK_ATTACHMENT",
    "CLICKUP_GET_TASK_MEMBERS",
    "CLICKUP_GET_LIST_MEMBERS",
    "CLICKUP_INVITE_USER_TO_WORKSPACE",
    "CLICKUP_GET_USER",
]

# All tools used in ClickUp subgraph (merged from all categories)
CLICKUP_TOOLS = (
    SPACES_FOLDERS_TOOLS
    + TASKS_TOOLS
    + TIME_TRACKING_TOOLS
    + GOALS_TOOLS
    + COLLABORATION_TOOLS
)


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of ClickUp node configurations."""
    composio_service = get_composio_service()

    (
        spaces_folders_tools,
        tasks_tools,
        time_tracking_tools,
        goals_tools,
        collaboration_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(SPACES_FOLDERS_TOOLS),
        composio_service.get_tools_by_name(TASKS_TOOLS),
        composio_service.get_tools_by_name(TIME_TRACKING_TOOLS),
        composio_service.get_tools_by_name(GOALS_TOOLS),
        composio_service.get_tools_by_name(COLLABORATION_TOOLS),
    )

    return (
        OrchestratorNodeConfig(
            name="spaces_folders",
            description="Manage workspace structure: create/update spaces, folders, and lists for project organization",
            system_prompt=SPACES_FOLDERS_PROMPT,
            tools=spaces_folders_tools,
        ),
        OrchestratorNodeConfig(
            name="tasks",
            description="Manage tasks: create, update, delete tasks, checklists, dependencies, tags, and custom fields",
            system_prompt=TASKS_PROMPT,
            tools=tasks_tools,
        ),
        OrchestratorNodeConfig(
            name="time_tracking",
            description="Track time: start/stop timers, create time entries, manage time logs and reports",
            system_prompt=TIME_TRACKING_PROMPT,
            tools=time_tracking_tools,
        ),
        OrchestratorNodeConfig(
            name="goals",
            description="Manage goals and key results: create, update, track progress on objectives and targets",
            system_prompt=GOALS_PROMPT,
            tools=goals_tools,
        ),
        OrchestratorNodeConfig(
            name="collaboration",
            description="Team collaboration: comments, attachments, member management, and workspace invitations",
            system_prompt=COLLABORATION_PROMPT,
            tools=collaboration_tools,
        ),
    )


async def create_clickup_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the ClickUp sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating ClickUp subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="ClickUp",
        agent_name="clickup_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("ClickUp subgraph created successfully")

    return graph
