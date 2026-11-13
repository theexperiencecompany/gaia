"""The approvals a run asked for that have been settled: what a report tells the user was decided.

Read from the run's own cards, resolved against the stores that hold the decisions, so the
message says what the user decided rather than what the run's thread last saw.
"""

from app.agents.core.background.run_cards import approval_id_of_entry
from app.agents.core.background.session import ExecutorRun
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversations import conversation_repository
from app.models.hil_models import HILApprovalStatus, LedgerState
from app.services.hil.approvals_store import get_approval
from app.services.outbox.models import ApprovalOutcome, DecidedApproval

_LEDGER_OUTCOMES: dict[LedgerState, ApprovalOutcome] = {
    LedgerState.APPROVED: ApprovalOutcome.APPROVED,
    LedgerState.EXECUTING: ApprovalOutcome.APPROVED,
    LedgerState.EXECUTED: ApprovalOutcome.APPROVED,
    LedgerState.DENIED: ApprovalOutcome.DENIED,
    LedgerState.EXPIRED: ApprovalOutcome.EXPIRED,
    LedgerState.REVOKED: ApprovalOutcome.WITHDRAWN,
    LedgerState.FAILED: ApprovalOutcome.FAILED,
    LedgerState.UNKNOWN: ApprovalOutcome.UNKNOWN,
}

_BARRIER_OUTCOMES: dict[HILApprovalStatus, ApprovalOutcome] = {
    HILApprovalStatus.APPROVED: ApprovalOutcome.APPROVED,
    HILApprovalStatus.AUTO_APPROVED: ApprovalOutcome.APPROVED,
    HILApprovalStatus.DENIED: ApprovalOutcome.DENIED,
    HILApprovalStatus.TIMEOUT: ApprovalOutcome.EXPIRED,
    HILApprovalStatus.ABANDONED: ApprovalOutcome.WITHDRAWN,
}


async def _decided(approval_id: str) -> DecidedApproval | None:
    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is not None:
        ledger_outcome = _LEDGER_OUTCOMES.get(row.state)
        return (
            DecidedApproval(summary=row.summary, outcome=ledger_outcome) if ledger_outcome else None
        )
    record = await get_approval(approval_id)
    if record is None:
        return None
    barrier_outcome = _BARRIER_OUTCOMES.get(record.status)
    return (
        DecidedApproval(summary=record.summary, outcome=barrier_outcome)
        if barrier_outcome
        else None
    )


async def decided_approvals_of(run: ExecutorRun) -> list[DecidedApproval]:
    """Return the settled approvals among the cards the run left on its reply, in the order they were asked."""
    if not run.bot_message_id:
        return []
    message = await conversation_repository.get_message(
        run.conversation_id, run.bot_message_id, user_id=run.user.user_id
    )
    if message is None or not message.tool_data:
        return []
    approval_ids = [
        approval_id
        for entry in message.tool_data
        if (approval_id := approval_id_of_entry(entry)) is not None
    ]
    decided = [await _decided(approval_id) for approval_id in approval_ids]
    return [d for d in decided if d is not None]
