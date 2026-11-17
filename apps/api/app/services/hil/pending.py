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
from app.services.hil.errors import ApprovalRequestNotFoundError


@dataclass(frozen=True)
class PendingApproval:
    """An approval the log has open, under the number every surface shows it with."""

    number: int
    row: ApprovalLedgerDocument


async def pending_approvals(conversation_id: str, user_id: str) -> list[PendingApproval]:
    """Return the approvals the conversation's log has pending, in the screen's order, each under its number.

    A typed "yes 2" names the number the request was logged with. A request logged before
    approvals were numbered takes its place in this list; a pending one with no ledger row raises.
    """
    asking = (await runtime_ports().log.state(conversation_id, user_id)).asking
    rows = await asyncio.gather(*map(approval_ledger_repository.get_by_approval_id, asking))
    found = [row for row in rows if row is not None]
    if len(found) != len(asking):
        raise ApprovalRequestNotFoundError()
    logged = await conversation_log_repository.read_log(
        conversation_id, user_id=user_id, ids=[f"approval:{approval_id}" for approval_id in asking]
    )
    numbers = {
        item.entry.approval_id: item.entry.number
        for item in logged or ()
        if isinstance(item.entry, ApprovalRequested)
    }
    if set(numbers) != set(asking):
        raise ApprovalRequestNotFoundError()
    return [
        PendingApproval(number=numbers[row.approval_id] or place, row=row)
        for place, row in enumerate(found, start=1)
    ]


async def pending_approvals_by_owner(
    owner_run_type: str, owner_ids: list[str]
) -> dict[str, ApprovalLedgerDocument]:
    """Return each background owner's oldest approval its conversation's log still has pending."""
    asked_since = datetime.now(UTC) - (
        timedelta(seconds=HIL_APPROVAL_TIMEOUT_SECONDS) + APPROVAL_EXPIRY_GRACE
    )
    rows = await approval_ledger_repository.list_by_owners(
        owner_run_type, owner_ids, created_since=asked_since
    )
    conversations = list({(row.conversation_id, row.user_id) for row in rows})
    logged = await asyncio.gather(*(runtime_ports().log.state(*key) for key in conversations))
    states = dict(zip(conversations, logged, strict=True))  # pragma: no mutate — one per key
    oldest: dict[str, ApprovalLedgerDocument] = {}
    for row in rows:
        state = states[(row.conversation_id, row.user_id)]
        waiting = any(row.approval_id in work.pending_approvals for work in state.work)
        if waiting and row.owner_id not in oldest:
            oldest[row.owner_id] = row
    return oldest
