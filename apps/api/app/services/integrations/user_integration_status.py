"""
User integration status management.

This module is separated to avoid circular imports between
oauth_service.py and integration_service.py.
"""

from typing import Literal

from app.constants.cache import USER_INTEGRATION_CACHE_PATTERNS
from app.constants.log_tags import LogTag
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.caching import CacheInvalidator
from app.services.integrations_fs import schedule_user_integrations_sync
from shared.py.wide_events import log


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
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
    log.set(integration={"provider": integration_id, "action": "update_status"})

    success = await user_integration_repository.set_status(user_id, integration_id, status=status)

    if success:
        log.info(
            f"{LogTag.INTEGRATION} Updated user {user_id} integration {integration_id} status to {status}"
        )
        if status == "connected":
            # Reflect the new connected set in the user's workspace VFS.
            schedule_user_integrations_sync(user_id)
        return True

    return False
