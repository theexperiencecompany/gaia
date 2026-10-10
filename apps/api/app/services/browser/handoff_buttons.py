"""A handoff decided by a button: the web card's, or the bot live-view page's.

No turn runs for a tap, so the agent's thread never sees the decision unless it
is written there; the reply the agent later voiced once called the user's own
"skip the upvote" a mistake. A chat reply needs none of this: its turn reads it.
Cancel is a real stop of the job, as a "cancel" said in chat is: the run ends
stopped and nothing tells a result, rather than ending on its own and reporting.
"""

from app.agents.core.background.comms_narrator import record_exchange_in_thread
from app.constants.browser import (
    BROWSER_HANDOFF_ACK_CANCEL,
    BROWSER_HANDOFF_ACK_CONTINUE,
    BROWSER_HANDOFF_CARD_DECISION,
    HANDOFF_DECISION_STATUS,
    HandoffDecision,
    HandoffStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import HandoffRecord
from app.services.analytics_service import capture
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.handoff import cancel_handoff, get_handoff, resolve_handoff
from app.services.browser.job_stop import stop_job
from shared.py.analytics import UserId
from shared.py.analytics.catalog.browser import BrowserHandoffResolved
from shared.py.wide_events import log

_ACKS = {
    HandoffDecision.CONTINUE: BROWSER_HANDOFF_ACK_CONTINUE,
    HandoffDecision.CANCEL: BROWSER_HANDOFF_ACK_CANCEL,
}


async def decide_handoff_by_button(
    handoff_id: str, decision: HandoffDecision, user_id: str, message: str | None
) -> HandoffStatus | None:
    """Apply a button's decision and record it in the agent's thread when it is the one that decided the handoff.

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
        await record_exchange_in_thread(
            pending.conversation_id,
            BROWSER_HANDOFF_CARD_DECISION.format(decision=words),
            _ACKS[decision],
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
