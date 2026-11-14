"""Resume driver: wake a background owner parked on a decided approval.

Live runs get the ticket through the executor inbox. Background runs have no
live run to wake, so an approval RE-ENQUEUES the owning work carrying the ticket
(that resume is the one continuation), and a denial leaves a trace where the
owner actually looks:

- Tracked todos: log the grant on the todo's activity and re-enqueue the todo
  in its parked conversation, which redeems the ticket; a denial is recorded on
  the same log, which its next run reads.
- Workflows: re-queue with the ticket in the trigger context, so the run
  redeems it and continues with the trace in its conversation.

Every resume costs a fresh human tap, so no count cap is needed; one that
cannot be enqueued raises to the tap.
"""

from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.hil_models import ApprovalLedgerDocument
from app.services.analytics_service import capture
from app.services.hil.errors import ResumeNotQueuedError, UnknownResumeOwnerError
from app.services.hil.ticket import approval_ticket
from app.services.todo_activity import record_activity
from app.services.workflow.execution_service import get_last_run_brief
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilResumed
from shared.py.wide_events import log


async def resume_owner_after_approval(row: ApprovalLedgerDocument) -> None:
    """Re-enqueue the background owner parked on this approved row, once per approval."""
    if not await approval_ledger_repository.claim_resume(row.approval_id):
        return
    match row.owner_run_type:
        case "todo":
            await _resume_todo(row)
        case "workflow":
            await _resume_workflow(row)
        case _:
            raise UnknownResumeOwnerError(row.approval_id, row.owner_run_type)


async def record_owner_deny(row: ApprovalLedgerDocument, feedback: str | None) -> None:
    """Leave a denial trace where a background owner looks. Never raises."""
    if row.owner_run_type != "todo" or not row.owner_id:
        return
    what = f" ({feedback!r})" if feedback else ""
    await record_activity(
        row.owner_id,
        row.user_id,
        TodoActivityEvent.APPROVAL_DENIED,
        f"{row.approval_id}{what}: skipped {row.summary}",
    )


async def _resume_todo(row: ApprovalLedgerDocument) -> None:
    """Resume in the PARKED conversation so the receipt joins the run's own thread.

    The lock/defer machinery stays the arbiter of concurrency, exactly like a
    scheduled fire. The grant is logged here, under the resume claim, because
    the resume job itself may be deferred and run again.
    """
    await record_activity(
        row.owner_id,
        row.user_id,
        TodoActivityEvent.APPROVAL_GRANTED,
        f"{row.approval_id}: {row.summary}; continuing the run in its own thread",
    )
    pool = await RedisPoolManager.get_pool()
    await enqueue_worker_job(
        pool,
        "resume_tracked_todo",
        row.owner_id,
        row.conversation_id,
        row.approval_id,
        row.summary,
    )
    capture(UserId(row.user_id), HilResumed(approval_id=row.approval_id, owner_run_type="todo"))


async def _resume_workflow(row: ApprovalLedgerDocument) -> None:
    """Re-queue the workflow with the ticket in its trigger context.

    Re-enters through the normal queue (deterministic job id dedups a racing
    re-fire), carrying the ticket plus the prior execution's trace so the agent
    redeems the granted step instead of redoing the run.
    """

    brief = ""
    try:
        brief = await get_last_run_brief(row.owner_id, row.user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} last-run brief unavailable; resuming without it",
            approval_id=row.approval_id,
            error=str(e),
            error_type=type(e).__name__,
        )
    queued = await WorkflowQueueService.queue_workflow_execution(
        row.owner_id,
        row.user_id,
        {
            "resume_from_approval": row.approval_id,
            "approval_summary": row.summary,
            "approval_ticket": approval_ticket(row),
            "prior_run_brief": brief,
        },
    )
    if not queued:
        raise ResumeNotQueuedError(row.approval_id, row.owner_run_type)
    capture(
        UserId(row.user_id),
        HilResumed(approval_id=row.approval_id, owner_run_type="workflow"),
    )
