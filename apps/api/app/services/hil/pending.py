"""The approvals waiting on the user, as the conversation log has them, with their ledger envelopes."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.constants.conversation import APPROVAL_EXPIRY_GRACE
from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.conversation_log import conversation_log_repository
from app.models.conversation_log_models import ApprovalRequested
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.runtime import runtime_ports
from app.services.conversation.screen import approval_status
from app.services.hil.errors import ApprovalRequestNotFoundError
from shared.py.approvals import ApprovalStatus


@dataclass(frozen=True)
class PendingApproval:
    """An approval the log has open, under the number every surface shows it with."""

    number: int
    row: ApprovalLedgerDocument


async def pending_approvals(conversation_id: str, user_id: str) -> list[PendingApproval]:
    """Return the approvals the conversation's log has waiting, in the screen's order, each under its number.

    A typed "yes 2" names the number the request was logged with. A request logged before
    approvals were numbered takes its place in this list; a waiting one with no ledger row raises.
    One past its time is the sweep's to expire, never a reply's to decide.
    """
    asking = (await runtime_ports().log.state(conversation_id, user_id)).asking
    if not asking:
        return []
    logged = await conversation_log_repository.read_log(
        conversation_id, user_id=user_id, ids=[f"approval:{approval_id}" for approval_id in asking]
    )
    requests = {
        item.entry.approval_id: item.entry
        for item in logged or ()
        if isinstance(item.entry, ApprovalRequested)
    }
    if set(requests) != set(asking):
        raise ApprovalRequestNotFoundError()
    now = datetime.now(UTC)
    waiting = [
        approval_id
        for approval_id in asking
        if approval_status(requests[approval_id], None, ended_by=None, now=now)
        is ApprovalStatus.WAITING
    ]
    rows = await asyncio.gather(*map(approval_ledger_repository.get_by_approval_id, waiting))
    found = [row for row in rows if row is not None]
    if len(found) != len(waiting):
        raise ApprovalRequestNotFoundError()
    return [
        PendingApproval(number=requests[row.approval_id].number or place, row=row)
        for place, row in enumerate(found, start=1)
    ]


async def pending_approvals_by_owner(
    owner_run_type: str, owner_ids: list[str]
) -> dict[str, ApprovalLedgerDocument]:
    """Return each background owner's oldest approval its conversation's log still has pending."""
    rows = await approval_ledger_repository.list_by_owners(
        owner_run_type, owner_ids, created_since=_asked_since()
    )
    return await _oldest_waiting(rows, [row.owner_id for row in rows])


async def pending_approvals_by_task(task_ids: list[str]) -> dict[str, ApprovalLedgerDocument]:
    """Return each GAIA task's oldest approval its chat's log still has pending."""
    rows = await approval_ledger_repository.list_by_tasks(task_ids, created_since=_asked_since())
    return await _oldest_waiting(rows, [row.owner_task_id for row in rows])


def _asked_since() -> datetime:
    """Return the oldest moment an approval still waiting can have been asked at."""
    return datetime.now(UTC) - (
        timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS) + APPROVAL_EXPIRY_GRACE
    )


async def _oldest_waiting(
    rows: list[ApprovalLedgerDocument], owners: list[str | None]
) -> dict[str, ApprovalLedgerDocument]:
    """Map each owner to its oldest row whose conversation's log still has it pending."""
    conversations = list({(row.conversation_id, row.user_id) for row in rows})
    logged = await asyncio.gather(*(runtime_ports().log.state(*key) for key in conversations))
    states = dict(zip(conversations, logged, strict=True))  # pragma: no mutate — one per key
    oldest: dict[str, ApprovalLedgerDocument] = {}
    for row, owner in zip(rows, owners, strict=True):
        state = states[(row.conversation_id, row.user_id)]
        waiting = any(row.approval_id in work.pending_approvals for work in state.work)
        if waiting and owner is not None and owner not in oldest:
            oldest[owner] = row
    return oldest
