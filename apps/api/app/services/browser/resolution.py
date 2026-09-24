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

HandoffReplyAction = Literal["continue", "cancel", "redirect", "unrelated"]

# First words that carry a decision on their own, for the rule that stands in
# when the classifier is unavailable.
_CONTINUE_WORDS = frozenset({"done", "continue", "yes", "ok", "okay", "finished"})
_CANCEL_WORDS = frozenset({"stop", "cancel", "abort", "no"})
_ACKNOWLEDGEMENT_WORDS = _CONTINUE_WORDS | _CANCEL_WORDS

# Openers that decline the paused step. Followed by more text they redirect the
# run rather than cancel it, so they are matched before the first-word rule.
_DECLINE_MARKERS = (
    "never mind",
    "nevermind",
    "don't bother",
    "no need",
    "skip",
    "forget",
    "instead",
)

_RESOLVE_PROMPT = (
    "A browser automation task is paused, waiting for the user to finish a "
    "sensitive step themselves in the live browser: {reason!r}\n\n"
    "The user just sent this message:\n{message!r}\n\n"
    "Classify the reply as exactly one of:\n"
    "- 'continue': they finished the step or gave the go-ahead.\n"
    "- 'cancel': they want the whole task stopped.\n"
    "- 'redirect': they will NOT do the paused step, but they tell you what "
    "to do instead, so the task carries on with that new instruction. "
    "Examples: 'never mind the login, just tell me what the github.com "
    "homepage headline says', 'skip the upvote, just tell me the title of "
    "the top post on r/python', 'forget the payment, read me the total'. "
    "For a redirect, 'note' must hold the ENTIRE new instruction.\n"
    "- 'unrelated': the reply has nothing to do with the paused task, such "
    "as 'what's the weather'.\n\n"
    "Put anything the user asks for beyond the go-ahead itself in 'note', "
    "verbatim. Leave 'note' null when the reply is only an acknowledgement."
)


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

    kind = HandoffDecision.CANCEL if decision.action == "cancel" else HandoffDecision.CONTINUE
    note = (decision.note or "").strip() or None
    try:
        await resolve_handoff(handoff_id, kind, user_id, message=note)
    except BrowserHandoffNotOwned:
        log.warning(
            f"{LogTag.BROWSER} Handoff reply ignored: the handoff belongs to another user",
            browser={"handoff_id": handoff_id},
            user_id=user_id,
        )
        return None
    return decision.action


def keyword_reply_decision(message: str) -> HandoffReplyDecision:
    """Classify a reply by its first word alone, with the rest kept as the note.

    The rule the classifier degrades to: a provider outage must not swallow a
    plain "done" and start a new turn instead of resuming the paused task.
    """
    text = message.strip()
    if _declines_with_an_instruction(text):
        return HandoffReplyDecision(action="redirect", note=text)
    first, _, rest = text.partition(" ")
    word = first.strip(string.punctuation).lower()
    if word in _CONTINUE_WORDS:
        return HandoffReplyDecision(action="continue", note=rest.strip() or None)
    if word in _CANCEL_WORDS:
        return HandoffReplyDecision(action="cancel")
    return HandoffReplyDecision(action="unrelated")


def _declines_with_an_instruction(text: str) -> bool:
    """Report whether the reply opens by declining the paused step and still asks for something."""
    lowered = text.lower()
    for marker in _DECLINE_MARKERS:
        if not lowered.startswith(marker):
            continue
        rest = lowered[len(marker) :]
        # "skipper is my dog" opens with the letters of a marker, not the word.
        if rest[:1].isalnum():
            continue  # pragma: no mutate — no marker prefixes a later one, so break is the same
        if rest.strip(string.punctuation + string.whitespace):
            return True
    return False


def _without_an_acknowledgement_note(decision: HandoffReplyDecision) -> HandoffReplyDecision:
    """Blank a note that is only the go-ahead word, which the run would obey as an instruction."""
    if decision.action == "redirect" or not decision.note:
        return decision
    words = {w.strip(string.punctuation).lower() for w in decision.note.split()}
    if words <= _ACKNOWLEDGEMENT_WORDS:  # pragma: no mutate — < differs only on all ten words
        return decision.model_copy(update={"note": None})
    return decision


async def _interpret(message: str, reason: str) -> HandoffReplyDecision:
    """Classify the reply, on the lane that falls back when its provider fails.

    Degrades to the keyword rule rather than to unrelated: a failed classifier
    is not evidence that the user changed the subject.
    """
    try:
        decision = await ainvoke_structured_gemini(
            HandoffReplyDecision,
            _RESOLVE_PROMPT.format(reason=reason, message=message),
            label="browser_handoff_conversational_resolve",
        )
    except Exception as e:  # an LLM hiccup must not act on its own
        log.warning(
            f"{LogTag.BROWSER} Browser handoff resolve failed, using the keyword rule",
            error_type=type(e).__name__,
        )
        decision = keyword_reply_decision(message)
    return _without_an_acknowledgement_note(decision)
