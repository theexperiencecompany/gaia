"""Every feature that follows a user's integrations, and the emitters the connect and disconnect paths call."""

from app.constants.log_tags import LogTag
from app.services.briefing.scouts.lifecycle import SCOUT_INTEGRATION_HOOKS
from app.services.integrations.hooks import IntegrationHooks
from shared.py.wide_events import log

INTEGRATION_HOOKS: tuple[IntegrationHooks, ...] = (SCOUT_INTEGRATION_HOOKS,)


async def emit_connected(user_id: str, integration_id: str) -> None:
    """Run every connect hook; one that fails is logged and never fails the connect."""
    for hooks in INTEGRATION_HOOKS:
        try:
            await hooks.on_connected(user_id, integration_id)
        except Exception as e:
            log.warning(
                f"{LogTag.INTEGRATION} An integration connect hook failed",
                hook=hooks.name,
                integration_id=integration_id,
                error=str(e),
                error_type=type(e).__name__,
            )


async def emit_disconnected(user_id: str, integration_id: str) -> None:
    """Run every disconnect hook; a failure propagates, so the disconnect fails with it."""
    for hooks in INTEGRATION_HOOKS:
        await hooks.on_disconnected(user_id, integration_id)
