"""User integration management functions."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Literal, Optional

from app.config.loggers import app_logger as logger
from app.constants.cache import ONE_DAY_TTL
from app.db.mongodb.collections import user_integrations_collection
from app.db.utils import serialize_document
from app.decorators.caching import Cacheable, CacheInvalidator
from app.models.integration_models import (
    UserIntegration,
    UserIntegrationResponse,
    UserIntegrationsListResponse,
)
from app.services.integrations.marketplace import get_integration_details


async def get_user_integrations(user_id: str) -> UserIntegrationsListResponse:
    """Get all integrations a user has added to their workspace."""
    user_integrations = []

    cursor = user_integrations_collection.find({"user_id": user_id}).sort(
        "created_at", -1
    )

    async for doc in cursor:
        try:
            user_int = UserIntegration(**doc)
            integration = await get_integration_details(user_int.integration_id)
            if integration:
                user_integrations.append(
                    UserIntegrationResponse(
                        integration_id=user_int.integration_id,
                        status=user_int.status,
                        created_at=user_int.created_at,
                        connected_at=user_int.connected_at,
                        integration=integration,
                    )
                )
        except Exception as e:
            logger.warning(f"Failed to parse user integration: {e}")

    return UserIntegrationsListResponse(
        integrations=user_integrations,
        total=len(user_integrations),
    )


@Cacheable(key_pattern="tools:user:{user_id}:integrations", ttl=ONE_DAY_TTL)
async def get_user_connected_integrations(user_id: str) -> List[Dict[str, Any]]:
    """Get only the integrations that user has connected (status='connected')."""
    results = []
    cursor = user_integrations_collection.find(
        {
            "user_id": user_id,
            "status": "connected",
        }
    )

    async for doc in cursor:
        results.append(serialize_document(doc))

    return results


@CacheInvalidator(key_patterns=["tools:user:{user_id}:*"])
async def add_user_integration(
    user_id: str,
    integration_id: str,
    initial_status: Optional[Literal["created", "connected"]] = None,
) -> UserIntegration:
    """Add an integration to user's workspace."""
    integration = await get_integration_details(integration_id)
    if not integration:
        raise ValueError(f"Integration '{integration_id}' not found")

    existing = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    if existing:
        raise ValueError(f"Integration '{integration_id}' already added to workspace")

    status: Literal["created", "connected"]
    if initial_status:
        status = initial_status
    else:
        status = "connected" if not integration.requires_auth else "created"
    connected_at = datetime.now(UTC) if status == "connected" else None

    user_integration = UserIntegration(
        user_id=user_id,
        integration_id=integration_id,
        status=status,
        created_at=datetime.now(UTC),
        connected_at=connected_at,
    )

    await user_integrations_collection.insert_one(user_integration.model_dump())
    logger.info(
        f"User {user_id} added integration {integration_id} with status {status}"
    )

    return user_integration


@CacheInvalidator(key_patterns=["tools:user:{user_id}:*"])
async def remove_user_integration(user_id: str, integration_id: str) -> bool:
    """Remove an integration from user's workspace."""
    result = await user_integrations_collection.delete_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )

    if result.deleted_count > 0:
        logger.info(f"User {user_id} removed integration {integration_id}")
        return True

    return False


async def check_user_has_integration(user_id: str, integration_id: str) -> bool:
    """Check if a user has added a specific integration."""
    doc = await user_integrations_collection.find_one(
        {
            "user_id": user_id,
            "integration_id": integration_id,
        }
    )
    return doc is not None
