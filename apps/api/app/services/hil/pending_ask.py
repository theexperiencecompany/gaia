"""Which approval a user's reply is about, read from where GAIA asked it.

An approval is asked in whatever chat the user is in, not necessarily the conversation the
work belongs to, so a reply is matched to the ask it answers: the message it quotes, else
the latest message that asked. Only when neither names an open approval does the caller fall
back on the conversation's own pending approvals.
"""

from app.constants.hil import PENDING_ASK_LOOKBACK_MESSAGES
from app.db.repositories.approval_ledger import approval_ledger_repository
from app.db.repositories.outbound_receipts import outbound_receipts_repository
from app.db.repositories.outbox_messages import outbox_messages_repository
from app.models.hil_models import ApprovalLedgerDocument, LedgerState
from app.services.outbox.approvals import approval_id_of_report


async def _pending_rows(user_id: str, report_ids: list[str]) -> list[ApprovalLedgerDocument]:
    """Return the user's still-pending approvals among those a message's reports told, in the order told."""
    rows = [
        await approval_ledger_repository.get_by_approval_id(approval_id)
        for report_id in report_ids
        if (approval_id := approval_id_of_report(report_id)) is not None
    ]
    return [
        row
        for row in rows
        if row is not None and row.user_id == user_id and row.state is LedgerState.PENDING
    ]


async def _asked_in_quoted(user_id: str, platform_message_id: str) -> list[ApprovalLedgerDocument]:
    for attempt_id in await outbound_receipts_repository.outbox_message_ids_of(platform_message_id):
        message = await outbox_messages_repository.get_by_attempt(user_id, attempt_id)
        if message is not None and (rows := await _pending_rows(user_id, message.report_ids)):
            return rows
    return []


async def _asked_in_latest(user_id: str) -> list[ApprovalLedgerDocument]:
    for message in await outbox_messages_repository.recent_sent(
        user_id, limit=PENDING_ASK_LOOKBACK_MESSAGES
    ):
        if rows := await _pending_rows(user_id, message.report_ids):
            return rows
    return []


async def asked_approvals(
    user_id: str, reply_to_platform_message_id: str | None
) -> list[ApprovalLedgerDocument]:
    """Return the open approvals a reply is about: those in the message it quotes, else in the latest that asked.

    Empty when no message GAIA sent names an open approval.
    """
    if reply_to_platform_message_id is not None:
        quoted = await _asked_in_quoted(user_id, reply_to_platform_message_id)
        if quoted:
            return quoted
    return await _asked_in_latest(user_id)
