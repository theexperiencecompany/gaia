"""HubSpot plan-and-execute subgraph built from reusable configuration."""

import asyncio
from typing import Sequence

from app.agents.prompts.hubspot_node_prompts import (
    ACTIVITIES_PROMPT,
    ADMIN_PROMPT,
    COMPANIES_PROMPT,
    CONTACTS_PROMPT,
    DATA_MANAGEMENT_PROMPT,
    DEALS_PROMPT,
    MARKETING_PROMPT,
    PRODUCTS_QUOTES_PROMPT,
    TICKETS_PROMPT,
)
from app.config.loggers import langchain_logger as logger
from app.config.oauth_config import get_integration_by_id
from app.langchain.core.framework.plan_and_execute import (
    OrchestratorNodeConfig,
    OrchestratorSubgraphConfig,
    build_orchestrator_subgraph,
)
from app.services.composio.composio_service import get_composio_service
from langchain_core.language_models import LanguageModelLike
from langgraph.graph.state import CompiledStateGraph

# Contacts Tools
CONTACTS_TOOLS = [
    "HUBSPOT_CREATE_CONTACT",
    "HUBSPOT_READ_CONTACT",
    "HUBSPOT_UPDATE_CONTACT",
    "HUBSPOT_ARCHIVE_CONTACT",
    "HUBSPOT_LIST_CONTACTS",
    "HUBSPOT_SEARCH_CONTACTS_BY_CRITERIA",
    "HUBSPOT_CREATE_BATCH_OF_CONTACTS",
    "HUBSPOT_ARCHIVE_BATCH_OF_CONTACTS_BY_ID",
    "HUBSPOT_PERMANENTLY_DELETE_CONTACT_FOR_GDPR",
]

# Companies Tools
COMPANIES_TOOLS = [
    "HUBSPOT_CREATE_COMPANY",
    "HUBSPOT_GET_COMPANY",
    "HUBSPOT_UPDATE_COMPANY",
    "HUBSPOT_ARCHIVE_COMPANY",
    "HUBSPOT_LIST_COMPANIES",
    "HUBSPOT_SEARCH_COMPANIES",
    "HUBSPOT_CREATE_A_BATCH_OF_COMPANIES",
    "HUBSPOT_ARCHIVE_BATCH_OF_COMPANIES_BY_ID_BATCH",
    "HUBSPOT_PERMANENTLY_DELETE_COMPANY_FOR_GDPR_COMPLIANCE",
]

# Deals Tools
DEALS_TOOLS = [
    "HUBSPOT_CREATE_DEAL",
    "HUBSPOT_GET_DEAL",
    "HUBSPOT_UPDATE_DEAL",
    "HUBSPOT_REMOVE_DEAL",
    "HUBSPOT_LIST_DEALS",
    "HUBSPOT_SEARCH_DEALS",
    "HUBSPOT_CREATE_BATCH_OF_DEALS",
    "HUBSPOT_ARCHIVE_BATCH_OF_DEALS_BY_ID",
    "HUBSPOT_PERMANENTLY_DELETE_DEAL_FOR_GDPR_COMPLIANCE",
]

# Tickets Tools
TICKETS_TOOLS = [
    "HUBSPOT_CREATE_TICKET",
    "HUBSPOT_GET_TICKET",
    "HUBSPOT_UPDATE_TICKET",
    "HUBSPOT_ARCHIVE_TICKET",
    "HUBSPOT_LIST_TICKETS",
    "HUBSPOT_SEARCH_TICKETS",
    "HUBSPOT_CREATE_BATCH_OF_TICKET",
    "HUBSPOT_ARCHIVE_BATCH_OF_TICKETS_BY_ID",
]

# Products Tools
PRODUCTS_TOOLS = [
    "HUBSPOT_CREATE_PRODUCT",
    "HUBSPOT_GET_PRODUCT",
    "HUBSPOT_UPDATE_PRODUCT",
    "HUBSPOT_ARCHIVE_PRODUCT",
    "HUBSPOT_LIST_PRODUCTS_WITH_PAGING",
    "HUBSPOT_SEARCH_PRODUCTS",
    "HUBSPOT_CREATE_PRODUCT_BATCH",
    "HUBSPOT_ARCHIVE_BATCH_PRODUCTS_BY_ID",
]

