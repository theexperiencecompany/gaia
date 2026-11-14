"""The approvals waiting on the user, as the conversation log has them, with their ledger envelopes."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.constants.conversation import APPROVAL_EXPIRY_GRACE
from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.runtime import runtime_ports


async def pending_approvals(conversation_id: str, user_id: str) -> list[ApprovalLedgerDocument]:
    """Return the envelopes of the approvals the conversation's log has pending, oldest first."""
    state = await runtime_ports().log.state(conversation_id, user_id)
    pending = sorted({approval for work in state.work for approval in work.pending_approvals})
    rows = await asyncio.gather(*map(approval_ledger_repository.get_by_approval_id, pending))
    return sorted(
        (row for row in rows if row is not None),
        key=lambda row: (row.created_at or datetime.min.replace(tzinfo=UTC), row.approval_id),
    )


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
