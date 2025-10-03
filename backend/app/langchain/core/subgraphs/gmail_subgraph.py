"""Gmail plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.gmail_node_prompts import (
    ATTACHMENT_HANDLING_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    GMAIL_FINALIZER_PROMPT,
    GMAIL_PLANNER_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    PlanExecuteNodeConfig,
    PlanExecuteSubgraphConfig,
    build_plan_execute_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph


async def get_node_configs() -> Sequence[PlanExecuteNodeConfig]:
    """Get the list of Gmail node configurations."""
    composio_service = get_composio_service()

    (
        email_composition_tools,
        email_retrieval_tools,
        email_management_tools,
        communication_tools,
        contact_management_tools,
        attachment_handling_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(
            [
                "GMAIL_CREATE_EMAIL_DRAFT",
                "GMAIL_SEND_EMAIL",
                "GMAIL_SEND_DRAFT",
                "GMAIL_LIST_DRAFTS",
                "GMAIL_DELETE_DRAFT",
            ],
        ),
        composio_service.get_tools_by_name(
            [
                "GMAIL_FETCH_EMAILS",
                "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID",
                "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
                "GMAIL_LIST_THREADS",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GMAIL_ADD_LABEL_TO_EMAIL",
                "GMAIL_CREATE_LABEL",
                "GMAIL_LIST_LABELS",
                "GMAIL_MODIFY_THREAD_LABELS",
                "GMAIL_PATCH_LABEL",
                "GMAIL_REMOVE_LABEL",
                "GMAIL_DELETE_MESSAGE",
                "GMAIL_MOVE_TO_TRASH",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GMAIL_REPLY_TO_THREAD",
                "GMAIL_FORWARD_MESSAGE",
                "GMAIL_FETCH_MESSAGE_BY_THREAD_ID",
                "GMAIL_LIST_THREADS",
            ]
        ),
        composio_service.get_tools_by_name(
            [
                "GMAIL_GET_CONTACTS",
                "GMAIL_GET_PEOPLE",
                "GMAIL_GET_PROFILE",
                "GMAIL_SEARCH_PEOPLE",
            ]
        ),
        composio_service.get_tools_by_name(["GMAIL_GET_ATTACHMENT"]),
    )

    return (
        PlanExecuteNodeConfig(
            name="email_composition",
            description="Create, draft, send emails and manage drafts",
            system_prompt=EMAIL_COMPOSITION_PROMPT,
            tools=email_composition_tools,
        ),
        PlanExecuteNodeConfig(
            name="email_retrieval",
            description="Search, fetch, list emails and conversation threads",
            system_prompt=EMAIL_RETRIEVAL_PROMPT,
            tools=email_retrieval_tools,
        ),
        PlanExecuteNodeConfig(
            name="email_management",
            description="Organize, label, delete, archive emails",
            system_prompt=EMAIL_MANAGEMENT_PROMPT,
            tools=email_management_tools,
        ),
        PlanExecuteNodeConfig(
            name="communication",
            description="Reply to threads, forward messages, manage conversations",
            system_prompt=COMMUNICATION_PROMPT,
            tools=communication_tools,
        ),
        PlanExecuteNodeConfig(
            name="contact_management",
            description="Search people, contacts, profiles in Gmail",
            system_prompt=CONTACT_MANAGEMENT_PROMPT,
            tools=contact_management_tools,
        ),
        PlanExecuteNodeConfig(
            name="attachment_handling",
            description="Download and process email attachments",
            system_prompt=ATTACHMENT_HANDLING_PROMPT,
            tools=attachment_handling_tools,
        ),
        PlanExecuteNodeConfig(
            name="free_llm",
            description="General reasoning, brainstorming, structuring tasks",
            system_prompt="You are a helpful Gmail assistant. Execute the given instruction using your knowledge and reasoning abilities. Be thorough and provide clear, actionable responses.",
        ),
    )


async def create_gmail_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the Gmail sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating Gmail subgraph using plan-and-execute framework")

    config = PlanExecuteSubgraphConfig(
        provider_name="Gmail",
        agent_name="gmail_agent",
        planner_prompt=GMAIL_PLANNER_PROMPT,
        node_configs=await get_node_configs(),
        llm=llm,
        finalizer_prompt=GMAIL_FINALIZER_PROMPT,
    )

    result = build_plan_execute_subgraph(config)
    graph = result.compile()
    logger.info("Gmail subgraph created successfully")

    return graph

