"""Which approval a user's reply is about, read from where GAIA asked it.

An approval is asked in whatever chat the user is in, not necessarily the conversation the
work belongs to, so a reply is matched to the ask it answers: the message it quotes, else the
latest message that asked in the chat the reply came from. A message sent to another chat is
never what a reply here answers.
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


async def quoted_approvals(
    user_id: str, reply_to_platform_message_id: str | None
) -> list[ApprovalLedgerDocument]:
    """Return the open approvals in the message a reply quotes; empty when it quotes none or none asked."""
    if reply_to_platform_message_id is None:
        return []
    return await _asked_in_quoted(user_id, reply_to_platform_message_id)


async def latest_approvals_in_chat(
    user_id: str, conversation_id: str
) -> list[ApprovalLedgerDocument]:
    """Return the open approvals in the latest message that asked in this chat; empty when none did."""
    for message in await outbox_messages_repository.recent_sent_in(
        user_id, conversation_id, limit=PENDING_ASK_LOOKBACK_MESSAGES
    ):
        if rows := await _pending_rows(user_id, message.report_ids):
            return rows
    return []
