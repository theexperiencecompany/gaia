"""Resolve a pending browser handoff from the user's next chat message.

When a browser task is paused at a sensitive step and the user replies in chat
("ok I'm logged in" / "no, stop") instead of clicking the card's buttons, one
scoped LLM call classifies the reply. This is the text-channel equivalent of
the Continue/Cancel buttons, same core (resolve_handoff), so it works
identically on web and bots. Mirrors the HIL conversational-resolution pattern:
a classifier that fails leaves the handoff pending, never acts on a guess.
"""

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

_RESOLVE_PROMPT = (
    "A browser automation task is paused, waiting for the user to finish a "
    "sensitive step themselves in the live browser: {reason!r}\n\n"
    "The user just sent this message:\n{message!r}\n\n"
    "Classify the reply as exactly one of:\n"
    "- 'continue': they say they finished the step or give the go-ahead, such as "
    "'done', 'logged in', 'ok go ahead', 'finished, continue'.\n"
    "- 'cancel': they want the whole task stopped.\n"
    "- 'redirect': they will NOT do the paused step, but they tell you what "
    "to do instead, so the task carries on with that new instruction. "
    "Examples: 'never mind the login, just tell me what the github.com "
    "homepage headline says', 'skip the upvote, just tell me the title of "
    "the top post on r/python', 'forget the payment, read me the total'. "
    "For a redirect, 'note' must hold the ENTIRE new instruction.\n"
    "- 'unrelated': anything else, including a reply that has nothing to do "
    "with the paused task ('what's the weather') and one that says they are "
    "not done yet ('one sec', 'which password?'). The task stays paused.\n\n"
    "Put anything the user asks for beyond the go-ahead itself in 'note', "
    "verbatim. Leave 'note' null when the reply only says they are done."
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

    # A classifier failure raises to the chat turn, which logs it and leaves the handoff pending.
    decision = await ainvoke_structured_gemini(
        HandoffReplyDecision,
        _RESOLVE_PROMPT.format(reason=record.reason, message=message),
        label="browser_handoff_conversational_resolve",
    )
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
