"""
User integration status management.

This module is separated to avoid circular imports between
oauth_service.py and integration_service.py.
"""

from collections.abc import Awaitable

from pymongo.errors import PyMongoError

from app.constants.cache import USER_INTEGRATION_CACHE_PATTERNS
from app.constants.integrations import INTEGRATION_STATUS_UPDATE_EVENT
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.caching import CacheInvalidator
from app.models.integration_models import UserIntegrationStatus
from app.services.integrations_fs import schedule_user_integrations_sync
from shared.py.wide_events import log


async def publish_connected(user_id: str, integration_id: str) -> None:
    """Reflect a newly connected integration in the workspace VFS and on any open page."""
    schedule_user_integrations_sync(user_id)
    # Best-effort: a missed push catches up on the next catalog read, so a
    # broadcast failure (Redis down) must not fail the connect.
    try:
        await websocket_manager.broadcast_to_user(
            user_id=user_id,
            message={
                "type": INTEGRATION_STATUS_UPDATE_EVENT,
                "data": {"integration_id": integration_id, "status": "connected"},
            },
        )
    except Exception as e:
        log.warning(
            f"{LogTag.INTEGRATION} Failed to broadcast connected status",
            integration_id=integration_id,
            error=str(e),
            error_type=type(e).__name__,
        )


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def update_user_integration_status(
    user_id: str,
    integration_id: str,
    status: UserIntegrationStatus,
    expired_reason: str | None = None,
) -> bool:
    """Upsert user integration status; creates the record if it doesn't exist.

    Called after MCP/self-managed connection and on the connect start; Composio
    accounts write their state through integration_accounts.save_accounts.
    """
    log.set(integration={"provider": integration_id, "action": "update_status"})

    success = await user_integration_repository.set_status(
        user_id,
        integration_id,
        status=status,
        expired_reason=expired_reason,
    )
    if not success:
        return False

    log.info(
        f"{LogTag.INTEGRATION} Updated user integration status to",
        user_id=user_id,
        integration_id=integration_id,
        status=status,
    )
    if status == "connected":
        await publish_connected(user_id, integration_id)
    return True


async def reconnect_or_unknown(
    connected_before: Awaitable[bool], integration_id: str
) -> bool | None:
    """Await the connected-before lookup for an OAuth callback; None when Mongo cannot answer.

    It only labels integration:connected, so like the callbacks' own best-effort
    status write it must never fail the connect the user just completed.
    """
    try:
        return await connected_before
    except PyMongoError as e:
        log.warning(
            f"{LogTag.INTEGRATION} Could not tell whether the connect is a reconnect",
            integration_id=integration_id,
            error_type=type(e).__name__,
        )
        return None
