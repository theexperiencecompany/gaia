"""Trello plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.trello_node_prompts import (
    BOARDS_PROMPT,
    CARDS_PROMPT,
    LABELS_CHECKLISTS_PROMPT,
    LISTS_PROMPT,
    MEMBERS_COLLABORATION_PROMPT,
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

# Board Management Tools
BOARDS_TOOLS = [
    "TRELLO_ADD_BOARDS",
    "TRELLO_GET_BOARDS_BY_ID_BOARD",
    "TRELLO_UPDATE_BOARDS_BY_ID_BOARD",
    "TRELLO_UPDATE_BOARDS_CLOSED_BY_ID_BOARD",
    "TRELLO_UPDATE_BOARDS_NAME_BY_ID_BOARD",
    "TRELLO_UPDATE_BOARDS_DESC_BY_ID_BOARD",
    "TRELLO_GET_BOARDS_LISTS_BY_ID_BOARD",
    "TRELLO_GET_BOARDS_CARDS_BY_ID_BOARD",
    "TRELLO_GET_BOARDS_MEMBERS_BY_ID_BOARD",
    "TRELLO_UPDATE_BOARDS_MEMBERS_BY_ID_BOARD",
    "TRELLO_ADD_BOARDS_LISTS_BY_ID_BOARD",
]

# Card Management Tools
CARDS_TOOLS = [
    "TRELLO_ADD_CARDS",
    "TRELLO_GET_CARDS_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_BY_ID_CARD",
    "TRELLO_DELETE_CARDS_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_NAME_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_DESC_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_DUE_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_CLOSED_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_ID_LIST_BY_ID_CARD",
    "TRELLO_UPDATE_CARDS_POS_BY_ID_CARD",
    "TRELLO_ADD_CARDS_ID_MEMBERS_BY_ID_CARD",
    "TRELLO_DELETE_CARDS_ID_MEMBERS_BY_ID_CARD_BY_ID_MEMBER",
    "TRELLO_ADD_CARDS_ACTIONS_COMMENTS_BY_ID_CARD",
    "TRELLO_DELETE_CARDS_ACTIONS_COMMENTS_BY_ID_CARD_BY_ID_ACTION",
    "TRELLO_ADD_CARDS_ATTACHMENTS_BY_ID_CARD",
    "TRELLO_DELETE_CARDS_ATTACHMENTS_BY_ID_CARD_BY_ID_ATTACHMENT",
]

# List Management Tools
LISTS_TOOLS = [
    "TRELLO_ADD_LISTS",
    "TRELLO_GET_LISTS_BY_ID_LIST",
    "TRELLO_UPDATE_LISTS_BY_ID_LIST",
    "TRELLO_UPDATE_LISTS_CLOSED_BY_ID_LIST",
    "TRELLO_UPDATE_LISTS_NAME_BY_ID_LIST",
    "TRELLO_UPDATE_LISTS_POS_BY_ID_LIST",
    "TRELLO_GET_LISTS_CARDS_BY_ID_LIST",
    "TRELLO_ADD_LISTS_CARDS_BY_ID_LIST",
    "TRELLO_ADD_LISTS_ARCHIVE_ALL_CARDS_BY_ID_LIST",
    "TRELLO_ADD_LISTS_MOVE_ALL_CARDS_BY_ID_LIST",
]

# Labels & Checklists Tools
LABELS_CHECKLISTS_TOOLS = [
    "TRELLO_ADD_LABELS",
    "TRELLO_GET_LABELS_BY_ID_LABEL",
    "TRELLO_UPDATE_LABELS_BY_ID_LABEL",
    "TRELLO_DELETE_LABELS_BY_ID_LABEL",
    "TRELLO_UPDATE_LABELS_NAME_BY_ID_LABEL",
    "TRELLO_UPDATE_LABELS_COLOR_BY_ID_LABEL",
    "TRELLO_ADD_CARDS_ID_LABELS_BY_ID_CARD",
    "TRELLO_DELETE_CARDS_ID_LABELS_BY_ID_CARD_BY_ID_LABEL",
    "TRELLO_ADD_CHECKLISTS",
    "TRELLO_GET_CHECKLISTS_BY_ID_CHECKLIST",
    "TRELLO_UPDATE_CHECKLISTS_BY_ID_CHECKLIST",
    "TRELLO_DELETE_CHECKLISTS_BY_ID_CHECKLIST",
    "TRELLO_ADD_CHECKLISTS_CHECK_ITEMS_BY_ID_CHECKLIST",
    "TRELLO_UPDATE_CARD_CHECKLIST_ITEM_STATE_BY_IDS",
    "TRELLO_DELETE_CHECKLIST_ITEM",
    "TRELLO_ADD_CARDS_CHECKLISTS_BY_ID_CARD",
]

# Members & Collaboration Tools
MEMBERS_COLLABORATION_TOOLS = [
    "TRELLO_GET_MEMBERS_BY_ID_MEMBER",
    "TRELLO_GET_MEMBERS_BOARDS_BY_ID_MEMBER",
    "TRELLO_GET_MEMBERS_CARDS_BY_ID_MEMBER",
    "TRELLO_GET_CARDS_MEMBERS_BY_ID_CARD",
    "TRELLO_GET_BOARDS_MEMBERS_BY_ID_BOARD",
    "TRELLO_GET_SEARCH",
    "TRELLO_GET_SEARCH_MEMBERS",
]

# All tools used in Trello subgraph (merged from all categories)
TRELLO_TOOLS = (
    BOARDS_TOOLS
    + CARDS_TOOLS
    + LISTS_TOOLS
    + LABELS_CHECKLISTS_TOOLS
    + MEMBERS_COLLABORATION_TOOLS
)


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of Trello node configurations."""
    composio_service = get_composio_service()

    (
        boards_tools,
        cards_tools,
        lists_tools,
        labels_checklists_tools,
        members_collaboration_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(BOARDS_TOOLS),
        composio_service.get_tools_by_name(CARDS_TOOLS),
        composio_service.get_tools_by_name(LISTS_TOOLS),
        composio_service.get_tools_by_name(LABELS_CHECKLISTS_TOOLS),
        composio_service.get_tools_by_name(MEMBERS_COLLABORATION_TOOLS),
    )

    return (
        OrchestratorNodeConfig(
            name="boards",
            description="Manage Trello boards: create, update, configure boards, manage board members and settings",
            system_prompt=BOARDS_PROMPT,
            tools=boards_tools,
        ),
        OrchestratorNodeConfig(
            name="cards",
            description="Manage cards: create, update, move, delete cards, add members, comments, and attachments",
            system_prompt=CARDS_PROMPT,
            tools=cards_tools,
        ),
        OrchestratorNodeConfig(
            name="lists",
            description="Manage lists: create, update, archive, move cards between lists and organize workflows",
            system_prompt=LISTS_PROMPT,
            tools=lists_tools,
        ),
        OrchestratorNodeConfig(
            name="labels_checklists",
            description="Manage labels and checklists: create/update labels, manage checklists and checklist items",
            system_prompt=LABELS_CHECKLISTS_PROMPT,
            tools=labels_checklists_tools,
        ),
        OrchestratorNodeConfig(
            name="members_collaboration",
            description="Member management and search: view members, search boards/cards, team collaboration",
            system_prompt=MEMBERS_COLLABORATION_PROMPT,
            tools=members_collaboration_tools,
        ),
    )


async def create_trello_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the Trello sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating Trello subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="Trello",
        agent_name="trello_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("Trello subgraph created successfully")

    return graph
