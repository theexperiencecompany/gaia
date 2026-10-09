"""Inbox desk provisioning, retried by the worker until the desk is armed.

A Gmail connect or a plan start only queues the provisioning job; users who had both
before the desk shipped get theirs from scripts/provision_inbox_desks.py.
"""

from arq import Retry

from app.constants.log_tags import LogTag
from app.constants.todos import INBOX_DESK_PROVISION_RETRY_DELAY
from app.services.todos.inbox_desk import provision_inbox_desk
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
