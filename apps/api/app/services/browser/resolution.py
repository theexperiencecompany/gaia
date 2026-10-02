"""Read the user's chat message against their browser task: a reply to a paused step, or a stop.

When a browser task is paused at a sensitive step and the user replies in chat
("ok I'm logged in" / "no, stop") instead of clicking the card's buttons, one
scoped LLM call classifies the reply. This is the text-channel equivalent of
the Continue/Cancel buttons, so it works identically on web and bots. While a
task runs unpaused, one scoped call reads whether the message stops it.

A stop said in chat takes the one stop path (stop_browser_job), so the job is
flagged stopped before anything else reads the message: the turn answering it
is then the only one that speaks of the stop. Read as a note instead, it once
ended the run on its own agent's say-so as a failure, which the run's executor
narrated on top of the turn's own "Stopped." Mirrors the HIL conversational
pattern: a classifier that fails acts on nothing.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured_gemini
from app.constants.browser import HandoffDecision, HandoffStatus
from app.constants.log_tags import LogTag
from app.schemas.browser_job import BrowserJobStatus
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.handoff import (
    get_handoff,
    get_pending_handoff_for_reply,
    resolve_handoff,
)
from app.services.browser.job_stop import stop_browser_job
from app.services.browser.jobs import get_conversation_slot, get_job_state
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


_RUNNING_PROMPT = (
    "A browser automation task is running for the user: {task!r}\n\n"
    "The user just sent this message while it runs:\n{message!r}\n\n"
    "Classify it as exactly one of:\n"
    "- 'stop': they want the browser task stopped, such as 'stop', 'cancel that', "
    "'never mind, stop it'.\n"
    "- 'other': anything else, including a change to what the task should do, a "
    "question, or something unrelated. It reaches the running task as something "
    "the user said."
)


class RunningTaskMessageDecision(BaseModel):
    """Scoped reading of a message sent while a browser task runs unpaused."""

    action: Literal["stop", "other"]


@dataclass(frozen=True)
class HandoffReply:
    """How a chat reply was read against the handoff it answered."""

    action: HandoffReplyAction
    #: What the paused task had asked the user to do.
    reason: str


async def resolve_handoff_from_message(
    address: str, user_id: str, message: str
) -> HandoffReply | None:
    """Resolve the browser handoff pending at this reply address (handoff.reply_address) from message.

    Returns how the reply was read, or None when nothing is pending there (so
    the normal turn runs with nothing to add). A reply read as a stop stops the
    task itself, not only the step it paused on.
    """
    handoff_id = await get_pending_handoff_for_reply(address)
    if not handoff_id:
        return None
    record = await get_handoff(handoff_id)
    if record is None or record.status != HandoffStatus.PENDING:
        return None
    if record.user_id != user_id:
        log.warning(
            f"{LogTag.BROWSER} Handoff reply ignored: the handoff belongs to another user",
            browser={"handoff_id": handoff_id},
            user_id=user_id,
        )
        return None

    # A classifier failure raises to the chat turn, which logs it and leaves the handoff pending.
    decision = await ainvoke_structured_gemini(
        HandoffReplyDecision,
        _RESOLVE_PROMPT.format(reason=record.reason, message=message),
        label="browser_handoff_conversational_resolve",
    )
    if decision.action == "unrelated":
        return HandoffReply(action="unrelated", reason=record.reason)
    if decision.action == "cancel":
        # Settles the handoff it is paused on as cancelled, after flagging the job.
        await stop_browser_job(address)
        capture_event(
            user_id,
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": HandoffDecision.CANCEL.value, "with_note": False},
        )
        return HandoffReply(action="cancel", reason=record.reason)

    note = (decision.note or "").strip() or None
    await resolve_handoff(
        handoff_id,
        HandoffDecision.CONTINUE,
        user_id,
        message=note,
        redirect=decision.action == "redirect",
    )
    return HandoffReply(action=decision.action, reason=record.reason)


async def stop_running_job_from_message(conversation_id: str, message: str) -> bool:
    """Stop the conversation's running browser task when the user's message asks for that; whether it did.

    Read only while a task runs: anything else the user says reaches the task as
    something they said. A classifier failure raises to the chat turn.
    """
    job_id = await get_conversation_slot(conversation_id)
    state = await get_job_state(job_id) if job_id is not None else None
    if state is None or state.status is BrowserJobStatus.DONE:
        return False
    decision = await ainvoke_structured_gemini(
        RunningTaskMessageDecision,
        _RUNNING_PROMPT.format(task=state.task, message=message),
        label="browser_running_task_message",
    )
    if decision.action != "stop":
        return False
    await stop_browser_job(conversation_id)
    return True
