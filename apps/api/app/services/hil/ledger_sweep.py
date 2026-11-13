"""The clock's part in ledger approvals: remind once before an ask lapses, expire it when it does.

Cron-driven (the every-minute HIL sweep). Expiry is a decision like any other, so it goes
through ledger_decide and wakes the run that proposed the action; the reminder is a notice
filed with the outbox under a fixed report id, so two sweeps file one.
"""

from typing import TypedDict

from app.constants.log_tags import LogTag
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.services.hil.ledger_decide import decide_ledger
from app.services.outbox.approvals import ApprovalNoticeState, ledger_approval_notice
from app.services.outbox.intake import submit
from app.utils import clock
from shared.py.wide_events import log


class LedgerSweepCounts(TypedDict):
    """What one ledger sweep did."""

    expired: int
    reminded: int


async def sweep_ledger_approvals() -> LedgerSweepCounts:
    """Expire the asks that ran out, then remind the ones about to; one bad row never strands the rest."""
    now = clock.now()
    expired = 0
    for row in await approval_ledger_repository.list_pending_expired(now):
        try:
            decision = await decide_ledger(
                row.approval_id, user_id=row.user_id, kind="expire", via="expiry"
            )
        except Exception as e:
            log.error(
                f"{LogTag.HIL} Sweep could not expire a ledger approval",
                approval_id=row.approval_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            continue
        expired += decision.committed

    reminded = 0
    for row in await approval_ledger_repository.list_pending_reminders_due(now):
        try:
            await submit(ledger_approval_notice(row, ApprovalNoticeState.REMINDER, now=now))
        except Exception as e:
            log.error(
                f"{LogTag.HIL} Sweep could not file an approval reminder",
                approval_id=row.approval_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            continue
        reminded += await approval_ledger_repository.mark_reminded(row.approval_id)
    return {"expired": expired, "reminded": reminded}
