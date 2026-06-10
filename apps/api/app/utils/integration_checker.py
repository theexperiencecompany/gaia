"""
Integration Connection Checker Utility

This module provides utilities to check if a user has the required integration
permissions and stream connection prompts to the frontend when needed.
"""

import httpx
from langgraph.config import get_config, get_stream_writer

from app.config.oauth_config import get_integration_by_id, get_integration_scopes
from app.config.token_repository import token_repository
from app.models.chat_models import SourceCategory
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


def _current_source_category() -> str | None:
    """Read the generalized source category (ui/bot/bg) from the active graph run.

    Uses LangGraph's ambient config (same mechanism as ``get_stream_writer``), so
    no config threading is needed. Returns None outside a runnable context.
    """
    try:
        config = get_config()
    except RuntimeError:
        return None
    return config.get("configurable", {}).get("source_category")


def build_integration_connection_message(integration_name: str, connect_url: str) -> str:
    """Agent-facing instruction for getting an integration connected.

    On UI clients a connect card/button is rendered alongside the reply. The
    agent receives the URL for context but must NOT include it in its reply —
    the card already gives the user a one-click button. On bot/background
    clients there is no UI, so the agent must put the link directly in its
    text reply so the user can navigate to it.
    """
    if _current_source_category() == SourceCategory.UI.value:
        return (
            f"{integration_name} needs to be connected. A connect button has been shown to the "
            f"user — do NOT include any URL in your reply, the UI card handles it. "
            f"Ask the user to click the connect button, then try again. "
            f"(connect URL for context only, do not render: {connect_url})"
        )
    return (
        f"{integration_name} needs to be connected. The user is on a text-only platform (no UI). "
        f"Include this URL verbatim in your result so the comms agent can relay it to the user: "
        f"{connect_url}"
    )


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
) -> None:
    """
    Stream an integration connection prompt to the frontend.

    Args:
        integration_id: The integration ID that needs to be connected
        tool_name: Optional tool name that triggered this requirement
        tool_category: Optional tool category
        message: Optional custom message to display
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

        # Prepare the integration connection data
        connection_data = {
            "integration_connection_required": {
                "integration_id": integration_id,
                "message": message
                or f"To use {str(tool_name).replace('_', ' ') or 'this feature'}, please connect your {integration.name} account.",
            }
        }

        # Stream the data to frontend
        writer(connection_data)
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
    access_token: str, tool_category: str, tool_name: str | None = None
) -> bool:
    """
    Check if user has required integration and prompt if not.

    Args:
        access_token: User's OAuth access token
        tool_category: The tool category being accessed
        tool_name: Optional tool name for better messaging

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
    )
    return False
