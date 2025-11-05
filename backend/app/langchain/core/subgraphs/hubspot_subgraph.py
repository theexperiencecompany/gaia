"""HubSpot plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.hubspot_node_prompts import (
    ADMIN_PROMPT,
    COMMUNICATION_PROMPT,
    COMPANIES_PROMPT,
    CONTACTS_PROMPT,
    DATA_MANAGEMENT_PROMPT,
    DEALS_PROMPT,
    NOTES_TASKS_PROMPT,
    PRODUCTS_QUOTES_PROMPT,
    TICKETS_PROMPT,
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
    """Get the list of HubSpot node configurations."""
    composio_service = get_composio_service()

    (
        contacts_tools,
        companies_tools,
        deals_tools,
        tickets_tools,
        notes_tasks_tools,
        communication_tools,
        products_quotes_tools,
        data_management_tools,
        admin_tools,
    ) = await asyncio.gather(
        # Contacts
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_CONTACT",
                "HUBSPOT_GET_CONTACT",
                "HUBSPOT_UPDATE_CONTACT",
                "HUBSPOT_LIST_CONTACTS",
                "HUBSPOT_ARCHIVE_CONTACT",
                "HUBSPOT_PERMANENTLY_DELETE_CONTACT_FOR_GDPR",
            ]
        ),
        # Companies
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_COMPANY",
                "HUBSPOT_GET_COMPANY",
                "HUBSPOT_UPDATE_COMPANY",
                "HUBSPOT_LIST_COMPANIES",
                "HUBSPOT_ARCHIVE_COMPANY",
                "HUBSPOT_PERMANENTLY_DELETE_COMPANY_FOR_GDPR_COMPLIANCE",
            ]
        ),
        # Deals
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_DEAL",
                "HUBSPOT_GET_DEAL",
                "HUBSPOT_UPDATE_DEAL",
                "HUBSPOT_LIST_DEALS",
                "HUBSPOT_ARCHIVE_DEAL",
                "HUBSPOT_SEARCH_DEALS",
            ]
        ),
        # Tickets
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_TICKET",
                "HUBSPOT_GET_TICKET",
                "HUBSPOT_UPDATE_TICKET",
                "HUBSPOT_LIST_TICKETS",
                "HUBSPOT_ARCHIVE_TICKET",
                "HUBSPOT_SEARCH_TICKETS",
            ]
        ),
        # Notes & Tasks
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_NOTE",
                "HUBSPOT_GET_NOTE",
                "HUBSPOT_UPDATE_NOTE",
                "HUBSPOT_LIST_NOTES",
                "HUBSPOT_CREATE_TASK",
                "HUBSPOT_GET_TASK",
                "HUBSPOT_UPDATE_TASK",
                "HUBSPOT_LIST_TASKS",
            ]
        ),
        # Communication (Emails & Meetings)
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_EMAIL",
                "HUBSPOT_LIST_EMAILS",
                "HUBSPOT_CREATE_MEETING",
                "HUBSPOT_GET_MEETING",
                "HUBSPOT_LIST_MEETINGS",
            ]
        ),
        # Products & Quotes
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_CREATE_PRODUCT",
                "HUBSPOT_GET_PRODUCT",
                "HUBSPOT_LIST_PRODUCTS",
                "HUBSPOT_SEARCH_PRODUCTS",
                "HUBSPOT_CREATE_QUOTE",
                "HUBSPOT_GET_QUOTE_BY_ID",
                "HUBSPOT_SEARCH_QUOTES_BY_CRITERIA",
            ]
        ),
        # Data Management & Search
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_SEARCH_CRM_OBJECTS_BY_CRITERIA",
                "HUBSPOT_CREATE_ASSOCIATION",
                "HUBSPOT_LIST_ASSOCIATIONS",
                "HUBSPOT_DELETE_ASSOCIATION",
                "HUBSPOT_LIST_ASSOCIATION_TYPES",
            ]
        ),
        # Admin & Utilities
        composio_service.get_tools_by_name(
            [
                "HUBSPOT_RETRIEVE_OWNERS",
                "HUBSPOT_RETRIEVE_OWNER_BY_ID_OR_USER_ID",
                "HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE",
                "HUBSPOT_RETRIEVE_PIPELINE_STAGES",
            ]
        ),
    )

    return (
        OrchestratorNodeConfig(
            name="contacts",
            description="Manage individual people records: create, update, retrieve, list, archive, and GDPR delete contacts",
            system_prompt=CONTACTS_PROMPT,
            tools=contacts_tools,
        ),
        OrchestratorNodeConfig(
            name="companies",
            description="Manage organization records: create, update, retrieve, list, archive, and GDPR delete companies",
            system_prompt=COMPANIES_PROMPT,
            tools=companies_tools,
        ),
        OrchestratorNodeConfig(
            name="deals",
            description="Track sales opportunities: create, update, search, list, and manage deals through sales pipeline",
            system_prompt=DEALS_PROMPT,
            tools=deals_tools,
        ),
        OrchestratorNodeConfig(
            name="tickets",
            description="Manage customer support requests: create, update, search, list, and archive support tickets",
            system_prompt=TICKETS_PROMPT,
            tools=tickets_tools,
        ),
        OrchestratorNodeConfig(
            name="notes_tasks",
            description="Log internal notes and manage to-do items: create, update, list notes and tasks",
            system_prompt=NOTES_TASKS_PROMPT,
            tools=notes_tasks_tools,
        ),
        OrchestratorNodeConfig(
            name="communication",
            description="Log client interactions: create and list email engagements and meeting records",
            system_prompt=COMMUNICATION_PROMPT,
            tools=communication_tools,
        ),
        OrchestratorNodeConfig(
            name="products_quotes",
            description="Manage product catalog and sales quotes: create, search products, and generate quotes",
            system_prompt=PRODUCTS_QUOTES_PROMPT,
            tools=products_quotes_tools,
        ),
        OrchestratorNodeConfig(
            name="data_management",
            description="Global search across CRM and manage relationships: search any object, create/list/delete associations",
            system_prompt=DATA_MANAGEMENT_PROMPT,
            tools=data_management_tools,
        ),
        OrchestratorNodeConfig(
            name="admin",
            description="Manage CRM configuration: retrieve owners, pipelines, and stages",
            system_prompt=ADMIN_PROMPT,
            tools=admin_tools,
        ),
    )


async def create_hubspot_subgraph(llm: LanguageModelLike) -> CompiledStateGraph:
    """Factory function to create and compile the HubSpot sub-agent subgraph.

    Args:
        llm: Language model to use for the subgraph

    Returns:
        CompiledStateGraph with automatic message filtering and cleanup
    """
    logger.info("Creating HubSpot subgraph using plan-and-execute framework")

    config = OrchestratorSubgraphConfig(
        provider_name="HubSpot",
        agent_name="hubspot_agent",
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("HubSpot subgraph created successfully")

    return graph
