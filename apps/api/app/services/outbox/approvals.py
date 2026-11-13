"""Approvals as the outbox sees them: the ask and its one reminder are reports, the ledger row is the truth.

A pending approval is filed as a needs_you notice on its own subject. The notice carries
facts, never words: compose says the ask in GAIA's voice, in the thread it joins. Whether
an ask is still worth telling is read from the stores when it is about to go out, so an
approval answered while its message was composing is never told.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.constants.outbox import APPROVAL_REPORT_PREFIX, APPROVAL_SUBJECT_PREFIX
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.todos import todo_repository
from app.models.hil_models import ApprovalLedgerDocument, HILApprovalStatus, LedgerState
from app.services.hil.approvals_store import get_approval
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    Subject,
    SubjectKind,
)


class ApprovalNoticeState(StrEnum):
    """Which telling of an approval a notice is."""

    PENDING = "pending"
    REMINDER = "reminder"


def approval_subject_id(approval_id: str) -> str:
    """Return the subject id every notice of one approval shares."""
    return f"{APPROVAL_SUBJECT_PREFIX}{approval_id}"


def approval_id_of_report(report_id: str) -> str | None:
    """Return the approval a notice's report id names, or None when it is not an approval notice."""
    if not report_id.startswith(APPROVAL_REPORT_PREFIX):
        return None
    approval_id, _, state = report_id.removeprefix(APPROVAL_REPORT_PREFIX).rpartition(":")
    return approval_id if approval_id and state in set(ApprovalNoticeState) else None


@dataclass(frozen=True, slots=True)
class ApprovalAsk:
    """An approval waiting on the user, as the outbox needs to know it."""

    approval_id: str
    user_id: str
    conversation_id: str
    summary: str
    expires_at: datetime | None
    #: True for work the user scheduled (a workflow, a todo): its ask answers their own wish, as an ask in a chat does.
    set_up_by_user: bool


def approval_notice(ask: ApprovalAsk, state: ApprovalNoticeState, *, now: datetime) -> NoticeReport:
    """Return the notice that tells the user an approval waits on them."""
    facts = [f"Needs the user's yes or no before it can happen: {ask.summary}."]
    if state is ApprovalNoticeState.REMINDER:
        facts.append("They were already asked and have not answered.")
    if ask.expires_at is not None:
        facts.append(f"The request lapses on {ask.expires_at.isoformat(timespec='minutes')}.")
    return NoticeReport(
        report_id=f"{APPROVAL_REPORT_PREFIX}{ask.approval_id}:{state.value}",
        recipient=ask.user_id,
        producer=ProducerKind.APPROVAL,
        subject=Subject(
            kind=SubjectKind.APPROVAL,
            id=approval_subject_id(ask.approval_id),
            owner_conversation_id=ask.conversation_id,
            label=ask.summary,
        ),
        occurred_at=now,
        initiative=Initiative.USER_SCHEDULED if ask.set_up_by_user else Initiative.ASKED,
        outcome=NoticeOutcome.NEEDS_YOU,
        facts=facts,
        valid_until=ask.expires_at,
    )


async def ledger_approval_notice(
    row: ApprovalLedgerDocument, state: ApprovalNoticeState, *, now: datetime
) -> NoticeReport:
    """Return the notice for a ledger approval; work a background owner parked on was set up by the user.

    A todo run's approval is told where the todo was asked, since its own chat is one the user never opens.
    """
    ask = ApprovalAsk(
        approval_id=row.approval_id,
        user_id=row.user_id,
        conversation_id=await _told_in_conversation(row),
        summary=row.summary,
        expires_at=row.expires_at,
        set_up_by_user=bool(row.owner_run_type),
    )
    return approval_notice(ask, state, now=now)


async def _told_in_conversation(row: ApprovalLedgerDocument) -> str:
    if row.owner_run_type != "todo" or not row.owner_id:
        return row.conversation_id
    todo = await todo_repository.get_by_id(row.owner_id)
    if todo is None:
        return row.conversation_id
    conversation_id, _ = todo.answer_location(
        runs_once=todo.runs_once, own_chat=row.conversation_id
    )
    return conversation_id


async def is_approval_open(approval_id: str) -> bool:
    """Whether the user can still answer the approval, in the ledger or the older parked-run store."""
    row = await approval_ledger_repository.get_by_approval_id(approval_id)
    if row is not None:
        return row.state is LedgerState.PENDING
    record = await get_approval(approval_id)
    return record is not None and record.status is HILApprovalStatus.PENDING