# Quotes Tools
QUOTES_TOOLS = [
    "HUBSPOT_CREATE_QUOTE_OBJECT",
    "HUBSPOT_GET_QUOTE_BY_ID",
    "HUBSPOT_PARTIAL_UPDATE_QUOTE_BY_QUOTE_ID",
    "HUBSPOT_ARCHIVE_QUOTE_OBJECT_BY_ID",
    "HUBSPOT_SEARCH_QUOTES_BY_CRITERIA",
    "HUBSPOT_CREATE_LINE_ITEM",
    "HUBSPOT_RETRIEVE_LINE_ITEM_BY_ID",
    "HUBSPOT_UPDATE_LINE_ITEM_OBJECT_PARTIALLY",
    "HUBSPOT_ARCHIVE_LINE_ITEM_BY_ID",
]

# Activities Tools
ACTIVITIES_TOOLS = [
    "HUBSPOT_CREATE_TASK",
    "HUBSPOT_CREATE_EMAIL",
    "HUBSPOT_LIST",
    "HUBSPOT_SEARCH_EMAILS",
    "HUBSPOT_CREATE_TIMELINE_EVENT_BASED_ON_TEMPLATE",
    "HUBSPOT_RETRIEVE_TIMELINE_EVENT_BY_IDS",
    "HUBSPOT_LIST_ALL_EVENT_TEMPLATES_FOR_APP",
]

# Marketing Tools
MARKETING_TOOLS = [
    "HUBSPOT_CREATE_CAMPAIGN",
    "HUBSPOT_GET_CAMPAIGN",
    "HUBSPOT_UPDATE_CAMPAIGN",
    "HUBSPOT_DELETE_CAMPAIGN",
    "HUBSPOT_SEARCH_CAMPAIGNS",
    "HUBSPOT_CREATE_A_NEW_MARKETING_EMAIL",
    "HUBSPOT_GET_THE_DETAILS_OF_A_SPECIFIED_MARKETING_EMAIL",
    "HUBSPOT_UPDATE_A_MARKETING_EMAIL",
    "HUBSPOT_DELETE_A_MARKETING_EMAIL",
    "HUBSPOT_PUBLISH_MARKETING_EMAIL",
]

# Admin Tools
ADMIN_TOOLS = [
    "HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE",
    "HUBSPOT_RETURN_PIPELINE_BY_ID",
    "HUBSPOT_CREATE_PIPELINE_FOR_OBJECT_TYPE",
    "HUBSPOT_DELETE_PIPELINE_BY_ID",
    "HUBSPOT_RETRIEVE_PIPELINE_STAGES",
    "HUBSPOT_CREATE_PIPELINE_STAGE",
    "HUBSPOT_DELETE_PIPELINE_STAGE_BY_ID",
    "HUBSPOT_RETRIEVE_OWNERS",
    "HUBSPOT_RETRIEVE_OWNER_BY_ID_OR_USER_ID",
]

# Data Management Tools
DATA_MANAGEMENT_TOOLS = [
    "HUBSPOT_SEARCH_CRM_OBJECTS_BY_CRITERIA",
    "HUBSPOT_CREATE_ASSOCIATION_FOR_OBJECT_TYPE",
    "HUBSPOT_LIST_ASSOCIATION_TYPES",
    "HUBSPOT_REMOVE_ASSOCIATION_FROM_SCHEMA",
]

# All tools used in HubSpot subgraph (merged from all categories)
HUBSPOT_TOOLS = (
    CONTACTS_TOOLS
    + COMPANIES_TOOLS
    + DEALS_TOOLS
    + TICKETS_TOOLS
    + PRODUCTS_TOOLS
    + QUOTES_TOOLS
    + ACTIVITIES_TOOLS
    + MARKETING_TOOLS
    + ADMIN_TOOLS
    + DATA_MANAGEMENT_TOOLS
)


