"""
Integration Management Tools

Tools for listing, connecting, and managing user integrations.
"""

import re
from typing import Annotated, List, Optional

from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.constants.integrations import (
    MAX_AVAILABLE_FOR_LLM,
    MAX_CONNECTED_FOR_LLM,
    MAX_SUGGESTED_FOR_LLM,
)
from app.helpers.integration_helpers import generate_integration_slug
from app.db.mongodb.collections import (
    integrations_collection,
    user_integrations_collection,
)
from app.decorators import with_doc
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
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


# Stopwords to filter out from search queries
SEARCH_STOPWORDS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "with",
    "and",
    "or",
    "in",
    "on",
    "my",
}


def build_search_patterns(query: str) -> list[str]:
    """Extract individual words from query for flexible matching.

    E.g., "Render deployment" -> ["render", "deployment"]
    This allows matching "Render" when query is "Render deployment"
    """
    # Split on whitespace and common separators
    words = re.split(r"[\s,;]+", query.lower())
    # Filter out short/common words that don't help matching
    return [w for w in words if len(w) >= 2 and w not in SEARCH_STOPWORDS]


@tool
@with_doc(LIST_INTEGRATIONS)
async def list_integrations(
    config: RunnableConfig,
    search_public_query: Annotated[
        Optional[str],
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
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        writer = get_stream_writer()

        # Fetch platform integrations with connection status
        platform_ids = [i.id for i in OAUTH_INTEGRATIONS if i.available]
        status_map = await check_multiple_integrations_status(platform_ids, user_id)

        connected_list: List[IntegrationInfo] = []
        available_list: List[IntegrationInfo] = []

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
        user_integration_ids = set()
        cursor = user_integrations_collection.find({"user_id": user_id})
        async for doc in cursor:
            user_integration_ids.add(doc.get("integration_id"))

        if user_integration_ids:
            custom_cursor = integrations_collection.find(
                {
                    "integration_id": {"$in": list(user_integration_ids)},
                    "source": "custom",
                }
            )
            async for doc in custom_cursor:
                integration_id = doc.get("integration_id")
                user_doc = await user_integrations_collection.find_one(
                    {"user_id": user_id, "integration_id": integration_id}
                )
                is_connected = (
                    user_doc.get("status") == "connected" if user_doc else False
                )

                custom_info: IntegrationInfo = {
                    "id": integration_id,
                    "name": doc.get("name", ""),
                    "description": doc.get("description", ""),
                    "category": doc.get("category", "custom"),
                    "connected": is_connected,
                }

                if is_connected:
                    connected_list.append(custom_info)
                else:
                    available_list.append(custom_info)

        # Search for suggested public integrations if query provided
        suggested_list: List[SuggestedIntegration] = []

        if search_public_query and search_public_query.strip():
            try:
                query = search_public_query.strip()
                logger.info(f"Searching public integrations with query: {query}")

                # Get IDs to exclude (user already has these)
                existing_ids = {i["id"] for i in connected_list + available_list}
                existing_ids.update(user_integration_ids)

                # Build flexible word-based search
                words = build_search_patterns(query)

                # Create conditions that match any word in name/description/category
                word_conditions = []
                for word in words:
                    escaped_word = re.escape(word)
                    word_conditions.extend(
                        [
                            {"name": {"$regex": escaped_word, "$options": "i"}},
                            {"description": {"$regex": escaped_word, "$options": "i"}},
                            {"category": {"$regex": escaped_word, "$options": "i"}},
                        ]
                    )

                # Also try the full query as a fallback
                escaped_query = re.escape(query)
                word_conditions.extend(
                    [
                        {"name": {"$regex": escaped_query, "$options": "i"}},
                        {"description": {"$regex": escaped_query, "$options": "i"}},
                    ]
                )

                search_filter = {
                    "is_public": True,
                    "integration_id": {"$nin": list(existing_ids)},
                    "$or": word_conditions
                    if word_conditions
                    else [{"name": {"$regex": escaped_query, "$options": "i"}}],
                }

                docs_cursor = integrations_collection.find(search_filter).limit(
                    MAX_SUGGESTED_FOR_LLM
                )

                async for doc in docs_cursor:
                    iid = doc.get("integration_id")
                    mcp_config = doc.get("mcp_config", {})
                    logger.info(f"Found public integration: {iid} - {doc.get('name')}")

                    suggested_list.append(
                        {
                            "id": iid,
                            "name": doc.get("name", ""),
                            "description": doc.get("description", ""),
                            "category": doc.get("category", "custom"),
                            "icon_url": doc.get("icon_url"),
                            "auth_type": mcp_config.get("auth_type"),
                            "relevance_score": 1.0,  # All matches are equal with regex
                            "slug": generate_integration_slug(
                                name=doc.get("name", ""),
                                category=doc.get("category", "custom"),
                                integration_id=iid,
                            ),
                        }
                    )

                logger.info(f"Found {len(suggested_list)} public integrations")

            except Exception as e:
                logger.warning(f"Failed to search public integrations: {e}")

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
        logger.error(f"Error listing integrations: {e}")
        return f"Error listing integrations: {str(e)}"


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
    return await list_integrations.ainvoke(
        {"search_public_query": query}, config=config
    )


@tool
@with_doc(CONNECT_INTEGRATION)
async def connect_integration(
    integration_names: Annotated[
        List[str],
        "List of integration names or IDs to connect (e.g., ['gmail', 'notion', 'twitter']). Can also be a single integration.",
    ],
    config: RunnableConfig,
) -> str:
    try:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        # Ensure integration_names is a list
        if isinstance(integration_names, str):
            integration_names = [integration_names]

        writer = get_stream_writer()

        results = []
        connections_to_initiate = []

        for integration_name in integration_names:
            # Find the integration by name or ID
            integration = None
            search_name = integration_name.lower().strip()

            for integ in OAUTH_INTEGRATIONS:
                if (
                    integ.id.lower() == search_name
                    or integ.name.lower() == search_name
                    or (integ.short_name and integ.short_name.lower() == search_name)
                ):
                    integration = integ
                    break

            if not integration:
                # Return list of available integrations as suggestion
                available = [i.name for i in OAUTH_INTEGRATIONS if i.available]
                results.append(
                    f"❌ '{integration_name}' not found. "
                    f"Available: {', '.join(available[:5])}{'...' if len(available) > 5 else ''}"
                )
                continue

            if not integration.available:
                results.append(
                    f"⏳ {integration.name} is not available yet. Coming soon!"
                )
                continue

            # Check if already connected using unified service
            is_connected = await check_single_integration_status(
                integration.id, user_id
            )
            if is_connected:
                results.append(f"✅ {integration.name} is already connected!")
                continue

            # Queue for connection
            connections_to_initiate.append(integration)

        # Initiate connections for all queued integrations
        for integration in connections_to_initiate:
            writer({"progress": f"Initiating {integration.name} connection..."})

            integration_data = {
                "integration_id": integration.id,
                "message": f"To use {integration.name} features, please connect your account.",
            }

            writer({"integration_connection_required": integration_data})

            results.append(
                f"🔗 Connection initiated for {integration.name}. "
                f"Please follow the authentication flow."
            )

        return "\n".join(results) if results else "No integrations to connect."

    except Exception as e:
        logger.error(f"Error connecting integrations {integration_names}: {e}")
        return f"Error connecting integrations: {str(e)}"


@tool
@with_doc(CHECK_INTEGRATIONS_STATUS)
async def check_integrations_status(
    integration_names: Annotated[
        List[str],
        "List of integration names or IDs to check status for (e.g., ['gmail', 'notion'])",
    ],
    config: RunnableConfig,
) -> str:
    try:
        configurable = config.get("configurable", {})
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
            is_connected = await check_single_integration_status(
                integration.id, user_id
            )
            status = "✅ Connected" if is_connected else "⚪ Not Connected"
            results.append(f"{integration.name}: {status}")

        return "\n".join(results)

    except Exception as e:
        logger.error(f"Error checking integration status: {e}")
        return f"Error checking status: {str(e)}"


# Export all tools
tools = [
    list_integrations,
    suggest_integrations,
    connect_integration,
    check_integrations_status,
]
