"""
User integration status management.

This module is separated to avoid circular imports between
oauth_service.py and integration_service.py.
"""

from datetime import UTC, datetime
from typing import Any, Dict, Literal

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import user_integrations_collection
from app.decorators.caching import CacheInvalidator


@CacheInvalidator(key_patterns=["tools:user:{user_id}"])
async def update_user_integration_status(
    user_id: str,
    integration_id: str,
    status: Literal["created", "connected"],
) -> bool:
    """
    Update or create user integration status (upsert).

    Called after successful OAuth or MCP connection to set status='connected'.
    Creates the record if it doesn't exist.

    Args:
        user_id: The user's ID
        integration_id: ID of integration
        status: New status ('created' or 'connected')

    Returns:
        True if operation was successful (update, insert, or matched existing)
    """
    update_data: Dict[str, Any] = {
        "status": status,
        "user_id": user_id,
        "integration_id": integration_id,
    }
    if status == "connected":
        update_data["connected_at"] = datetime.now(UTC)

    result = await user_integrations_collection.update_one(
        {"user_id": user_id, "integration_id": integration_id},
        {
            "$set": update_data,
            "$setOnInsert": {"created_at": datetime.now(UTC)},
        },
        upsert=True,
    )

    # Operation is successful if document was modified, inserted, or matched
    # (matched_count > 0 means document exists with same values - still success)
    if result.modified_count > 0 or result.upserted_id or result.matched_count > 0:
        logger.info(
            f"Updated user {user_id} integration {integration_id} status to {status}"
        )
        return True

    return False
