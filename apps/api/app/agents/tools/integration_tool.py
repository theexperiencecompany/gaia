"""
Integration Management Tools

Tools for listing, connecting, and managing user integrations.
"""

from typing import Annotated, cast

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.integrations import (
    MAX_AVAILABLE_FOR_LLM,
    MAX_CONNECTED_FOR_LLM,
    MAX_SUGGESTED_FOR_LLM,
)
from app.constants.log_tags import LogTag
from app.db.repositories.integrations import integration_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators import with_doc
from app.helpers.integration_helpers import build_search_patterns, generate_integration_slug
from app.models.agent_models import agent_configurable
from app.models.integration_models import (
    IntegrationInfo,
    ListIntegrationsResult,
    SuggestedIntegration,
)
from app.services.oauth.oauth_service import (
    check_integration_status as check_single_integration_status,
    check_multiple_integrations_status,
)
from app.templates.docstrings.integration_tool_docs import (
    CHECK_INTEGRATIONS_STATUS,
    CONNECT_INTEGRATION,
    LIST_INTEGRATIONS,
)
from app.utils.integration_checker import request_integration_connection
from shared.py.wide_events import log


@tool
@with_doc(LIST_INTEGRATIONS)
async def list_integrations(
    config: RunnableConfig,
    search_public_query: Annotated[
        str | None,
        "Search query to discover public integrations from the marketplace. "
        "Use natural language like 'API testing', 'email automation', 'project management'. "
        "Leave empty to just show user's current integrations.",
    ] = None,
) -> ListIntegrationsResult | str:
    """
    List user integrations and optionally search for suggested public integrations.

    Returns structured data for LLM context and streams suggested integrations
    to the frontend for the 'Discover More' section.
    """
    try:
        log.set(tool={"name": "list_integrations", "action": "list"})
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        writer = get_stream_writer()

        # Fetch platform integrations with connection status
        platform_ids = [i.id for i in OAUTH_INTEGRATIONS if i.available]
        status_map = await check_multiple_integrations_status(platform_ids, user_id)

        connected_list: list[IntegrationInfo] = []
        available_list: list[IntegrationInfo] = []

        for integration in OAUTH_INTEGRATIONS:
            if not integration.available:
                continue

            is_connected = status_map.get(integration.id, False)
            info: IntegrationInfo = {
                "id": integration.id,
                "name": integration.name,
                "description": integration.description,
                "category": integration.category,
                "connected": is_connected,
            }

            if is_connected:
                connected_list.append(info)
            else:
                available_list.append(info)

        # Fetch user's custom integrations
        user_integrations = await user_integration_repository.list_for_user(user_id)
        user_integration_ids = {ui.integration_id for ui in user_integrations}

        if user_integration_ids:
            custom_docs = await integration_repository.find_custom_by_ids(
                list(user_integration_ids)
            )
            for doc in custom_docs:
                integration_id = doc.integration_id
                is_connected = await user_integration_repository.is_connected(
                    user_id, integration_id
                )

                custom_info: IntegrationInfo = {
                    "id": integration_id,
                    "name": doc.name,
                    "description": doc.description,
                    "category": doc.category,
                    "connected": is_connected,
                }

                if is_connected:
                    connected_list.append(custom_info)
                else:
                    available_list.append(custom_info)

        # Search for suggested public integrations if query provided
        suggested_list: list[SuggestedIntegration] = []

        if search_public_query and search_public_query.strip():
            try:
                query = search_public_query.strip()
                log.info(f"{LogTag.TOOL} Searching public integrations", query=query)

                # Get IDs to exclude (user already has these)
                existing_ids = {i["id"] for i in connected_list + available_list}
                existing_ids.update(user_integration_ids)

                # Flexible word-based search (regex construction lives in the repo)
                words = build_search_patterns(query)

                docs = await integration_repository.search_public(
                    words=words,
                    query=query,
                    exclude_ids=list(existing_ids),
                    limit=MAX_SUGGESTED_FOR_LLM,
                )

                for doc in docs:
                    iid = doc.integration_id
                    log.info(
                        f"{LogTag.TOOL} Found public integration",
                        integration_id=iid,
                        integration_name=doc.name,
                    )

                    suggested_list.append(
                        {
                            "id": iid,
                            "name": doc.name,
                            "description": doc.description,
                            "category": doc.category,
                            "icon_url": doc.icon_url,
                            "auth_type": doc.mcp_config.auth_type if doc.mcp_config else None,
                            "relevance_score": 1.0,  # All matches are equal with regex
                            "slug": generate_integration_slug(
                                name=doc.name,
                                category=doc.category,
                            ),
                        }
                    )

                log.info(
                    f"{LogTag.TOOL} Found public integrations",
                    integration_count=len(suggested_list),
                )

            except Exception as e:
                log.warning(
                    f"{LogTag.TOOL} Failed to search public integrations",
                    error_type=type(e).__name__,
                )

        # Stream suggested integrations to frontend (camelCase)
        suggested_for_stream = [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s["description"],
                "category": s["category"],
                "iconUrl": s["icon_url"],
                "authType": s["auth_type"],
                "relevanceScore": s["relevance_score"],
                "slug": s["slug"],
            }
            for s in suggested_list[:MAX_SUGGESTED_FOR_LLM]
        ]

        writer(
            {
                "integration_list_data": {
                    "hasSuggestions": len(suggested_list) > 0,
                    "suggested": suggested_for_stream,
                }
            }
        )

        # Return structured data for LLM (with limits)
        return {
            "connected": connected_list[:MAX_CONNECTED_FOR_LLM],
            "available": available_list[:MAX_AVAILABLE_FOR_LLM],
            "suggested": suggested_list[:MAX_SUGGESTED_FOR_LLM],
        }

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error listing integrations", error_type=type(e).__name__)
        return f"Error listing integrations: {e!s}"


