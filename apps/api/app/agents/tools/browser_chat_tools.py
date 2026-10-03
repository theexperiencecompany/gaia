"""Comms' tools for what the user says to their browser task: finish the paused step, stop it, or tell it something.

Each acts on the task this chat controls, found from the turn (chat_task.py),
and only on a turn answering the user's own message. The result is a short
fact for the model to reply from.
"""

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.constants.browser import HandoffDecision, HandoffStatus
from app.models.agent_models import agent_configurable
from app.services.analytics_service import AnalyticsEvents, capture_event
from app.services.browser.chat_task import (
    chat_browser_tasks,
    paused_step,
    stop_report,
    user_message_turn,
)
from app.services.browser.handoff import resolve_handoff
from app.services.browser.job_stop import stop_chat_jobs, stop_job
from app.services.browser.jobs import post_job_message
from shared.py.wide_events import log

_NOT_A_USER_TURN = (
    "Nothing changed: only a reply to the user's own message can act on their browser task."
)
_NOTHING_PAUSED = "No browser task is waiting on the user, so nothing changed."
_REDIRECT_NEEDS_NOTE = (
    "Nothing changed: a redirect needs the user's new instruction in note, in full."
)
_SETTLED_ALREADY = "The paused step had already ended ({status}) before this, so nothing changed."
_CONTINUES = "The browser task carries on. Its result reaches the user in its own message."
_CONTINUES_WITH_NOTE = (
    "The browser task carries on with the user's note. Its result reaches the user in its "
    "own message."
)
_REDIRECTED = (
    "The browser task skipped the paused step and now follows the new instruction. Its result "
    "reaches the user in its own message."
)
_NOTHING_RUNNING = "No browser task is running in this chat, so nothing changed."
_EMPTY_MESSAGE = "Nothing was passed on: the text to tell the browser task was empty."
_TOLD_RUNNING = "Passed on. The browser task reads it at its next step."
_TOLD_PAUSED = (
    "Passed on. The browser task reads it once it resumes; it is still paused until the user "
    "finishes: {reason}"
)


class _StepDoneArgs(BaseModel):
    """What the model passes browser_step_done; the defaults live here, where the schema reads them."""

    note: str | None = Field(
        default=None,
        description="Anything the user asked for beyond saying they finished, in their words "
        "('ok done, also grab the photo' -> 'also grab the photo'). Leave it out for a bare "
        "'done'. With redirect, the whole new instruction.",
    )
    redirect: bool = Field(
        default=False,
        description="True when the user will NOT do the paused step and says what to do instead "
        "('never mind the login, just tell me X'). note then holds the new instruction.",
    )


@tool(args_schema=_StepDoneArgs)
async def browser_step_done(config: RunnableConfig, note: str | None, redirect: bool) -> str:
    """Tell the paused browser task the user finished its step in the live view, so it carries on.

    Use it only while a <browser_task> note says the task is paused, and only when
    the user says they finished the step ("done", "logged in", "ok go ahead") or
    replaces it with something else to do (redirect=true). A question about the
    step, or "not yet", is not finishing it: the task keeps waiting.
    """
    turn = user_message_turn(agent_configurable(config))
    if turn is None:
        return _NOT_A_USER_TURN
    note = (note or "").strip() or None
    if redirect and note is None:
        return _REDIRECT_NEEDS_NOTE
    paused = await paused_step(turn)
    if paused is None:
        return _NOTHING_PAUSED
    status = await resolve_handoff(
        paused.handoff_id, HandoffDecision.CONTINUE, turn.user_id, message=note, redirect=redirect
    )
    log.set_ns("browser", job_id=paused.job_id, step_done_from_chat=True, redirect=redirect)
    if status is None:
        return _NOTHING_PAUSED
    if status is not HandoffStatus.COMPLETED:
        return _SETTLED_ALREADY.format(status=status.value)
    if redirect:
        return _REDIRECTED
    return _CONTINUES_WITH_NOTE if note else _CONTINUES


@tool
async def stop_browser_task(config: RunnableConfig) -> str:
    """Stop the browser task running or paused in this chat.

    Use it when the user says to stop or cancel it ("stop", "cancel that", "forget it")
    while a <browser_task> note shows one. It stops only the browser task;
    cancel_executor([]) is for stopping everything.
    """
    turn = user_message_turn(agent_configurable(config))
    if turn is None:
        return _NOT_A_USER_TURN
    paused = await paused_step(turn)
    if paused is not None:
        # The paused task is the one the user is answering; another run may share their bot chat.
        outcome = await stop_job(paused.job_id)
        capture_event(
            turn.user_id,
            AnalyticsEvents.BROWSER_HANDOFF_RESOLVED,
            {"decision": HandoffDecision.CANCEL.value, "with_note": False},
        )
        log.set_ns("browser", job_id=paused.job_id, stopped_from_chat=True)
        return stop_report([outcome])
    outcomes = await stop_chat_jobs(turn.conversation_id, turn.requester)
    if not outcomes:
        return _NOTHING_RUNNING
    log.set_ns("browser", stopped_from_chat=sorted(outcomes))
    return stop_report(outcomes.values())


@tool
async def tell_browser_task(
    config: RunnableConfig,
    text: Annotated[
        str,
        "What the user wants the browser task to do differently, with every detail they gave "
        "('use the blue one', 'also grab the photo').",
    ],
) -> str:
    """Pass the user's instruction to the browser task while it runs, for it to follow from its next step.

    Use it when the user changes or adds to what the running task should do. Never
    for a stop (stop_browser_task), and never to finish a paused step
    (browser_step_done).
    """
    turn = user_message_turn(agent_configurable(config))
    if turn is None:
        return _NOT_A_USER_TURN
    text = text.strip()
    if not text:
        return _EMPTY_MESSAGE
    tasks = await chat_browser_tasks(turn)
    if not tasks.running:
        return _NOTHING_RUNNING
    for job in tasks.running:
        await post_job_message(job.job_id, text)
    log.set_ns("browser", told_from_chat=[job.job_id for job in tasks.running])
    if tasks.paused is not None:
        return _TOLD_PAUSED.format(reason=tasks.paused.reason)
    return _TOLD_RUNNING
