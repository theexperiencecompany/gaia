"""
Composio Token Utilities

Utility functions for retrieving access tokens from Composio connected accounts.
This module provides a centralized way to get OAuth tokens for various toolkits
(e.g., GOOGLECALENDAR, GMAIL, etc.) using Composio's connected accounts API.
"""

from typing import Dict, List, Optional

from composio_client.types.connected_account_list_response import (
    ConnectedAccountListResponse,
    Item,
)
from fastapi import HTTPException

from app.config.loggers import general_logger as logger
from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.services.composio.composio_service import get_composio_service

# Build a mapping of toolkit names to auth_config_ids from oauth_config
TOOLKIT_AUTH_CONFIG_MAP: Dict[str, str] = {
    integration.composio_config.toolkit: integration.composio_config.auth_config_id
    for integration in OAUTH_INTEGRATIONS
    if integration.composio_config and integration.composio_config.toolkit
}


def get_access_token_from_composio(
    user_id: str,
    toolkit: str,
) -> str:
    """
    Retrieve access token from Composio for a specific user and toolkit.

    Args:
        user_id: The user ID to get the token for
        toolkit: The Composio toolkit name (e.g., "GOOGLECALENDAR", "GMAIL")

    Returns:
        str: The access token

    Raises:
        HTTPException(401): If no connected account found or token unavailable
        HTTPException(500): If an unexpected error occurs

    Example:
        >>> token = get_access_token_from_composio(
        ...     user_id="user123",
        ...     toolkit="GOOGLECALENDAR"
        ... )
        >>> # Use token with Google Calendar API
        >>> headers = {"Authorization": f"Bearer {token}"}
    """
    # Get the auth_config_id for this toolkit
    auth_config_id = TOOLKIT_AUTH_CONFIG_MAP.get(toolkit)
    if not auth_config_id:
        raise HTTPException(
            status_code=500,
            detail=f"Toolkit '{toolkit}' not configured in oauth_config",
        )

    try:
        composio_service = get_composio_service()

        # Get connected accounts for this user and toolkit
        user_accounts: ConnectedAccountListResponse = (
            composio_service.composio.connected_accounts.list(
                user_ids=[user_id],
                auth_config_ids=[auth_config_id],
                limit=1,
            )
        )

        # Check if any active account exists
        active_accounts: List[Item] = [
            acc
            for acc in user_accounts.items
            if acc.status == "ACTIVE" and not acc.auth_config.is_disabled
        ]

        if not active_accounts:
            logger.warning(
                f"No active {toolkit} account found for user {user_id}. "
                f"User needs to connect their account via Composio."
            )
            raise HTTPException(
                status_code=401,
                detail=f"No connected {toolkit} account found. Please connect your account.",
            )

        # Get the first active account
        account: Item = active_accounts[0]

        # Extract access token from account credentials
        # The account.state is a Pydantic model (ItemStateUnionMember), not a dict
        if not account.state:
            raise HTTPException(
                status_code=500,
                detail=f"Account state not available for {toolkit}",
            )

        state_dict: Dict[str, Optional[object]] = account.state.model_dump()
        val: Dict[str, Optional[object]] = state_dict.get("val", {})  # type: ignore
        access_token: Optional[object] = (
            val.get("access_token") if isinstance(val, dict) else None
        )

        if not access_token:
            logger.error(
                f"Access token not found in state for {toolkit} account {account.id}. "
                f"Available keys in state: {list(state_dict.keys())}. "
                f"Credentials may be masked or structure changed."
            )
            raise HTTPException(
                status_code=500,
                detail="Access token unavailable. Check Composio project settings or account connection.",
            )

        # Convert access_token to string (it should be a string from Composio)
        access_token_str: str = str(access_token)

        # Check if token is redacted
        if access_token_str == "REDACTED":  # nosec B105
            logger.error(
                f"Access token is REDACTED for {toolkit}. "
                f"Disable 'Mask Connected Account Secrets' in Composio project settings."
            )
            raise HTTPException(
                status_code=500,
                detail="Access token is masked. Please disable 'Mask Connected Account Secrets' in Composio settings.",
            )

        logger.info(f"Successfully retrieved {toolkit} token for user {user_id}")
        return access_token_str

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving {toolkit} token for user {user_id}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve access token: {str(e)}",
        )


def get_google_calendar_token(user_id: str) -> str:
    """
    Convenience function to get Google Calendar access token.

    Args:
        user_id: The user ID to get the token for

    Returns:
        str: The Google Calendar access token

    Raises:
        HTTPException: If token retrieval fails
    """
    return get_access_token_from_composio(user_id, "GOOGLECALENDAR")
