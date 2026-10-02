"""Stop a browser job: what a chat controls, and the one decision a stop makes.

A job ends once, recorded by jobs.record_ending: a stop records STOPPED, the
run's own result card records FINISHED, and whoever records first wins. A
stop that won settles the handoff the run is paused on as cancelled and
aborts its ARQ task, whose cancellation path ends the run on a stopped card;
a stop that lost reports the job already ended, and its result is told. A job
still queued is not aborted (ARQ would drop it unrun, leaving no ending): it
reads its ending at its start and ends there.

Which jobs a user's stop reaches is chat_job_keys: the conversation's job, and
the job that answers to the requester's own chat, where a bot run started in
a group sends its updates and handoffs.
"""

from dataclasses import dataclass

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms

from app.constants.browser import BrowserStopOutcome, JobEnding
from app.constants.chat import ConversationSource, SourceCategory
from app.schemas.browser_job import BrowserJobState, BrowserJobStatus
from app.services.browser.handoff import bot_chat_address, cancel_handoff
from app.services.browser.jobs import (
    get_job_state,
    get_job_wait,
    get_latest_job,
    record_ending,
)
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log


@dataclass(frozen=True)
class RequesterChat:
    """A user's own chat on a bot platform: where their bot runs, from any chat, send updates and handoffs."""

    user_id: str
    source: ConversationSource


def requester_chat(user_id: str | None, source: ConversationSource | None) -> RequesterChat | None:
    """Return the user's own bot chat for a message from a bot platform; None for any other surface, or with no user."""
    if (
        not user_id
        or source is None
        or SourceCategory.from_source(source) is not SourceCategory.BOT
    ):
        return None
    return RequesterChat(user_id, source)


def chat_job_keys(conversation_id: str, requester: RequesterChat | None) -> list[str]:
    """Return where the jobs a chat controls are found: its conversation, and the requester's own chat."""
    keys = [conversation_id]
    if requester is not None:
        keys.append(bot_chat_address(requester.source, requester.user_id))
    return list(dict.fromkeys(keys))


async def running_chat_jobs(
    conversation_id: str, requester: RequesterChat | None
) -> list[BrowserJobState]:
    """Return the jobs this chat controls that have not ended, newest at each key."""
    running: list[BrowserJobState] = []
    for key in chat_job_keys(conversation_id, requester):
        job_id = await get_latest_job(key)
        state = await get_job_state(job_id) if job_id is not None else None
        if (
            state is not None
            and state.status is not BrowserJobStatus.DONE
            and state.job_id not in {job.job_id for job in running}
        ):
            running.append(state)
    return running


async def stop_chat_jobs(
    conversation_id: str, requester: RequesterChat | None
) -> dict[str, BrowserStopOutcome]:
    """Stop every job this chat controls; return what each stop came to, by job id."""
    jobs = await running_chat_jobs(conversation_id, requester)
    return {job.job_id: await stop_job(job.job_id) for job in jobs}


async def stop_browser_job(key: str) -> str | None:
    """Stop the latest job started at key; return its id when the stop won, else None."""
    job_id = await get_latest_job(key)
    if job_id is None or await get_job_state(job_id) is None:
        return None
    return job_id if await stop_job(job_id) is BrowserStopOutcome.STOPPED else None


async def stop_job(job_id: str) -> BrowserStopOutcome:
    """Record this job's ending as stopped unless it ended already; when the stop won, settle its handoff and abort its task."""
    if await record_ending(job_id, JobEnding.STOPPED) is not JobEnding.STOPPED:
        log.set_ns("browser", stopped_job=job_id, stop_lost="finished")
        return BrowserStopOutcome.ALREADY_ENDED
    paused_on = await get_job_wait(job_id)
    if paused_on is not None:
        await cancel_handoff(paused_on)
    aborted = await _abort_if_started(job_id)
    log.set_ns("browser", stopped_job=job_id, stop_settled=paused_on, stop_aborted=aborted)
    return BrowserStopOutcome.STOPPED


async def _abort_if_started(job_id: str) -> bool:
    """Cancel the job's ARQ task when a worker is running it; whether the abort was asked for."""
    pool = await RedisPoolManager.get_pool()
    # The in-progress key a worker holds while running a job, whichever queue it came from.
    if await Job(job_id, pool).status() is not JobStatus.in_progress:
        return False
    # What Job.abort does, without its wait on a result: this queue keeps none.
    await pool.zadd(abort_jobs_ss, {job_id: timestamp_ms()})
    return True
