"""
Integration Management Tools

Tools for listing, connecting, and managing user integrations.
"""

from typing import Annotated, List, TypedDict

from app.config.loggers import common_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.services.oauth_service import (
    check_integration_status as check_single_integration_status,
)
from app.services.oauth_service import (
    check_multiple_integrations_status,
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
async def list_integrations(
    config: RunnableConfig,
) -> List[IntegrationInfo] | str:
    """List all available integrations with their connection status and capabilities.

    Use this tool when the user asks:
    - "What integrations do you have?"
    - "What can you connect to?"
    - "What integrations are available?"
    - "Show me all integrations"
    - "What services can you work with?"

    Returns:
        A message confirming the list was shown.
    """
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
async def connect_integration(
    integration_names: Annotated[
        List[str],
        "List of integration names or IDs to connect (e.g., ['gmail', 'notion', 'twitter']). Can also be a single integration.",
    ],
    config: RunnableConfig,
) -> str:
    """Connect one or more integrations for the user.

    Use this tool when the user asks to:
    - "Connect Gmail"
    - "I want to link my Notion account"
    - "Set up Twitter integration"
    - "Connect my [service] account"
    - "Connect Gmail and Notion"
    - "Set up multiple integrations"

    Args:
        integration_names: List of integration names or IDs (e.g., ['gmail', 'notion', 'twitter'])

    Returns:
        A message indicating the connection status or showing the connection UI.
    """
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
async def check_integrations_status(
    integration_names: Annotated[
        List[str],
        "List of integration names or IDs to check status for (e.g., ['gmail', 'notion'])",
    ],
    config: RunnableConfig,
) -> str:
    """Check the connection status of specific integrations.

    Use this tool when the user asks:
    - "Is Gmail connected?"
    - "Check if Notion is connected"
    - "What's the status of my integrations?"

    Args:
        integration_names: List of integration names/IDs to check

    Returns:
        Status information for the requested integrations.
    """
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