@tool
async def suggest_integrations(
    query: Annotated[
        str,
        "Search query to find relevant public integrations from the marketplace. "
        "Examples: 'email tools', 'project management', 'social media', 'CRM', 'Slack alternatives'",
    ],
    config: RunnableConfig,
) -> ListIntegrationsResult | str:
    """
    Search for and suggest public integrations from the marketplace based on a query.

    Use this tool when the user wants to discover new integrations, find alternatives,
    or explore what's available in a specific category.

    This tool will search the marketplace and display suggested integrations
    that the user can add with one click.
    """
    # list_integrations itself declares this exact return type; .ainvoke() is the
    # BaseTool framework boundary and always types its result `Any`.
    return cast(
        "ListIntegrationsResult | str",
        await list_integrations.ainvoke({"search_public_query": query}, config=config),
    )


@tool
@with_doc(CONNECT_INTEGRATION)
async def connect_integration(
    integration_ids: Annotated[
        list[str],
        "List of exact integration IDs to connect (e.g., ['gmail', 'notion', 'twitter']).",
    ],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "connect_integration", "action": "connect"})
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        # The Pydantic args_schema declares list[str], but a direct/programmatic
        # invocation can still hand this a bare string — widen before narrowing.
        raw_integration_ids = cast("list[str] | str", integration_ids)
        if isinstance(raw_integration_ids, str):
            integration_ids = [raw_integration_ids]
        integration_ids = list(
            dict.fromkeys(iid.lower().strip() for iid in integration_ids if iid.strip())
        )

        writer = get_stream_writer()

        results = []
        connections_to_initiate = []

        for integration_id in integration_ids:
            integration = next(
                (integ for integ in OAUTH_INTEGRATIONS if integ.id.lower() == integration_id),
                None,
            )

            if not integration:
                available = [i.id for i in OAUTH_INTEGRATIONS if i.available]
                results.append(
                    f"❌ '{integration_id}' not found. "
                    f"Available IDs: {', '.join(available[:5])}{'...' if len(available) > 5 else ''}"
                )
                continue

            if not integration.available:
                results.append(f"⏳ {integration.name} is not available yet. Coming soon!")
                continue

            is_connected = await check_single_integration_status(integration.id, user_id)
            if is_connected:
                results.append(f"✅ {integration.name} is already connected!")
                continue

            connections_to_initiate.append(integration)

        for integration in connections_to_initiate:
            writer({"progress": f"Initiating {integration.name} connection..."})
            results.append(
                await request_integration_connection(integration.id, integration.name, str(user_id))
            )

        return "\n".join(results) if results else "No integrations to connect."

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error connecting integrations",
            integration_ids=integration_ids,
            error_type=type(e).__name__,
        )
        return f"Error connecting integrations: {e!s}"


@tool
@with_doc(CHECK_INTEGRATIONS_STATUS)
async def check_integrations_status(
    integration_names: Annotated[
        list[str],
        "List of integration names or IDs to check status for (e.g., ['gmail', 'notion'])",
    ],
    config: RunnableConfig,
) -> str:
    try:
        log.set(tool={"name": "check_integrations_status", "action": "check"})
        configurable = agent_configurable(config)
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        results = []

        for integration_name in integration_names:
            search_name = integration_name.lower().strip()
            integration = None

            for integ in OAUTH_INTEGRATIONS:
                if (
                    integ.id.lower() == search_name
                    or integ.name.lower() == search_name
                    or (integ.short_name and integ.short_name.lower() == search_name)
                ):
                    integration = integ
                    break

            if not integration:
                results.append(f"❓ {integration_name}: Not found")
                continue

            # Use unified status checker
            is_connected = await check_single_integration_status(integration.id, user_id)
            status = "✅ Connected" if is_connected else "⚪ Not Connected"
            results.append(f"{integration.name}: {status}")

        return "\n".join(results)

    except Exception as e:
        log.error(f"{LogTag.TOOL} Error checking integration status", error_type=type(e).__name__)
        return f"Error checking status: {e!s}"


# Export all tools
tools = [
    list_integrations,
    suggest_integrations,
    connect_integration,
    check_integrations_status,
]
