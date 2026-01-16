"""
Integration Management Tools

Tools for listing, connecting, and managing user integrations.
"""

from typing import Annotated, List, TypedDict

from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.decorators import with_doc
from app.services.oauth.oauth_service import (
    check_integration_status as check_single_integration_status,
)
from app.services.oauth.oauth_service import (
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


class IntegrationInfo(TypedDict):
    """Integration information structure."""

    id: str
    name: str
    description: str
    category: str
    connected: bool


@tool
@with_doc(LIST_INTEGRATIONS)
async def list_integrations(
    config: RunnableConfig,
    connected_only: Annotated[
        bool,
        "If true, only list connected integrations. If false, list all available integrations.",
    ] = False,
) -> List[IntegrationInfo] | str:
    try:
        configurable = config.get("configurable", {})
        user_id = configurable.get("user_id") if configurable else None
        if not user_id:
            return "Error: User ID not found in configuration."

        writer = get_stream_writer()

        # Get all integration IDs
        integration_ids = [
            integration.id
            for integration in OAUTH_INTEGRATIONS
            if integration.available
        ]

        # Check connection status using unified service
        status_map = await check_multiple_integrations_status(integration_ids, user_id)

        # Build integrations list
        integrations_list: List[IntegrationInfo] = []

        for integration in OAUTH_INTEGRATIONS:
            if not integration.available:
                continue

            # Get connection status from unified service
            is_connected = status_map.get(integration.id, False)

            # Skip disconnected integrations if connected_only is True
            if connected_only and not is_connected:
                continue

            integrations_list.append(
                {
                    "id": integration.id,
                    "name": integration.name,
                    "description": integration.description,
                    "category": integration.category,
                    "connected": is_connected,
                }
            )

        # Stream just the key to trigger UI
        writer({"integration_list_data": {}})

        return integrations_list

    except Exception as e:
        logger.error(f"Error listing integrations: {e}")
        return f"Error listing integrations: {str(e)}"


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
    connect_integration,
    check_integrations_status,
]
