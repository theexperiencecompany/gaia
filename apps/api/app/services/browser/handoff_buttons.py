"""A handoff decided by a button: the web card's, or the bot live-view page's.

The tap is the user's word in the conversation, so it is sent there as their
message and the step answers it like a typed one; without it the reply the agent
later voiced once called the user's own "skip the upvote" a mistake. Cancel is a
real stop of the job, as a "cancel" said in chat is: the run ends stopped and
nothing tells a result, rather than ending on its own and reporting.
"""

from app.constants.browser import (
    BROWSER_HANDOFF_CARD_DECISION,
    HANDOFF_DECISION_STATUS,
    HandoffDecision,
    HandoffStatus,
)
from app.constants.chat import ConversationSource
from app.constants.log_tags import LogTag
from app.db.repositories.conversations import conversation_repository
from app.models.conversation_send_models import SendMessageRequest
from app.models.user_models import AuthenticatedUser
from app.schemas.browser import HandoffRecord
from app.services.analytics_service import capture
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.handoff import cancel_handoff, get_handoff, resolve_handoff
from app.services.browser.job_stop import stop_job
from app.services.conversation.send import send_message
from shared.py.analytics import UserId
from shared.py.analytics.catalog.browser import BrowserHandoffResolved
from shared.py.wide_events import log


async def decide_handoff_by_button(
    handoff_id: str, decision: HandoffDecision, user_id: str, message: str | None
) -> HandoffStatus | None:
    """Apply a button's decision and send it to the conversation when it is the one that decided the handoff.

    Returns the decision of record, None when the handoff is gone; raises
    BrowserHandoffNotOwned for another user's handoff. A tap that arrived after
    the handoff was settled another way decided nothing, and is not recorded.
    """
    pending = await get_handoff(handoff_id)
    if decision is HandoffDecision.CANCEL:
        resolved = await _stop_from_card(handoff_id, pending, user_id)
    else:
        resolved = await resolve_handoff(handoff_id, decision, user_id, message)
    if resolved is None:
        return None
    log.info(
        f"{LogTag.BROWSER} Browser handoff decided", handoff_id=handoff_id, status=resolved.value
    )
    if (
        pending is not None
        and pending.status is HandoffStatus.PENDING
        and resolved is HANDOFF_DECISION_STATUS[decision]
        and pending.conversation_id
    ):
        note = (message or "").strip()
        words = f"{decision.value}: {note}" if note else decision.value
        conversation_id = pending.conversation_id
        surface = await conversation_repository.get_source(conversation_id, user_id=user_id)
        await send_message(
            conversation_id,
            AuthenticatedUser(user_id=user_id),
            SendMessageRequest(
                message_id=f"handoff:{handoff_id}",
                text=BROWSER_HANDOFF_CARD_DECISION.format(decision=words),
            ),
            surface or ConversationSource.WEB,
        )
    return resolved


async def _stop_from_card(
    handoff_id: str, pending: HandoffRecord | None, user_id: str
) -> HandoffStatus | None:
    """Stop the job a pending handoff pauses, settling the handoff cancelled; return its decision of record."""
    if pending is None:
        return None
    if pending.user_id != user_id:
        raise BrowserHandoffNotOwned("Not authorized to resolve this handoff")
    if pending.status is not HandoffStatus.PENDING:
        return pending.status
    # Stopped first, so the run cannot end on its own and tell a result the user declined.
    await stop_job(pending.job_id)
    resolved = await cancel_handoff(handoff_id)
    capture(
        UserId(user_id),
        BrowserHandoffResolved(decision=HandoffDecision.CANCEL.value, with_note=False),
    )
    return resolved
