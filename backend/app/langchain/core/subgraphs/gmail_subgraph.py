"""Gmail plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.core.nodes import trim_messages_node
from app.agents.core.nodes.delete_system_messages import (
    create_delete_system_messages_node,
)
from app.agents.core.nodes.filter_messages import create_filter_messages_node
from app.agents.prompts.gmail_node_prompts import (
    ATTACHMENT_HANDLING_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    GMAIL_PLANNER_PROMPT,
)
from app.agents.prompts.subagent_prompts import GMAIL_AGENT_SYSTEM_PROMPT
from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    PlanExecuteNodeConfig,
    PlanExecuteState,
    PlanExecuteSubgraphConfig,
    build_plan_execute_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph_bigtool.graph import State

AVAILABLE_NODES_DESCRIPTION = """
Available Gmail Operation Nodes:

- email_composition - Create, draft, send emails and manage drafts
- email_retrieval - Search, fetch, list emails and conversation threads
- email_management - Organize, label, delete, archive emails
- communication - Reply to threads, forward messages, manage conversations
- contact_management - Search people, contacts, profiles in Gmail
- attachment_handling - Download and process email attachments
- free_llm - General reasoning, brainstorming, structuring tasks
"""

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
            ]
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
        CompiledStateGraph with message filtering and system message management
    """

    logger.info("Creating Gmail subgraph using plan-and-execute framework")

    agent_name = "gmail_agent"

    # Create filter message node for PlanExecuteState
    filter_node = create_filter_messages_node(
        agent_name=agent_name,
        allow_memory_system_messages=True,
    )
    delete_node = create_delete_system_messages_node(
        prompt=GMAIL_AGENT_SYSTEM_PROMPT,
    )

    async def filter_hook(
        state: PlanExecuteState, config: RunnableConfig, store: BaseStore
    ) -> PlanExecuteState:
        # Adapt PlanExecuteState to State for filter_messages_node
        adapted_state: State = {
            "messages": state.get("messages", []),  # type: ignore
            "selected_tool_ids": [],
        }
        filtered_state = await filter_node(adapted_state, config, store)
        state["messages"] = filtered_state["messages"]  # type: ignore
        return state

    async def trim_hook(
        state: PlanExecuteState, config: RunnableConfig, store: BaseStore
    ) -> PlanExecuteState:
        # Adapt PlanExecuteState to State for trim_messages_node
        adapted_state: State = {
            "messages": state.get("messages", []),  # type: ignore
            "selected_tool_ids": [],
        }
        # trim_messages_node is sync, not async
        trimmed_state = trim_messages_node(adapted_state, config, store)  # type: ignore
        state["messages"] = trimmed_state["messages"]  # type: ignore
        return state

    async def delete_hook(
        state: PlanExecuteState, config: RunnableConfig, store: BaseStore
    ) -> PlanExecuteState:
        # Adapt PlanExecuteState to State for delete_system_messages_node
        adapted_state: State = {
            "messages": state.get("messages", []),  # type: ignore
            "selected_tool_ids": [],
        }
        deleted_state = await delete_node(adapted_state, config, store)
        state["messages"] = deleted_state["messages"]  # type: ignore
        return state

    config = PlanExecuteSubgraphConfig(
        provider_name="Gmail",
        agent_name=agent_name,
        base_planner_prompt=None,  # Use the default base planner prompt
        planner_prompt=GMAIL_PLANNER_PROMPT + "\n\n" + AVAILABLE_NODES_DESCRIPTION,
        node_configs=await get_node_configs(),
        llm=llm,
        pre_plan_hooks=[filter_hook, trim_hook],
        end_graph_hooks=[delete_hook],
    )

    result = build_plan_execute_subgraph(config)
    graph = result.compile()
    logger.info("Gmail subgraph created successfully with message filtering hooks")

    return graph

