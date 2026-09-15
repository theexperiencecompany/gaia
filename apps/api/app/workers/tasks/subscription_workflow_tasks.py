"""The durable half of a billing change's workflow pause/resume.

The Dodo webhook writes the subscription row and then moves the user's
workflows. A Composio or Mongo failure in that second step is not recoverable by
the provider's retry — the row already carries the reported status, so a
redelivery reduces to "unchanged" and never reaches the workflows again. The
webhook hands the remainder here, where ARQ owns the retries and a lapsed user's
automation still stops (or a restored subscriber's still resumes) once the
dependency comes back.
"""

from typing import TypedDict

from arq import Retry

from app.constants.log_tags import LogTag
from app.constants.payments import (
    SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY,
    SubscriptionWorkflowSync,
)
from app.services.workflow.subscription_pause import SYNC_ACTIONS
from shared.py.wide_events import log

RETRY_BACKOFF_BASE = 2


class ArqJobContext(TypedDict, total=False):
    """The ARQ job context, narrowed to the key this task reads.

    job_try is absent only when a caller invokes the task with a bare context.
    """

    job_try: int


async def sync_workflows_for_subscription_state(ctx: ArqJobContext, user_id: str, sync: str) -> str:
    """Move the user's workflows the way their last billing change said to.

    Idempotent by construction — each half re-reads only the workflows still in
    the wrong state — so a retry after a partial run picks up just what is left.
    """
    direction = SubscriptionWorkflowSync(sync)
    job_try = ctx.get("job_try", 1)
    log.set(user={"id": user_id}, workflow_sync={"direction": direction.value, "try": job_try})

    try:
        moved = await SYNC_ACTIONS[direction](user_id)
    except Exception as e:
        # Broad on purpose: whatever stopped the sync, the workflow is still in
        # the wrong state and this task is the only thing coming back for it.
        # Retry re-raises rather than swallows, and max_tries bounds the chain.
        defer = SUBSCRIPTION_WORKFLOW_SYNC_RETRY_DELAY * RETRY_BACKOFF_BASE ** (job_try - 1)
        log.warning(
            f"{LogTag.WORKFLOW} Workflow subscription sync incomplete; retrying",
            user_id=user_id,
            direction=direction.value,
            error=str(e),
            error_type=type(e).__name__,
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer) from e

    return f"sync_workflows_for_subscription_state {direction.value} moved {moved} workflow(s)"
