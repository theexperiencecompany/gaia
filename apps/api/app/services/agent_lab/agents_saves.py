"""Run gaia-save from GAIA's side, telling the watching todos once when saves start failing."""

from e2b import AsyncSandbox

from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.agent_lab.agents_home import SAVE_SCRIPT, SAVE_TIMEOUT_SECONDS
from app.services.agent_lab.sandbox_events import SandboxEventKind, report_sandbox_event
from shared.py.wide_events import log


def _save_failed_key(user_id: str) -> str:
    """Redis flag: the last save failed and the todos were already told."""
    return f"lab:save_failed:{user_id}"


async def save_agents_home(user_id: str, sbx: AsyncSandbox) -> bool:
    """Run gaia-save; a failure wakes the watching todos once until a save succeeds again."""
    key = _save_failed_key(user_id)
    try:
        await sbx.commands.run(SAVE_SCRIPT, timeout=SAVE_TIMEOUT_SECONDS)
    except Exception as e:
        log.warning(
            f"{LogTag.SANDBOX} agents-home save failed",
            user_id=user_id,
            error_type=type(e).__name__,
            error=str(e),
        )
        if await redis_cache.client.set(key, "1", nx=True):
            await report_sandbox_event(
                user_id,
                SandboxEventKind.SAVE_FAILED,
                f"saving the coding agents' home failed: {str(e)[:500]}",
            )
        return False
    await redis_cache.client.delete(key)
    return True
