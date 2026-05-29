"""
Integration Connection Checker Utility

This module provides utilities to check if a user has the required integration
permissions and stream connection prompts to the frontend when needed.
"""

import httpx
from langgraph.config import get_stream_writer

from app.config.oauth_config import get_integration_by_id, get_integration_scopes
from app.config.token_repository import token_repository
from shared.py.wide_events import log

http_async_client = httpx.AsyncClient(timeout=10.0)

# Mapping of tool categories to required integrations
TOOL_INTEGRATION_MAPPING = {
    "gmail": "gmail",
    "calendar": "googlecalendar",
    "googledocs": "googledocs",
    "google_drive": "google_drive",
    # Add more mappings as needed
}


async def check_user_has_integration(access_token: str, integration_id: str) -> bool:
    """
    Check if the user has the required integration permissions.

    Args:
        access_token: User's OAuth access token
        integration_id: The integration ID to check (e.g., 'gmail', 'googlecalendar')

    Returns:
        bool: True if user has required permissions, False otherwise
    """
    log.set(integration_id=integration_id)
    if not access_token:
        return False

    try:
        # Get required scopes for this integration from oauth_config
        required_scopes = get_integration_scopes(integration_id)
        if not required_scopes:
            log.warning(f"No scopes defined for integration: {integration_id}")
            return False

        token = await token_repository.get_token_by_auth_token(access_token, renew_if_expired=True)

        if not token:
            log.warning(f"No token found for access token: {access_token}")
            return False

        authorized_scopes = str(token.get("scope", "")).split()

        # Check if all required scopes are present
        missing_scopes = [scope for scope in required_scopes if scope not in authorized_scopes]
        return len(missing_scopes) == 0

    except Exception as e:
        log.error(f"Error checking integration permissions: {e}")
        return False


async def stream_integration_connection_prompt(
    integration_id: str,
    tool_name: str | None = None,
    tool_category: str | None = None,
    message: str | None = None,
    user_id: str | None = None,
    user_email: str = "",
) -> None:
    """
    Stream an integration connection prompt to the frontend.

    Args:
        integration_id: The integration ID that needs to be connected
        tool_name: Optional tool name that triggered this requirement
        tool_category: Optional tool category
        message: Optional custom message to display
        user_id: When provided, the actual connect/OAuth URL is built and
            attached to the prompt so the chat card can offer a one-click link.
        user_email: Used as the OAuth login hint for self-managed providers.
    """
    log.set(
        integration_id=integration_id,
        tool_name=tool_name,
        tool_category=tool_category,
    )
    try:
        writer = get_stream_writer()

        # Get integration details
        integration = get_integration_by_id(integration_id)
        if not integration:
            log.error(f"Integration not found: {integration_id}")
            return

        # Late import: this util is pulled in (via the require_integration
        # decorator) by the same import chain that loads the connection
        # service, so importing it at module top level forms a cycle.
        from app.services.integrations.integration_connection_service import build_connect_url

        connect_url = (
            await build_connect_url(user_id, integration_id, user_email=user_email)
            if user_id
            else None
        )

        # Prepare the integration connection data
        connection_payload: dict[str, str] = {
            "integration_id": integration_id,
            "message": message
            or f"To use {str(tool_name).replace('_', ' ') or 'this feature'}, please connect your {integration.name} account.",
        }
        if connect_url:
            connection_payload["connect_url"] = connect_url

        # Stream the data to frontend
        writer({"integration_connection_required": connection_payload})
        log.info(f"Streamed integration connection prompt for: {integration_id}")

    except Exception as e:
        log.error(f"Error streaming integration connection prompt: {e}")


def get_required_integration_for_tool_category(tool_category: str) -> str | None:
    """
    Get the required integration ID for a given tool category.

    Args:
        tool_category: The tool category (e.g., 'mail', 'calendar')

    Returns:
        Optional[str]: The integration ID if one is required, None otherwise
    """
    return TOOL_INTEGRATION_MAPPING.get(tool_category)


async def check_and_prompt_integration(
    access_token: str,
    tool_category: str,
    tool_name: str | None = None,
    user_id: str | None = None,
    user_email: str = "",
) -> bool:
    """
    Check if user has required integration and prompt if not.

    Args:
        access_token: User's OAuth access token
        tool_category: The tool category being accessed
        tool_name: Optional tool name for better messaging
        user_id: When provided, the streamed prompt includes a connect URL.
        user_email: OAuth login hint for self-managed providers.

    Returns:
        bool: True if user has required permissions, False if prompt was sent
    """
    required_integration = get_required_integration_for_tool_category(tool_category)
    if not required_integration:
        # No integration required for this tool category
        return True

    has_integration = await check_user_has_integration(access_token, required_integration)
    if has_integration:
        return True

    # User doesn't have the required integration, send connection prompt
    await stream_integration_connection_prompt(
        integration_id=required_integration,
        tool_name=tool_name,
        tool_category=tool_category,
        user_id=user_id,
        user_email=user_email,
    )
    return False
