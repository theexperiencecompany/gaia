"""Resume driver: wake a background owner parked on a decided approval.

Live runs resume through the executor inbox (ticket redeem). Background runs
have no live run to wake, so an approval must RE-ENQUEUE the owning work and a
denial must leave a trace where the owner actually looks:

- Tracked todos: re-enqueue the todo in its parked conversation; a denial is
  recorded on the todo's activity log, which its next run reads.
- Workflows: re-queue with the receipt in the trigger context, so the run
  continues with the approval in context and the trace in its conversation.

Every resume costs a fresh human tap, so no count cap is needed. Everything
here is best-effort: a resume failure must never fail the tap that approved.
"""

from app.constants.log_tags import LogTag
from app.constants.todos import TodoActivityEvent
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.hil_models import ApprovalLedgerDocument
from app.services.analytics_service import capture
from app.services.todo_activity import record_activity
from app.services.workflow.execution_service import get_last_run_brief
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilResumed
from shared.py.wide_events import log


async def resume_owner_after_approval(row: ApprovalLedgerDocument) -> None:
    """Re-enqueue the background owner parked on this approved row. Never raises."""
    if not row.owner_run_type or not row.owner_id:
        return
    try:
        if not await approval_ledger_repository.claim_resume(row.approval_id):
            return
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} resume claim failed; skipping resume",
            approval_id=row.approval_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return
    try:
        if row.owner_run_type == "todo":
            await _resume_todo(row)
        elif row.owner_run_type == "workflow":
            await _resume_workflow(row)
        else:
            log.warning(
                f"{LogTag.HIL} unknown resume owner; skipping",
                approval_id=row.approval_id,
                owner_run_type=row.owner_run_type,
            )
    except Exception as e:
        log.warning(
            f"{LogTag.HIL} owner resume failed; the approval itself stands",
            approval_id=row.approval_id,
            owner_run_type=row.owner_run_type,
            owner_id=row.owner_id,
            error=str(e),
            error_type=type(e).__name__,
        )


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
    scheduled fire.
    """

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
    """Re-queue the workflow with the receipt in its trigger context.

    Re-enters through the normal queue (deterministic job id dedups a racing
    re-fire), carrying the approval receipt plus the prior execution's trace so
    the agent continues past the granted step instead of redoing it.
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
    await WorkflowQueueService.queue_workflow_execution(
        row.owner_id,
        row.user_id,
        {
            "resume_from_approval": row.approval_id,
            "approval_summary": row.summary,
            "approval_result": "granted",
            "prior_run_brief": brief,
        },
    )
    capture(
        UserId(row.user_id),
        HilResumed(approval_id=row.approval_id, owner_run_type="workflow"),
    )
