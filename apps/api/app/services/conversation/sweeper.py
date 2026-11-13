"""The conversation runtime's liveness sweep: whatever a dead process left, the next sweep finishes.

It flushes entries a crashed append left in a head's outbox, logs live work whose executor
died as lost (which wakes the step to tell the user), and starts a step for any conversation
with unsettled inputs; the step's claim refuses while a live holder still runs it. One pass
pages through every due head, and one conversation that fails is logged and passed over.
"""

from dataclasses import dataclass

from app.agents.core.background.executor_queue import run_is_lost
from app.constants.conversation import SWEEP_BATCH, WORK_LOST_REPORT
from app.db.repositories.conversation_log import SweepHead, conversation_log_repository
from app.models.conversation_log_models import WorkOutcome
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.work_log import WorkReport, record_work_finished
from shared.py.wide_events import log


@dataclass
class SweepReport:
    """What one sweep did."""

    flushed: int = 0
    lost_work: int = 0
    kicked: int = 0
    failed: int = 0


async def sweep_conversations() -> SweepReport:
    """Finish what dead processes left on step-run conversations: unflushed entries, lost work, unanswered inputs."""
    ports = runtime_ports()
    report = SweepReport()
    after: str | None = None
    while page := await conversation_log_repository.list_heads_to_sweep(SWEEP_BATCH, after):
        for head in page:
            try:
                await _sweep_one(ports, head, report)
            except Exception as e:  # one failing conversation must not stop the rest
                report.failed += 1
                log.error(
                    "conversation sweep failed for one conversation",
                    conversation_id=head.conversation_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )
        if len(page) < SWEEP_BATCH:
            break
        after = page[-1].cursor
    log.set(
        conversation_sweep={
            "flushed": report.flushed,
            "lost_work": report.lost_work,
            "kicked": report.kicked,
            "failed": report.failed,
        }
    )
    return report


async def _sweep_one(ports: RuntimePorts, head: SweepHead, report: SweepReport) -> None:
    conversation_id, user_id = head.conversation_id, head.user_id
    if head.has_outbox:
        await conversation_log_repository.flush_outbox(conversation_id, user_id=user_id)
        report.flushed += 1
    for work in head.state.work:
        # A run paused on an approval holds no liveness while it waits for the user.
        if work.pending_approvals or not await run_is_lost(conversation_id, work.task_id):
            continue
        await record_work_finished(
            conversation_id, user_id, work.task_id, WorkOutcome.LOST, WorkReport(WORK_LOST_REPORT)
        )
        report.lost_work += 1
    if head.state.unsettled_waking:
        await ports.effects.kick(conversation_id, user_id)
        report.kicked += 1
