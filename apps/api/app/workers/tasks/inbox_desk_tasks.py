"""Inbox desk provisioning, retried by the worker until the desk is armed.

A Gmail connect or a plan start only queues the provisioning job, and a daily sweep
provisions every paying Gmail user, so no blip leaves a user without a desk for long.
"""

from collections.abc import Mapping

from arq import Retry

from app.constants.log_tags import LogTag
from app.constants.todos import INBOX_DESK_PROVISION_RETRY_DELAY
from app.services.todos.inbox_desk import provision_inbox_desk, reconcile_inbox_desks
from app.workers.task_envelope import RETRY_BACKOFF_BASE, ArqJobContext
from shared.py.wide_events import log


async def provision_inbox_desk_task(ctx: ArqJobContext, user_id: str) -> str:
    """Open or re-arm the user's Inbox desk; retry with backoff on any failure."""
    job_try = ctx.get("job_try", 1)
    try:
        await provision_inbox_desk(user_id)
    except Exception as e:
        # Broad on purpose: this job is the only thing coming back for the desk, and
        # Retry re-raises rather than swallows; max_tries bounds the chain.
        defer = INBOX_DESK_PROVISION_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            f"{LogTag.TODO} Inbox desk provisioning failed; retrying",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e
    return f"provision_inbox_desk {user_id}"


async def reconcile_inbox_desks_task(_ctx: Mapping[str, object]) -> str:
    """Give every paying Gmail user their desk; the daily safety net behind the queued jobs."""
    result = await reconcile_inbox_desks()
    log.set(inbox_desk_reconcile={"users": result.users, "failures": result.failures})
    return f"reconcile_inbox_desks visited {result.users} user(s), {result.failures} failure(s)"
