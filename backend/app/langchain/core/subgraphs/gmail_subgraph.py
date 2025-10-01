"""Gmail plan-and-execute subgraph built from reusable configuration."""

from typing import Sequence

from app.config.loggers import langchain_logger as logger
from app.langchain.core.framework.plan_and_execute import (
    PlanExecuteNodeConfig,
    PlanExecuteSubgraphConfig,
    build_plan_execute_subgraph,
)
from app.langchain.prompts.gmail_node_prompts import (
    ATTACHMENT_HANDLING_PROMPT,
    COMMUNICATION_PROMPT,
    CONTACT_MANAGEMENT_PROMPT,
    EMAIL_COMPOSITION_PROMPT,
    EMAIL_MANAGEMENT_PROMPT,
    EMAIL_RETRIEVAL_PROMPT,
    GMAIL_PLANNER_PROMPT,
)
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph

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

GMAIL_NODE_CONFIGS: Sequence[PlanExecuteNodeConfig] = (
    PlanExecuteNodeConfig(
        name="email_composition",
        description="Create, draft, send emails and manage drafts",
        system_prompt=EMAIL_COMPOSITION_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="email_retrieval",
        description="Search, fetch, list emails and conversation threads",
        system_prompt=EMAIL_RETRIEVAL_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="email_management",
        description="Organize, label, delete, archive emails",
        system_prompt=EMAIL_MANAGEMENT_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="communication",
        description="Reply to threads, forward messages, manage conversations",
        system_prompt=COMMUNICATION_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="contact_management",
        description="Search people, contacts, profiles in Gmail",
        system_prompt=CONTACT_MANAGEMENT_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="attachment_handling",
        description="Download and process email attachments",
        system_prompt=ATTACHMENT_HANDLING_PROMPT,
    ),
    PlanExecuteNodeConfig(
        name="free_llm",
        description="General reasoning, brainstorming, structuring tasks",
        system_prompt="You are a helpful Gmail assistant. Execute the given instruction using your knowledge and reasoning abilities. Be thorough and provide clear, actionable responses.",
    ),
)


def _planner_prompt() -> str:
    return GMAIL_PLANNER_PROMPT + "\n\n" + AVAILABLE_NODES_DESCRIPTION


def create_gmail_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the Gmail sub-agent subgraph."""
    logger.info("Creating Gmail subgraph using plan-and-execute framework")

    config = PlanExecuteSubgraphConfig(
        provider_name="Gmail",
        agent_name="gmail_agent",
        planner_prompt=_planner_prompt(),
        node_configs=GMAIL_NODE_CONFIGS,
        llm=llm,
    )

    compiled_graph = build_plan_execute_subgraph(config)
    logger.info("Gmail subgraph created successfully")
    return compiled_graph

