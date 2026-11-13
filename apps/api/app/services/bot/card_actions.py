"""Performing a tapped bot card button.

A button carries only an opaque id; the operation lives server-side
(card_action_store), so a button fits every platform's payload limit and a
forged id does nothing for another user. Each operation runs through the same
service the web card uses, and the tap and its outcome are written into the
conversation so the model knows what the user did.
"""

from typing import Literal

from app.agents.core.background.comms_narrator import record_exchange_in_thread
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.models.chat_models import ToolDataEntry
from app.schemas.bot_cards import BotCardActionOutcome, BotCardActionResult
from app.schemas.hil_schemas import ApprovalDecisionRequest
from app.services.analytics_service import capture
from app.services.bot.card_action_store import (
    ApprovalCardAction,
    CardAction,
    CardActionKind,
    SendEmailCardAction,
    load_card,
    load_card_action,
    spend_card_action,
    store_card,
)
from app.services.bot.card_settle import settle_card
from app.services.hil.decision_tap import decide_approval_tap
from app.services.hil.resolution import (
    ApprovalRequestForbiddenError,
    ApprovalRequestNotFoundError,
)
from app.services.mail.mail_service import EmailContent, send_draft, send_email
from shared.py.analytics import UserId
from shared.py.analytics.catalog.mail import EmailReplied, EmailSent
from shared.py.wide_events import log

_EXPIRED = BotCardActionResult(
    outcome=BotCardActionOutcome.EXPIRED, message="This button has expired. Ask GAIA again."
)


async def perform_card_action(
    action_id: str, user_id: str, platform: ConversationSource
) -> BotCardActionResult:
    """Perform the tapped button for user_id and record it in the card's conversation.

    A button is spent once its operation lands; a failed one stays tappable. Another
    user's id reads as expired, so a button's existence is never confirmed to them.
    """
    action = await load_card_action(action_id)
    if action is None or action.user_id != user_id:
        return _EXPIRED

    log.set(bot_card_action={"kind": action.kind.value, "platform": platform.value})
    result = await _perform(action)
    log.set_ns("bot_card_action", outcome=result.outcome.value)
    if result.outcome is BotCardActionOutcome.FAILED:
        return result

    await spend_card_action(action_id)
    card = await _settle_stored_card(action, action_id, result.outcome)
    if action.conversation_id:
        await record_exchange_in_thread(
            action.conversation_id,
            f'[The user tapped "{_VERBS[action.kind]}" on {action.subject} in {platform.display_name}]',
            f"[{result.message}]",
        )
    return result.model_copy(update={"card": card})


async def _settle_stored_card(
    action: CardAction, action_id: str, outcome: BotCardActionOutcome
) -> ToolDataEntry | None:
    """Settle the tapped card, keep the new state for its other buttons, and return it."""
    card = await load_card(action.card_id)
    if card is None:
        return None
    settled = settle_card(card, action_id, action.kind, outcome)
    await store_card(action.card_id, settled)
    return settled


_VERBS: dict[CardActionKind, str] = {
    CardActionKind.APPROVE: "Approve",
    CardActionKind.DENY: "Deny",
    CardActionKind.SEND_EMAIL: "Send",
}


async def _perform(action: CardAction) -> BotCardActionResult:
    match action:
        case ApprovalCardAction():
            return await _decide_approval(action)
        case SendEmailCardAction():
            return await _send_email(action)


async def _decide_approval(action: ApprovalCardAction) -> BotCardActionResult:
    decision: Literal["approve", "deny"] = (
        "approve" if action.kind is CardActionKind.APPROVE else "deny"
    )
    try:
        response = await decide_approval_tap(
            action.approval_id,
            action.user_id,
            ApprovalDecisionRequest(decision=decision, feedback=None),
        )
    except (ApprovalRequestNotFoundError, ApprovalRequestForbiddenError):
        return BotCardActionResult(
            outcome=BotCardActionOutcome.ALREADY_DONE, message="This request was already decided."
        )
    if not response.success:
        return BotCardActionResult(
            outcome=BotCardActionOutcome.ALREADY_DONE, message="This request was already decided."
        )
    return BotCardActionResult(
        outcome=BotCardActionOutcome.DONE,
        message="Approved." if decision == "approve" else "Denied.",
    )


async def _send_email(action: SendEmailCardAction) -> BotCardActionResult:
    if action.draft_id:
        result = await send_draft(user_id=action.user_id, draft_id=action.draft_id)
    else:
        result = await send_email(
            user_id=action.user_id,
            to=action.to[0],
            content=EmailContent(
                subject=action.subject_line,
                body=action.body,
                extra_recipients=action.to[1:],
                cc_list=action.cc,
                bcc_list=action.bcc,
            ),
            thread_id=action.thread_id,
        )
    if not result.successful:
        log.warning(f"{LogTag.MAIL} Bot card email send failed", error=result.error)
        return BotCardActionResult(
            outcome=BotCardActionOutcome.FAILED,
            message="Couldn't send the email. Try again, or send it from GAIA.",
        )
    capture(UserId(action.user_id), _email_sent_event(action))
    return BotCardActionResult(
        outcome=BotCardActionOutcome.DONE, message=f"Email sent to {', '.join(action.to)}."
    )


def _email_sent_event(action: SendEmailCardAction) -> EmailSent | EmailReplied:
    """Name the send as the web card's routes do: a stored draft, a reply, or a new email."""
    if action.draft_id:
        return EmailSent()
    if action.thread_id:
        return EmailReplied(has_attachments=False, attachment_count=0)
    return EmailSent(has_attachments=False, attachment_count=0)
