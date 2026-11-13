"""The conversation runtime's liveness sweep: whatever a dead process left, the next sweep finishes.

It flushes entries a crashed append left in a head's outbox, logs live work whose executor
died as lost (which wakes the step to tell the user), settles work paused on an approval
that can no longer be decided, and starts a step for any conversation with unsettled
inputs; the step's claim refuses while a live holder still runs it. One pass pages through
every due head, and one conversation that fails is logged and passed over.

The log is what says an approval is pending. The approval stores are read only to learn
whether one can still decide it: a record still pending there, and not long expired.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.agents.core.background.executor_queue import run_is_lost
from app.constants.conversation import (
    APPROVAL_EXPIRY_GRACE,
    APPROVAL_UNDECIDABLE_REPORT,
    SWEEP_BATCH,
    WORK_LOST_REPORT,
)
from app.constants.hil import ApprovalResolution
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversation_log import SweepHead, conversation_log_repository
from app.models.conversation_log_models import ApprovalRequested, LiveWork, WorkOutcome
from app.models.hil_models import HILApprovalStatus, LedgerState
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.work_log import (
    WorkReport,
    record_approval_decided,
    record_work_finished,
)
from app.services.hil.approvals_store import get_approval
from app.services.hil.ledger_decide import cancel_ledger_approvals
from app.services.hil.resolution import cancel_conversation_approvals
from shared.py.wide_events import log


@dataclass
class SweepReport:
    """What one sweep did."""

    flushed: int = 0
    lost_work: int = 0
    undecidable_approvals: int = 0
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
            "undecidable_approvals": report.undecidable_approvals,
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
        if work.pending_approvals:
            await _settle_undecidable(head, work, ports.clock, report)
            continue
        if not await run_is_lost(conversation_id, work.task_id):
            continue
        await record_work_finished(
            conversation_id, user_id, work.task_id, WorkOutcome.LOST, WorkReport(WORK_LOST_REPORT)
        )
        report.lost_work += 1
    if head.state.unsettled_waking:
        await ports.effects.kick(conversation_id, user_id)
        report.kicked += 1


async def _settle_undecidable(
    head: SweepHead, work: LiveWork, clock: Callable[[], datetime], report: SweepReport
) -> None:
    """Settle the approvals work waits on that nobody can decide; with none left to wait on, end the work."""
    conversation_id, user_id = head.conversation_id, head.user_id
    requested = await conversation_log_repository.read_log(
        conversation_id, user_id=user_id, ids=[f"approval:{a}" for a in work.pending_approvals]
    )
    expiries = {
        logged.entry.approval_id: logged.entry.expires_at
        for logged in requested or ()
        if isinstance(logged.entry, ApprovalRequested)
    }
    settled = 0
    for approval_id in sorted(work.pending_approvals):
        expires_at = expiries.get(approval_id)
        expired = expires_at is not None and expires_at + APPROVAL_EXPIRY_GRACE < clock()
        decision = await _undecidable_as(conversation_id, user_id, approval_id, expired=expired)
        if decision is None:
            continue
        await record_approval_decided(conversation_id, user_id, approval_id, decision)
        settled += 1
    report.undecidable_approvals += settled
    if settled == len(work.pending_approvals):
        await record_work_finished(
            conversation_id,
            user_id,
            work.task_id,
            WorkOutcome.FAILED,
            WorkReport(APPROVAL_UNDECIDABLE_REPORT),
        )


async def _undecidable_as(
    conversation_id: str, user_id: str, approval_id: str, *, expired: bool
) -> ApprovalResolution | None:
    """Return how an approval nobody can decide settles, closing its record; None while one still can."""
    barrier = await get_approval(approval_id)
    ledger = await approval_ledger_repository.get_by_approval_id(approval_id)
    pending = (barrier is not None and barrier.status is HILApprovalStatus.PENDING) or (
        ledger is not None and ledger.state is LedgerState.PENDING
    )
    if pending and not expired:
        return None
    if barrier is not None or ledger is not None:
        if not pending:
            # Decided in its store: that decision's own path logs it and resumes the work.
            return None
        await cancel_conversation_approvals(conversation_id, user_id, [approval_id])
        await cancel_ledger_approvals(conversation_id, user_id, [approval_id])
    return "timeout" if expired else "abandon"
