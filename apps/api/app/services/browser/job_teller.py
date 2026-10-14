"""The one telling of a browser job's ending, written in the same transaction as the ending.

A background job's ending lands in its conversation's executor inbox: a run's
result as a BROWSER_RESULT entry, read by the one executor run that tells it;
a stop as a BROWSER_STOPPED notice that wakes nobody, because the stop already
answered. A headless job (a workflow's, a todo's) lands nothing: the tool call
that started it blocks for the ending and returns it.
"""

from time import time
from uuid import uuid4

from app.agents.core.background.executor_channel import ExecutorInbox
from app.constants.agents import AgentTag
from app.constants.browser import (
    BROWSER_JOB_RESULT_ENTRY,
    BROWSER_JOB_STOPPED_NOTICE,
    BROWSER_RESULT_REPLACED_REQUEST,
    BROWSER_RESULT_USER_SAID,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.models.agent_models import InboxEntry
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import (
    BrowserJobEnding,
    BrowserJobState,
    BrowserJobStopped,
    BrowserJobWake,
)
from app.services.browser.jobs import InboxLanding, get_job_state, record_ending
from app.services.browser.user_notes import what_the_user_said
from shared.py.wide_events import log

# Screenshots stream into the chat live, so the reply must never narrate them.
_NO_META = (
    "The step-by-step screenshots were already shown to the user in this chat, so do "
    "NOT mention screenshots, tools, steps, or 'browser vision'. Speak only to the outcome."
)

# The executor re-ran a finished task once because the tool result buried the
# run's answer; the answer now leads, and a failure says not to try again.
_FINISHED_LINE = "The browser task finished, and the text above is its own final answer."
_NO_RETRY = "Do not run the browser again for this request; tell the user what happened."

# The conversation still holds the original instruction, so without this the
# reply confirms that instead: a run that was told to skip the login and the
# upvote closed with "signed you into Reddit ... and upvoted the top post".
_ONLY_THE_SUMMARY = (
    "Report only what the summary states. Never claim an action it does not explicitly "
    "report: a login, a purchase, a vote, a message sent, a form submitted, a box ticked. "
    "That the task asked for a step is not evidence the step happened."
)


def agent_result_message(result: BrowserResultSnapshot) -> str:
    """Tell the assistant how to reply: confirm a real result, own a stop, or report a failure."""
    summary = result.summary.strip()
    # First, before anything the run itself reported: a trailing sentence lost to the
    # original request still in the model's context.
    said = what_the_user_said(
        result.user_notes,
        result.redirects,
        replaced=BROWSER_RESULT_REPLACED_REQUEST,
        said=BROWSER_RESULT_USER_SAID,
    )
    lead = f"{said}\n\n" if said else ""
    if result.status == BrowserSessionStatus.COMPLETED and result.success:
        return (
            f"{lead}{summary or 'The task finished.'}\n\n"
            f"{_FINISHED_LINE} Reply with a short, natural confirmation of what you found "
            f"or did. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    if result.status == BrowserSessionStatus.CANCELLED:
        return (
            f"{lead}"
            "BROWSER TASK WAS STOPPED before it finished. It did NOT complete, so there is no "
            "result and you must not claim one. It was stopped either because the user asked, "
            "or because the request that started it ended early; never say the user stopped it "
            "unless the conversation shows they did.\n\n"
            f"Briefly say the browser task was stopped and ask if they'd like you to try again "
            f"or do something else. {_ONLY_THE_SUMMARY} {_NO_META}"
        )
    return (
        f"{lead}"
        f"BROWSER TASK DID NOT COMPLETE. Last state: {summary or 'the task could not be finished'}.\n\n"
        f"{_NO_RETRY} Tell the user honestly and briefly that it couldn't be finished, and why "
        f"if it's clear. Do not fabricate a result, and offer no figure or answer from memory or from "
        f"an earlier run: a run that confirmed nothing gives nothing. {_ONLY_THE_SUMMARY} {_NO_META}"
    )


def ending_message(job_id: str, ending: BrowserJobEnding) -> str:
    """Return what the executor reads about how the job ended: its result, or that a stop ended it."""
    if isinstance(ending, BrowserJobStopped):
        return BROWSER_JOB_STOPPED_NOTICE.format(job_id=job_id)
    return BROWSER_JOB_RESULT_ENTRY.format(
        job_id=job_id, outcome=agent_result_message(ending.result)
    )


async def end_job(job_id: str, ending: BrowserJobEnding) -> BrowserJobEnding:
    """Record the job's ending, landed in the executor inbox when the job runs in the background; return the ending of record."""
    state = await get_job_state(job_id)
    if state is None:
        # Kept past the latest a job can end, so only a job nobody started is unknown here.
        log.warning(
            f"{LogTag.BROWSER} Browser job ending recorded for a job with no state; nothing told",
            browser={"job_id": job_id, "ending": ending.ending.value},
        )
    landing = _landing(state, ending) if state is not None and state.in_background else None
    return await record_ending(job_id, ending, landing)


def _landing(state: BrowserJobState, ending: BrowserJobEnding) -> InboxLanding:
    """Return the inbox entry that tells ending; a result also wakes a run until it is read."""
    inbox = ExecutorInbox(state.conversation_id)
    text = ending_message(state.job_id, ending)
    if isinstance(ending, BrowserJobStopped):
        return InboxLanding(
            inbox, InboxEntry(id=str(uuid4()), text=text, tag=AgentTag.BROWSER_STOPPED)
        )
    entry = InboxEntry(id=str(uuid4()), text=text, tag=AgentTag.BROWSER_RESULT)
    wake = BrowserJobWake(
        job_id=state.job_id,
        conversation_id=state.conversation_id,
        user_id=state.user_id,
        entry_id=entry.id,
        landed_at=time(),
    )
    return InboxLanding(inbox, entry, wake)
