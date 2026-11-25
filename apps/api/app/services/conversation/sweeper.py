"""The conversation runtime's liveness sweep: whatever a dead process left, the next sweep finishes.

It carries out approval decisions whose hand-off to their work failed, flushes entries a
crashed append left in a head's outbox, logs live work whose executor
died as lost and work whose own finish was never saved as failed (either wakes the step
to tell the user), settles work paused on an approval that can no longer be decided, and
starts a step for any conversation with unsettled inputs; the step's claim refuses while a live holder still runs it. One pass pages through
every due head, and one conversation that fails is logged and passed over.

The log is what says an approval is pending and when it lapses. The ledger is read only to
learn whether its envelope still exists, without which nobody can decide it.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.agents.core.background.executor_queue import run_is_lost
from app.constants.conversation import (
    APPROVAL_EXPIRY_GRACE,
    APPROVAL_REGISTER_GRACE,
    SWEEP_BATCH,
)
from app.constants.hil import DECISION_HANDOFF_LEASE
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversation_sweep import SweepHead, conversation_sweep_repository
from app.models.conversation_log_models import (
    ApprovalRequested,
    LiveWork,
    WorkOutcome,
)
from app.services.conversation.ports import RuntimePorts
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.screen import approval_status
from app.services.conversation.work_log import record_work_lost
from app.services.hil.ledger_decide import (
    end_unledgered_approval,
    expire_ledger_approval,
    hand_off_stale_decision,
)
from shared.py.approvals import ApprovalOutcome, ApprovalStatus
from shared.py.wide_events import log


@dataclass
class SweepReport:
    """What one sweep did."""

    flushed: int = 0
    lost_work: int = 0
    unsaved_work: int = 0
    undecidable_approvals: int = 0
    kicked: int = 0
    handed_off: int = 0
    failed: int = 0


async def sweep_conversations() -> SweepReport:
    """Finish what dead processes left on step-run conversations: unflushed entries, lost work, unanswered inputs."""
    ports = runtime_ports()
    report = SweepReport()
    after: str | None = None
    await _hand_off_stale_decisions(ports.clock(), report)
    while page := await conversation_sweep_repository.list_heads_to_sweep(SWEEP_BATCH, after):
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
            "unsaved_work": report.unsaved_work,
            "undecidable_approvals": report.undecidable_approvals,
            "kicked": report.kicked,
            "handed_off": report.handed_off,
            "failed": report.failed,
        }
    )
    return report


async def _hand_off_stale_decisions(now: datetime, report: SweepReport) -> None:
    """Carry out every logged decision whose hand-off to its work failed; one that fails again waits for the next sweep."""
    for row in await approval_ledger_repository.list_stale_deliveries(now - DECISION_HANDOFF_LEASE):
        try:
            if await hand_off_stale_decision(row, now):
                report.handed_off += 1
        except Exception as e:  # one failing hand-off must not stop the rest
            report.failed += 1
            log.error(
                "approval decision hand-off failed again",
                approval_id=row.approval_id,
                conversation_id=row.conversation_id,
                error_type=type(e).__name__,
                error=str(e),
            )


async def _sweep_one(ports: RuntimePorts, head: SweepHead, report: SweepReport) -> None:
    conversation_id, user_id = head.conversation_id, head.user_id
    if head.has_outbox:
        await conversation_sweep_repository.flush_outbox(conversation_id, user_id=user_id)
        report.flushed += 1
    for work in head.state.work:
        if work.pending_approvals:
            await _settle_undecidable(head, work, ports.clock, report)
            continue
        if not await run_is_lost(conversation_id, work.task_id):
            continue
        if await record_work_lost(conversation_id, user_id, work.task_id) is WorkOutcome.LOST:
            report.lost_work += 1
        else:
            report.unsaved_work += 1
    if head.state.unsettled_waking:
        await ports.effects.kick(conversation_id, user_id)
        report.kicked += 1


async def _settle_undecidable(
    head: SweepHead, work: LiveWork, clock: Callable[[], datetime], report: SweepReport
) -> None:
    """Settle the approvals work waits on that nobody can decide; with none left to wait on, end the work.

    Every ending is a decision like any other: the log takes it once and the work resumes with it,
    so the sweep never ends the work itself.
    """
    conversation_id, user_id = head.conversation_id, head.user_id
    logged = await conversation_sweep_repository.read_log(
        conversation_id, user_id=user_id, ids=[f"approval:{a}" for a in work.pending_approvals]
    )
    requested = {
        entry.entry.approval_id: (entry.entry, entry.at)
        for entry in logged or ()
        if isinstance(entry.entry, ApprovalRequested)
    }
    for approval_id in sorted(work.pending_approvals):
        if await _end_undecidable(conversation_id, user_id, *requested[approval_id], clock):
            report.undecidable_approvals += 1


async def _end_undecidable(
    conversation_id: str,
    user_id: str,
    requested: ApprovalRequested,
    asked_at: datetime,
    clock: Callable[[], datetime],
) -> bool:
    """End an approval nobody can decide and resume its work; False while one still can, or a decision beat this one.

    Expired when it ran out of time; withdrawn when the ledger never got its envelope.
    """
    now = clock()
    # The grace lets a decision made at the deadline land before the sweep expires it.
    expired = (
        approval_status(requested, None, ended_by=None, now=now - APPROVAL_EXPIRY_GRACE)
        is ApprovalStatus.EXPIRED
    )
    row = await approval_ledger_repository.get_by_approval_id(requested.approval_id)
    if row is not None:
        return expired and await expire_ledger_approval(row)
    if not expired and asked_at + APPROVAL_REGISTER_GRACE > now:
        # Its gate may still be registering the row.
        return False
    return await end_unledgered_approval(
        conversation_id,
        user_id,
        requested,
        ApprovalOutcome.EXPIRED if expired else ApprovalOutcome.WITHDRAWN,
    )
