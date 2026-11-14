"""The approvals waiting on the user, as the conversation log has them, with their ledger envelopes."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.constants.conversation import APPROVAL_EXPIRY_GRACE
from app.constants.hil import HIL_APPROVAL_TIMEOUT_SECONDS
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.models.hil_models import ApprovalLedgerDocument
from app.services.conversation.runtime import runtime_ports
from app.services.hil.errors import ApprovalRequestNotFoundError


async def pending_approvals(conversation_id: str, user_id: str) -> list[ApprovalLedgerDocument]:
    """Return the envelopes of the approvals the conversation's log has pending, in the screen's order.

    A typed "yes to 2" indexes this list, so a pending approval with no ledger row raises
    rather than shifting every number after it.
    """
    asking = (await runtime_ports().log.state(conversation_id, user_id)).asking
    rows = await asyncio.gather(*map(approval_ledger_repository.get_by_approval_id, asking))
    found = [row for row in rows if row is not None]
    if len(found) != len(asking):
        raise ApprovalRequestNotFoundError()
    return found


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
    conversations = {(row.conversation_id, row.user_id) for row in rows}
    states = dict(
        zip(
            conversations,
            await asyncio.gather(
                *(
                    runtime_ports().log.state(conversation, user)
                    for conversation, user in conversations
                )
            ),
            strict=True,
        )
    )
    oldest: dict[str, ApprovalLedgerDocument] = {}
    for row in rows:
        state = states[(row.conversation_id, row.user_id)]
        waiting = any(row.approval_id in work.pending_approvals for work in state.work)
        if waiting and row.owner_id not in oldest:
            oldest[row.owner_id] = row
    return oldest
