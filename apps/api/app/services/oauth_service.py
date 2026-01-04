from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException

from app.config.loggers import app_logger as logger
from app.config.oauth_config import (
    OAUTH_INTEGRATIONS,
    get_integration_scopes,
)
from app.config.token_repository import token_repository
from app.constants.keys import OAUTH_STATUS_KEY
from app.core.websocket_manager import websocket_manager
from app.db.mongodb.collections import users_collection
from app.db.redis import delete_cache
from app.decorators.caching import Cacheable
from app.models.user_models import BioStatus
from app.services.composio.composio_service import get_composio_service
from app.services.integration_service import (
    check_user_has_integration,
    update_user_integration_status,
)
from app.services.mcp.mcp_token_store import MCPTokenStore
from app.services.provider_metadata_service import (
    fetch_and_store_provider_metadata,
)
from app.utils.email_utils import add_contact_to_resend, send_welcome_email
from app.utils.redis_utils import RedisPoolManager


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
    mcp_integrations = []

    # Group integrations by type
    for integration in OAUTH_INTEGRATIONS:
        if not integration.available:
            result[integration.id] = False
            continue

        # MCP integrations - check credentials table
        if integration.managed_by == "mcp":
            mcp_integrations.append(integration.id)
        elif integration.managed_by == "composio":
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

    # Batch check all MCP integrations
    if mcp_integrations:
        try:
            token_store = MCPTokenStore(user_id=user_id)
            for integration_id in mcp_integrations:
                integration = next(
                    (i for i in OAUTH_INTEGRATIONS if i.id == integration_id), None
                )
                # Unauthenticated MCPs require explicit user connection via user_integrations
                if (
                    integration
                    and integration.mcp_config
                    and not integration.mcp_config.requires_auth
                ):
                    # Check if user has connected this unauthenticated MCP
                    result[integration_id] = await check_user_has_integration(
                        user_id, integration_id
                    )
                else:
                    # Authenticated MCPs check mcp_credentials table
                    result[integration_id] = await token_store.is_connected(
                        integration_id
                    )
        except Exception as e:
            logger.error(f"Error checking MCP integrations: {e}")
            for integration_id in mcp_integrations:
                result[integration_id] = False

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


async def handle_oauth_connection(
    user_id: str,
    integration_config: Any,
    connected_account_id: str,
    background_tasks: Any,
) -> None:
    """
    Handle successful OAuth connection: setup triggers, update bio status, queue processing.

    Args:
        user_id: The user ID
        integration_config: The integration configuration object
        connected_account_id: The connected account ID from Composio
        background_tasks: FastAPI background tasks
    """
    # Setup triggers if available
    if integration_config.associated_triggers:
        composio_service = get_composio_service()
        logger.info(
            f"Setting up {len(integration_config.associated_triggers)} triggers "
            f"for user {user_id} and integration {integration_config.id}"
        )
        background_tasks.add_task(
            composio_service.handle_subscribe_trigger,
            user_id=user_id,
            triggers=integration_config.associated_triggers,
        )

    # Process Gmail emails to memory if this is a Gmail connection
    if integration_config.id == "gmail":
        logger.info(f"Starting Gmail email processing for user {user_id}")

        # Check if user has completed onboarding and update bio_status to processing
        try:
            user_doc = await users_collection.find_one({"_id": ObjectId(user_id)})
            if user_doc and user_doc.get("onboarding", {}).get("completed"):
                current_bio_status = user_doc.get("onboarding", {}).get("bio_status")

                # If bio was generated without Gmail, update status to processing
                if current_bio_status in [BioStatus.NO_GMAIL, "no_gmail"]:
                    await users_collection.update_one(
                        {"_id": ObjectId(user_id)},
                        {
                            "$set": {
                                "onboarding.bio_status": BioStatus.PROCESSING,
                                "updated_at": datetime.now(timezone.utc),
                            }
                        },
                    )
                    logger.info(
                        f"Updated bio_status to processing for user {user_id} "
                        f"(was {current_bio_status})"
                    )

                    # Send WebSocket update to notify frontend
                    try:
                        if isinstance(user_id, str) and user_id:
                            await websocket_manager.broadcast_to_user(
                                user_id=user_id,
                                message={
                                    "type": "bio_status_update",
                                    "data": {"bio_status": BioStatus.PROCESSING},
                                },
                            )
                        else:
                            logger.warning(
                                f"Cannot broadcast WebSocket update: user_id is not a valid string ({user_id})"
                            )
                    except Exception as ws_error:
                        logger.warning(f"Failed to send WebSocket update: {ws_error}")
        except Exception as e:
            logger.error(
                f"Error updating bio_status for user {user_id}: {e}", exc_info=True
            )

        # Queue Gmail processing via ARQ
        try:
            pool = await RedisPoolManager.get_pool()
            await pool.enqueue_job("process_gmail_emails_to_memory", user_id)
            logger.info(f"Queued Gmail processing job for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to queue Gmail processing: {e}", exc_info=True)

    # Invalidate OAuth status cache for this user
    try:
        cache_key = f"{OAUTH_STATUS_KEY}:{user_id}"
        await delete_cache(cache_key)
        logger.info(f"OAuth status cache invalidated for user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to invalidate OAuth status cache: {e}")

    # Update user_integrations status in MongoDB
    try:
        await update_user_integration_status(
            user_id, integration_config.id, "connected"
        )
        logger.info(f"Updated user_integrations status for {integration_config.id}")
    except Exception as e:
        logger.warning(f"Failed to update user_integrations status: {e}")

    if integration_config.metadata_config:
        background_tasks.add_task(
            fetch_and_store_provider_metadata,
            user_id=user_id,
            integration_id=integration_config.id,
        )
        logger.info(
            f"Queued metadata fetch for user {user_id} and integration {integration_config.id}"
        )
