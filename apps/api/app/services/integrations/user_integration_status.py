"""
User integration status management.

This module is separated to avoid circular imports between
oauth_service.py and integration_service.py.
"""

from app.constants.cache import USER_INTEGRATION_CACHE_PATTERNS
from app.constants.integrations import INTEGRATION_STATUS_UPDATE_EVENT
from app.constants.log_tags import LogTag
from app.core.websocket_manager import websocket_manager
from app.db.repositories.user_integrations import user_integration_repository
from app.decorators.caching import CacheInvalidator
from app.models.integration_models import UserIntegrationStatus
from app.services.integrations_fs import schedule_user_integrations_sync
from shared.py.wide_events import log


@CacheInvalidator(key_patterns=USER_INTEGRATION_CACHE_PATTERNS)
async def update_user_integration_status(
    user_id: str,
    integration_id: str,
    status: UserIntegrationStatus,
    expired_reason: str | None = None,
    connected_account_id: str | None = None,
) -> bool:
    """Upsert user integration status; creates the record if it doesn't exist.

    Called after OAuth/MCP connection or from the expiry transition.
    expired_reason stamps only the 'expired' transition; connected_account_id
    is the Composio connected-account nanoid, recorded whenever known.
    """
    log.set(integration={"provider": integration_id, "action": "update_status"})

    success = await user_integration_repository.set_status(
        user_id,
        integration_id,
        status=status,
        expired_reason=expired_reason,
        connected_account_id=connected_account_id,
    )

    if success:
        log.info(
            f"{LogTag.INTEGRATION} Updated user integration status to",
            user_id=user_id,
            integration_id=integration_id,
            status=status,
        )
        if status == "connected":
            # Reflect the new connected set in the user's workspace VFS.
            schedule_user_integrations_sync(user_id)
            # Push the live transition (mirrors the expiry push) so an open page
            # flips without a reload. Best-effort: a missed push catches up on the
            # next catalog read, so a broadcast failure (Redis down) must not fail.
            try:
                await websocket_manager.broadcast_to_user(
                    user_id=user_id,
                    message={
                        "type": INTEGRATION_STATUS_UPDATE_EVENT,
                        "data": {"integration_id": integration_id, "status": status},
                    },
                )
            except Exception as e:
                log.warning(
                    f"{LogTag.INTEGRATION} Failed to broadcast connected status",
                    integration_id=integration_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
        return True

    return False