async def get_node_configs() -> Sequence[OrchestratorNodeConfig]:
    """Get the list of HubSpot node configurations."""
    composio_service = get_composio_service()

    (
        contacts_tools,
        companies_tools,
        deals_tools,
        tickets_tools,
        products_tools,
        quotes_tools,
        activities_tools,
        marketing_tools,
        admin_tools,
        data_management_tools,
    ) = await asyncio.gather(
        composio_service.get_tools_by_name(CONTACTS_TOOLS),
        composio_service.get_tools_by_name(COMPANIES_TOOLS),
        composio_service.get_tools_by_name(DEALS_TOOLS),
        composio_service.get_tools_by_name(TICKETS_TOOLS),
        composio_service.get_tools_by_name(PRODUCTS_TOOLS),
        composio_service.get_tools_by_name(QUOTES_TOOLS),
        composio_service.get_tools_by_name(ACTIVITIES_TOOLS),
        composio_service.get_tools_by_name(MARKETING_TOOLS),
        composio_service.get_tools_by_name(ADMIN_TOOLS),
        composio_service.get_tools_by_name(DATA_MANAGEMENT_TOOLS),
    )

    return (
        OrchestratorNodeConfig(
            name="contacts",
            description="Manage individual people records: create, read, update, search, batch operations, archive, and GDPR delete contacts",
            system_prompt=CONTACTS_PROMPT,
            tools=contacts_tools,
        ),
        OrchestratorNodeConfig(
            name="companies",
            description="Manage organization records: create, update, retrieve, search, batch operations, archive, and GDPR delete companies",
            system_prompt=COMPANIES_PROMPT,
            tools=companies_tools,
        ),
        OrchestratorNodeConfig(
            name="deals",
            description="Track sales opportunities: create, update, search, batch operations, archive, and GDPR delete deals through sales pipeline",
            system_prompt=DEALS_PROMPT,
            tools=deals_tools,
        ),
        OrchestratorNodeConfig(
            name="tickets",
            description="Manage customer support requests: create, update, search, batch operations, and archive support tickets",
            system_prompt=TICKETS_PROMPT,
            tools=tickets_tools,
        ),
        OrchestratorNodeConfig(
            name="products",
            description="Manage product catalog: create, update, search, batch operations, and archive products",
            system_prompt=PRODUCTS_QUOTES_PROMPT,
            tools=products_tools,
        ),
        OrchestratorNodeConfig(
            name="quotes",
            description="Manage sales quotes and line items: create, update, search, and archive quotes with line items",
            system_prompt=PRODUCTS_QUOTES_PROMPT,
            tools=quotes_tools,
        ),
        OrchestratorNodeConfig(
            name="activities",
            description="Log activities and create timeline events: tasks, emails, and custom timeline events",
            system_prompt=ACTIVITIES_PROMPT,
            tools=activities_tools,
        ),
        OrchestratorNodeConfig(
            name="marketing",
            description="Manage marketing campaigns and emails: create, update, publish, and delete marketing campaigns and emails",
            system_prompt=MARKETING_PROMPT,
            tools=marketing_tools,
        ),
        OrchestratorNodeConfig(
            name="admin",
            description="Manage CRM configuration: pipelines, stages, and owners management with full CRUD operations",
            system_prompt=ADMIN_PROMPT,
            tools=admin_tools,
        ),
        OrchestratorNodeConfig(
            name="data_management",
            description="Global search across CRM and manage object associations: search any object type and manage relationships",
            system_prompt=DATA_MANAGEMENT_PROMPT,
            tools=data_management_tools,
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

    integration = get_integration_by_id("hubspot")
    if not integration or not integration.subagent_config:
        raise ValueError("HubSpot integration or subagent config not found")

    config = OrchestratorSubgraphConfig(
        provider_name=integration.provider,
        agent_name=integration.subagent_config.agent_name,
        node_configs=await get_node_configs(),
        llm=llm,
    )

    graph = build_orchestrator_subgraph(config)
    logger.info("HubSpot subgraph created successfully")

    return graph
