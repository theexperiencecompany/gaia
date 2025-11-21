from datetime import datetime, timezone
from typing import Optional

from app.config.loggers import app_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_scopes,
)
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.db.mongodb.collections import users_collection
from app.decorators.caching import Cacheable
from app.services.composio.composio_service import get_composio_service
from app.utils.email_utils import add_contact_to_resend, send_welcome_email
from fastapi import HTTPException


async def store_user_info(name: str, email: str, picture_url: Optional[str]):
    """
    Stores user info from Google callback.

    - Updates existing users or creates new ones
    - Stores profile picture URL directly without processing

    Args:
        name (str): The user's name.
        email (str): The user's email.
        picture_url (str): The URL of the profile picture from Google.

    Returns:
        The user's MongoDB _id.

    Raises:
        HTTPException: If any step in the process fails.
    """
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    current_time = datetime.now(timezone.utc)

    # Check if user already exists
    existing_user = await users_collection.find_one({"email": email})

    if existing_user:
        update_data = {
            "name": name,
            "updated_at": current_time,
        }

        # Update picture URL if provided, otherwise keep existing or set empty
        if picture_url:
            update_data["picture"] = picture_url
        elif not existing_user.get("picture"):
            update_data["picture"] = ""

        await users_collection.update_one({"email": email}, {"$set": update_data})
        return existing_user["_id"]
    else:
        user_data = {
            "name": name,
            "email": email,
            "picture": picture_url or "",
            "created_at": current_time,
            "updated_at": current_time,
        }

        result = await users_collection.insert_one(user_data)

        # Send welcome email to new user
        try:
            await send_welcome_email(email, name)
            logger.info(f"Welcome email sent to new user: {email}")
        except Exception as e:
            logger.error(f"Failed to send welcome email to {email}: {str(e)}")
            # Don't raise exception - user creation should still succeed

        # Add contact to Resend audience
        try:
            await add_contact_to_resend(email, name)
            logger.info(f"Contact added to Resend audience for new user: {email}")
        except Exception as e:
            logger.error(
                f"Failed to add contact to Resend audience for {email}: {str(e)}"
            )
            # Don't raise exception - user creation should still succeed

        return result.inserted_id


@Cacheable(ttl=86400, key_pattern=f"{OAUTH_STATUS_KEY}:{{user_id}}")
async def get_all_integrations_status(user_id: str) -> dict[str, bool]:
    """
    Get status for ALL integrations for a user. This is the ONLY cached function.

    This function retrieves the connection status for all available integrations
    and caches the entire result. All other status check functions should use this
    cached data rather than making separate API calls.

    Args:
        user_id: The user ID to check status for

    Returns:
        dict[str, bool]: Mapping of integration_id -> connection status for ALL integrations
    """
    result = {}
    composio_providers = []
    composio_id_to_provider = {}

    # Group integrations by type
    for integration in OAUTH_INTEGRATIONS:
        if not integration.available:
            result[integration.id] = False
            continue

        if integration.managed_by == "composio":
            composio_providers.append(integration.provider)
            composio_id_to_provider[integration.id] = integration.provider
        elif integration.managed_by == "self":
            # Check self-managed integrations individually
            try:
                token = await token_repository.get_token(
                    user_id, integration.provider, renew_if_expired=True
                )
                authorized_scopes = str(token.get("scope", "")).split()
                required_scopes = get_integration_scopes(integration.id)
                result[integration.id] = all(
                    scope in authorized_scopes for scope in required_scopes
                )
            except Exception as e:
                logger.debug(f"Token not found for {integration.provider}: {e}")
                result[integration.id] = False

    # Batch check all Composio integrations
    if composio_providers:
        try:
            composio_service = get_composio_service()
            status_map = await composio_service.check_connection_status(
                composio_providers, user_id
            )
            for integration_id, provider in composio_id_to_provider.items():
                result[integration_id] = status_map.get(provider, False)
        except Exception as e:
            logger.error(f"Error batch checking Composio integrations: {e}")
            for integration_id in composio_id_to_provider.keys():
                result[integration_id] = False

    return result


async def check_integration_status(integration_id: str, user_id: str) -> bool:
    """
    Check if a specific integration is connected.

    This function uses the cached get_all_integrations_status() to avoid making
    unnecessary API calls. It will only hit the cache once per user.

    Args:
        integration_id: The integration ID to check (e.g., 'gmail', 'calendar', 'notion')
        user_id: The user ID to check status for

    Returns:
        bool: True if the integration is connected, False otherwise
    """
    try:
        all_statuses = await get_all_integrations_status(user_id)
        return all_statuses.get(integration_id, False)
    except Exception as e:
        logger.error(f"Error checking integration status for {integration_id}: {e}")
        return False


async def check_multiple_integrations_status(
    integration_ids: list[str], user_id: str
) -> dict[str, bool]:
    """
    Check status for multiple integrations.

    This function uses the cached get_all_integrations_status() to efficiently
    return status for multiple integrations without making additional API calls.

    Args:
        integration_ids: List of integration IDs to check
        user_id: The user ID to check status for

    Returns:
        dict[str, bool]: Mapping of integration_id -> connection status
    """
    try:
        all_statuses = await get_all_integrations_status(user_id)
        return {
            integration_id: all_statuses.get(integration_id, False)
            for integration_id in integration_ids
        }
    except Exception as e:
        logger.error(f"Error checking multiple integrations status: {e}")
        return {integration_id: False for integration_id in integration_ids}
