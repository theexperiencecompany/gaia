"""
Unified Integration Dependencies

This module provides FastAPI dependencies for validating both Google OAuth scopes
and Composio integrations before allowing access to protected endpoints.

Supports all configured integrations:
- Google OAuth integrations (managed_by="self"): calendar, drive, docs
- Composio integrations (managed_by="composio"): gmail, sheets, notion, twitter, linkedin

Usage:
    # Modern approach - use for any integration
    require_integration("gmail")  # Composio integration
    require_integration("calendar")  # Google OAuth integration

    # Legacy approach - maintained for backward compatibility
    require_integration("gmail")  # Still works but function name is misleading
"""

import httpx
from app.api.v1.dependencies.oauth_dependencies import get_current_user
from app.config.loggers import auth_logger as logger
from app.config.oauth_config import get_integration_by_id, get_short_name_mapping
from app.services.oauth.oauth_service import check_integration_status
from fastapi import Depends, HTTPException, status

http_async_client = httpx.AsyncClient(timeout=10.0)


def require_integration(integration_short_name: str):
    """
    Unified dependency factory that creates a dependency to check for any integration.

    Automatically handles both Google OAuth scopes and Composio integrations
    based on the integration's configuration.

    Args:
        integration_short_name: The short name of the integration (e.g., "gmail", "calendar", "drive")

    Returns:
        A dependency function that validates the user has the required integration

    Raises:
        HTTPException: 403 if the user doesn't have the required integration
        ValueError: If unknown integration name is provided
    """
    # Get the short name mapping from oauth_config
    short_name_mapping = get_short_name_mapping()

    if integration_short_name not in short_name_mapping:
        raise ValueError(
            f"Unknown integration: {integration_short_name}. Available: {list(short_name_mapping.keys())}"
        )

    integration_id = short_name_mapping[integration_short_name]
    integration_config = get_integration_by_id(integration_id)

    if not integration_config:
        raise ValueError(f"Integration config not found for: {integration_id}")

    async def wrapper(user: dict = Depends(get_current_user)):
        user_id = user.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User ID not found",
            )

        try:
            # Use unified integration status checker
            is_connected = await check_integration_status(integration_id, str(user_id))

            if not is_connected:
                detail = {
                    "type": "integration",
                    "message": f"Missing connection: {integration_config.name}. Please connect integrations in settings.",
                }
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=detail,
                )

            return user

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error checking integration {integration_short_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to verify integration permissions",
            )

    return wrapper
