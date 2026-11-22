"""Resume driver: wake a background owner parked on a decided approval.

Live runs get the ticket through the executor inbox. Background runs have no
live run to wake, so an approval RE-ENQUEUES the owning work carrying the ticket
(that resume is the one continuation), and a denial leaves a trace where the
owner actually looks:

- GAIA tasks: log the grant on the task's log and re-enqueue it in its
  parked chat, which redeems the ticket; a denial is recorded on the
  same log, which its next run reads.
- Workflows: re-queue with the ticket in the trigger context, so the run
  redeems it and continues with the trace in its conversation.

Every resume costs a fresh human tap, so no count cap is needed; one that
cannot be enqueued raises, and the decision's hand-off is retried by the sweeper.
"""

from app.constants.log_tags import LogTag
from app.constants.tasks import RESUME_TASK_JOB, TaskLogEvent
from app.db.repositories.tasks import task_repository
from app.models.conversation_log_models import ApprovalDecided
from app.models.hil_models import ApprovalLedgerDocument
from app.services.analytics_service import capture
from app.services.hil.errors import ResumeNotQueuedError, UnknownResumeOwnerError
from app.services.hil.ticket import approval_ticket
from app.services.tasks.run_records import record_event
from app.services.workflow.execution_service import get_last_run_brief
from app.services.workflow.queue_service import WorkflowQueueService
from app.utils.redis_utils import RedisPoolManager
from app.workers.queue import enqueue_worker_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.hil import HilResumed
from shared.py.wide_events import log


async def resume_owner_after_approval(
    row: ApprovalLedgerDocument, decision: ApprovalDecided
) -> None:
    """Re-enqueue the background owner parked on this approved row; the decision's hand-off lease makes it once."""
    if row.owner_task_id:
        await _resume_task(row, row.owner_task_id)
        return
    match row.owner_run_type:
        case "workflow":
            await _resume_workflow(row, decision)
        case _:
            raise UnknownResumeOwnerError(row.approval_id, row.owner_run_type)


async def record_owner_deny(row: ApprovalLedgerDocument, feedback: str | None) -> None:
    """Leave a denial trace where a background owner looks. Never raises."""
    what = f" ({feedback!r})" if feedback else ""
    if row.owner_task_id:
        if task := await task_repository.get(row.owner_task_id, user_id=row.user_id):
            await record_event(
                task,
                TaskLogEvent.APPROVAL_DENIED,
                f"{row.approval_id}{what}: skipped {row.summary}",
            )


async def _resume_task(row: ApprovalLedgerDocument, task_id: str) -> None:
    """Continue the task's run in its parked chat; the grant is logged here, at the hand-off."""
    task = await task_repository.get(task_id, user_id=row.user_id)
    if task is None:
        return
    await record_event(
        task,
        TaskLogEvent.APPROVAL_GRANTED,
        f"{row.approval_id}: {row.summary}; continuing the run in its own chat",
    )
    await enqueue_worker_job(
        await RedisPoolManager.get_pool(),
        RESUME_TASK_JOB,
        task_id,
        row.conversation_id,
        row.approval_id,
        row.summary,
    )
    capture(UserId(row.user_id), HilResumed(approval_id=row.approval_id, owner_run_type="task"))


async def _resume_workflow(row: ApprovalLedgerDocument, decision: ApprovalDecided) -> None:
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
            "approval_ticket": approval_ticket(row, decision),
            "prior_run_brief": brief,
        },
    )
    if not queued:
        raise ResumeNotQueuedError(row.approval_id, row.owner_run_type)
    capture(
        UserId(row.user_id),
        HilResumed(approval_id=row.approval_id, owner_run_type="workflow"),
    )
