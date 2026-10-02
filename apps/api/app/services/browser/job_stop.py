"""Stop a conversation's browser job: the one path every stop takes.

The chat's Stop button, cancel_executor, a failed executor run and the bot's
/stop all land here. A stop flags the job, settles the handoff it is paused on
as cancelled, and aborts its ARQ task, whose cancellation path ends the run on
a stopped card. A job still queued is not aborted: ARQ would drop it unrun,
leaving no ending at all, so it reads the flag at its start and ends there.
"""

from arq.constants import abort_jobs_ss
from arq.jobs import Job, JobStatus
from arq.utils import timestamp_ms

from app.constants.browser import (
    BrowserSessionStatus,
    BrowserStopOutcome,
)
from app.schemas.browser_job import BrowserJobStatus
from app.services.browser.handoff import cancel_handoff
from app.services.browser.job_events import wait_for_job_end
from app.services.browser.jobs import (
    get_job_state,
    get_job_wait,
    get_latest_job,
    request_job_cancel,
)
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log


async def stop_browser_job(key: str) -> str | None:
    """Stop the queued or running browser job started at key (a conversation, or a bot run's requester chat); return its id, or None when none is in flight."""
    job_id = await get_latest_job(key)
    if job_id is None:
        return None
    state = await get_job_state(job_id)
    if state is None or state.status is BrowserJobStatus.DONE:
        return None
    await request_job_cancel(job_id)
    paused_on = await get_job_wait(job_id)
    if paused_on is not None:
        await cancel_handoff(paused_on)
    aborted = await _abort_if_started(job_id)
    log.set_ns("browser", stopped_job=job_id, stop_settled=paused_on, stop_aborted=aborted)
    return job_id


async def _abort_if_started(job_id: str) -> bool:
    """Cancel the job's ARQ task when a worker is running it; whether the abort was asked for."""
    pool = await RedisPoolManager.get_pool()
    # The in-progress key a worker holds while running a job, whichever queue it came from.
    if await Job(job_id, pool).status() is not JobStatus.in_progress:
        return False
    # What Job.abort does, without its wait on a result: this queue keeps none.
    await pool.zadd(abort_jobs_ss, {job_id: timestamp_ms()})
    return True


async def confirm_stopped(job_id: str, within_seconds: float) -> BrowserStopOutcome:
    """Wait for the stopped job's own ending; say whether it ended stopped, ended otherwise, or not yet."""
    if not await wait_for_job_end(job_id, within_seconds):
        return BrowserStopOutcome.UNCONFIRMED
    state = await get_job_state(job_id)
    result = state.result if state is not None else None
    if result is not None and result.status is not BrowserSessionStatus.CANCELLED:
        return BrowserStopOutcome.ALREADY_ENDED
    return BrowserStopOutcome.STOPPED
