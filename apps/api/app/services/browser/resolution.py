"""Resolve a pending browser handoff from the user's next chat message.

When a browser task is paused at a sensitive step and the user replies in chat
("yeah I paid, continue" / "no, stop") instead of clicking the card's buttons,
one scoped LLM call classifies the reply. This is the text-channel equivalent of
the Continue/Cancel buttons, same core (resolve_handoff), so it works
identically on web and bots. Mirrors the HIL conversational-resolution pattern.
"""

import string
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured_gemini
from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.services.browser.exceptions import BrowserHandoffNotOwned
from app.services.browser.handoff import (
    get_conversation_pending_handoff,
    get_handoff,
    resolve_handoff,
)
from shared.py.wide_events import log

HandoffReplyAction = Literal["continue", "cancel", "unrelated"]

# First words that carry a decision on their own, for the rule that stands in
# when the classifier is unavailable.
_CONTINUE_WORDS = frozenset({"done", "continue", "yes", "ok", "okay", "finished"})
_CANCEL_WORDS = frozenset({"stop", "cancel", "abort", "no"})


class HandoffReplyDecision(BaseModel):
    """Scoped classification of a reply to a pending browser handoff."""

    action: HandoffReplyAction
    #: Everything the reply asks for beyond the go-ahead itself. The run forwards
    #: it to the agent as a note, so a bare "done" must leave it unset rather than
    #: feed the acknowledgement back as an instruction.
    note: str | None = Field(
        default=None,
        description=(
            "The rest of the reply, verbatim, once the continue/cancel wording is "
            "removed. Null when the reply is only an acknowledgement."
        ),
    )


async def resolve_handoff_from_message(
    conversation_id: str, user_id: str, message: str
) -> HandoffReplyAction | None:
    """Resolve the conversation's pending browser handoff from message.

    Returns the classified action, or None when nothing is pending or the
    reply addressed none of it (so the normal turn runs).
    """
    handoff_id = await get_conversation_pending_handoff(conversation_id)
    if not handoff_id:
        return None
    record = await get_handoff(handoff_id)
    if record is None or record.status != HandoffStatus.PENDING:
        return None

    decision = await _interpret(message, record.reason)
    if decision.action == "unrelated":
        return "unrelated"

    kind = HandoffDecision.CONTINUE if decision.action == "continue" else HandoffDecision.CANCEL
    note = (decision.note or "").strip() or None
    try:
        await resolve_handoff(handoff_id, kind, user_id, message=note)
    except BrowserHandoffNotOwned:
        return None
    return decision.action


def keyword_reply_decision(message: str) -> HandoffReplyDecision:
    """Classify a reply by its first word alone, with the rest kept as the note.

    The rule the classifier degrades to: a provider outage must not swallow a
    plain "done" and start a new turn instead of resuming the paused task.
    """
    first, _, rest = message.strip().partition(" ")
    word = first.strip(string.punctuation).lower()
    if word in _CONTINUE_WORDS:
        return HandoffReplyDecision(action="continue", note=rest.strip() or None)
    if word in _CANCEL_WORDS:
        return HandoffReplyDecision(action="cancel")
    return HandoffReplyDecision(action="unrelated")


async def _interpret(message: str, reason: str) -> HandoffReplyDecision:
    """Classify the reply, on the lane that falls back when its provider fails.

    Degrades to the keyword rule rather than to unrelated: a failed classifier
    is not evidence that the user changed the subject.
    """
    try:
        return await ainvoke_structured_gemini(
            HandoffReplyDecision,
            _prompt(message, reason),
            label="browser_handoff_conversational_resolve",
        )
    except Exception as e:  # an LLM hiccup must not act on its own
        log.warning(
            f"{LogTag.BROWSER} Browser handoff resolve failed, using the keyword rule",
            error_type=type(e).__name__,
        )
        return keyword_reply_decision(message)


def _prompt(message: str, reason: str) -> str:
    return (
        "A browser automation task is paused, waiting for the user to finish a "
        f"sensitive step themselves in the live browser: {reason!r}\n\n"
        f"The user just sent this message:\n{message!r}\n\n"
        "Is the user telling the assistant to CONTINUE (they finished the step / "
        "gave the go-ahead), to CANCEL (stop the task), or is this an UNRELATED "
        "new request? Reply with action='continue', 'cancel', or 'unrelated', and "
        "put anything the user asks for beyond the go-ahead itself in 'note', "
        "verbatim — null when the reply is only an acknowledgement."
    )
