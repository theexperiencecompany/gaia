"""Resolve a pending browser handoff from the user's next chat message.

When a browser task is paused at a sensitive step and the user replies in chat
("yeah I paid, continue" / "no, stop") instead of clicking the card's buttons,
one scoped LLM call classifies the reply. This is the text-channel equivalent of
the Continue/Cancel buttons — same core (``resolve_handoff``), so it works
identically on web and bots. Mirrors the HIL conversational-resolution pattern.
"""

from typing import Literal

from pydantic import BaseModel

from app.agents.llm.client import ainvoke_structured
from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.services.browser.handoff import (
    get_conversation_pending_handoff,
    get_handoff,
    resolve_handoff,
)
from shared.py.wide_events import log

HandoffReplyAction = Literal["continue", "cancel", "unrelated"]


class HandoffReplyDecision(BaseModel):
    """Scoped classification of a reply to a pending browser handoff."""

    action: HandoffReplyAction


async def resolve_handoff_from_message(
    conversation_id: str, user_id: str, message: str
) -> HandoffReplyAction | None:
    """Resolve the conversation's pending browser handoff from ``message``.

    Returns the classified action, or ``None`` when nothing is pending or the
    reply addressed none of it (so the normal turn runs).
    """
    handoff_id = await get_conversation_pending_handoff(conversation_id)
    if not handoff_id:
        return None
    record = await get_handoff(handoff_id)
    if record is None or record.get("status") != HandoffStatus.PENDING.value:
        return None

    decision = await _interpret(message, record.get("reason", ""))
    if decision.action == "unrelated":
        return "unrelated"

    kind = HandoffDecision.CONTINUE if decision.action == "continue" else HandoffDecision.CANCEL
    try:
        await resolve_handoff(handoff_id, kind, user_id)
    except PermissionError:
        return None
    return decision.action


async def _interpret(message: str, reason: str) -> HandoffReplyDecision:
    """Classify the reply. Fails toward ``unrelated`` (normal chat), never toward
    silently continuing a sensitive browser task."""
    try:
        return await ainvoke_structured(
            HandoffReplyDecision,
            _prompt(message, reason),
            label="browser_handoff_conversational_resolve",
        )
    except Exception as e:  # noqa: BLE001 — an LLM hiccup must not act on its own
        log.warning(f"{LogTag.AGENT} Browser handoff resolve failed, treating as unrelated: {e}")
        return HandoffReplyDecision(action="unrelated")


def _prompt(message: str, reason: str) -> str:
    return (
        "A browser automation task is paused, waiting for the user to finish a "
        f"sensitive step themselves in the live browser: {reason!r}\n\n"
        f"The user just sent this message:\n{message!r}\n\n"
        "Is the user telling the assistant to CONTINUE (they finished the step / "
        "gave the go-ahead), to CANCEL (stop the task), or is this an UNRELATED "
        "new request? Reply with action='continue', 'cancel', or 'unrelated'."
    )
