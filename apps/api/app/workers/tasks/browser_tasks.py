"""The ARQ tasks of a browser job: the one that runs it, and the reaper that makes good a worker that died.

The run itself is the job runner's, and the telling of its ending job_teller's;
this owns what only a worker can own: the slot and the lease the run holds while
it really runs, the executor run woken to tell a landed result, and the sweep
that ends a job nobody is left to end and wakes a result nobody was woken for.
"""

import asyncio
from collections.abc import Mapping
from time import time

from arq.connections import ArqRedis
from arq.jobs import Job, JobStatus

from app.agents.core.background.executor_channel import ExecutorInbox
from app.agents.core.background.executor_runner import wake_executor_for_inbox
from app.constants.browser import (
    BROWSER_JOB_DEATH_CONFIRM_SECONDS,
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_JOB_WAKE_GRACE_SECONDS,
    BROWSER_JOB_WORKER_LOST_SUMMARY,
    BrowserRunFailure,
)
from app.constants.log_tags import LogTag
from app.schemas.browser_job import BrowserJobRequest, BrowserJobWake
from app.services.browser.job_runner import end_lost_job, execute_browser_job, refuse_browser_job
from app.services.browser.jobs import (
    claim_conversation_slot,
    clear_suspect,
    done_state,
    forget_live_job,
    forget_wake,
    get_job_state,
    heartbeat_conversation_slot,
    hold_job_alive,
    job_alive,
    keep_wakes,
    landed_wake,
    landed_wakes,
    live_job_ids,
    release_conversation_slot,
    release_job_alive,
    suspect_since,
)
from app.utils.auth_utils import load_user_context
from app.utils.background_tasks import spawn_background_task
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log

#: A job ARQ still holds for a worker to take: nothing has died yet.
_WAITING_FOR_A_WORKER = frozenset({JobStatus.queued, JobStatus.deferred})


async def run_browser_job(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    payload: dict[str, object],
) -> str:
    """Run one browser task to completion off the request path, then wake the executor its result landed for.

    Holds the job's lease and the conversation's slot while it runs. The ending
    was told as it was recorded (job_teller): a finished background run's result
    is in the executor inbox, a stop's notice wakes nobody, and a headless run's
    caller reads the ending itself.
    """
    request = BrowserJobRequest.model_validate(payload)
    # First: from here on the reaper reads this job as alive.
    await hold_job_alive(request.job_id)
    log.set(
        user={"id": request.user_id},
        platform=request.conversation_source.value if request.conversation_source else None,
        browser={
            "job_id": request.job_id,
            "conversation_id": request.conversation_id,
            "source_category": request.source_category,
        },
    )
    # Nobody heartbeats the enqueuer's slot lease until here, so a long queue wait
    # can have outlived it, and another run may have taken the conversation since.
    holder = await claim_conversation_slot(request.conversation_id, request.job_id)
    if holder is not None and holder != request.job_id:
        log.warning(
            f"{LogTag.BROWSER} Browser job refused: its conversation slot was taken",
            browser={"job_id": request.job_id, "slot_holder": holder},
        )
        result = await refuse_browser_job(request, BROWSER_JOB_SLOT_TAKEN_SUMMARY)
    else:
        heartbeat = spawn_background_task(_heartbeat(request), name="browser_job_heartbeat")
        try:
            result = await execute_browser_job(request)
        finally:
            heartbeat.cancel()
            await release_conversation_slot(request.conversation_id, request.job_id)
    await release_job_alive(request.job_id)
    wake = await landed_wake(request.job_id)
    if wake is not None:
        await _wake(wake)
    return result.status.value


async def _heartbeat(request: BrowserJobRequest) -> None:
    """Hold the job's lease and the conversation's browser slot for as long as this run is really running.

    One Redis error costs one beat, not the lease: a heartbeat that died on it
    would let the slot lapse under a live run.
    """
    while True:
        await asyncio.sleep(BROWSER_JOB_HEARTBEAT_SECONDS)
        try:
            await hold_job_alive(request.job_id)
            held = await heartbeat_conversation_slot(request.conversation_id, request.job_id)
        except Exception as exc:
            log.error(
                f"{LogTag.BROWSER} Browser job slot heartbeat failed",
                error_type=type(exc).__name__,
                error=str(exc),
                browser={"job_id": request.job_id},
            )
            continue
        if not held:
            log.warning(
                f"{LogTag.BROWSER} Browser job lost its conversation slot while running",
                browser={"job_id": request.job_id},
            )


async def _wake(wake: BrowserJobWake) -> None:
    """Start an executor run to tell a landed result, unless it was read already or a live run will read it.

    The wake is kept until its entry leaves the inbox, so a run that never came
    is asked for again; a live run, or one that just started, makes this a no-op.
    """
    pending = {entry.id for entry in await ExecutorInbox(wake.conversation_id).read()}
    if wake.entry_id not in pending:
        await forget_wake(wake.job_id)
        return
    user = await load_user_context(wake.user_id)
    if user is None:
        log.warning(
            f"{LogTag.BROWSER} Browser job result landed but nobody can be woken: user not found",
            browser={"job_id": wake.job_id, "conversation_id": wake.conversation_id},
        )
        await forget_wake(wake.job_id)
        return
    await wake_executor_for_inbox(wake.conversation_id, user)


async def reap_browser_jobs(_ctx: Mapping[str, object]) -> str:
    """End every job whose worker died before it ended, and wake every result nobody was woken for.

    ARQ never retries a browser job, so one whose worker died has no one left
    to end it: its card would spin, its relay wait, and a headless caller block.
    """
    pool = await RedisPoolManager.get_pool()
    reaped = [job_id for job_id in await live_job_ids() if await _reap(pool, job_id)]
    now = time()
    wakes = [w for w in await landed_wakes() if now - w.landed_at >= BROWSER_JOB_WAKE_GRACE_SECONDS]
    for wake in wakes:
        await _wake(wake)
    await keep_wakes()
    log.set_ns("browser", reaped_jobs=reaped, results_to_tell=[wake.job_id for wake in wakes])
    return f"reaped={len(reaped)} results_to_tell={len(wakes)}"


async def _reap(pool: ArqRedis, job_id: str) -> bool:
    """End job_id when its worker is gone for good; whether this sweep ended it.

    Gone takes positive evidence: not held by ARQ for a worker to take, no
    worker lease on it, and both for a full confirm window, never one sweep.
    """
    state = await get_job_state(job_id)
    if state is None or await done_state(job_id) is not None:
        await forget_live_job(job_id)
        return False
    waiting = (
        await Job(job_id, pool, _queue_name=BROWSER_JOB_QUEUE).status() in _WAITING_FOR_A_WORKER
    )
    if waiting or await job_alive(job_id):
        await clear_suspect(job_id)
        return False
    now = time()
    if now - await suspect_since(job_id, now) < BROWSER_JOB_DEATH_CONFIRM_SECONDS:
        return False
    log.warning(
        f"{LogTag.BROWSER} Browser job ended by the reaper: its worker died",
        reason=BrowserRunFailure.WORKER_LOST.value,
        browser={"job_id": job_id, "status": state.status.value},
    )
    await end_lost_job(state, BROWSER_JOB_WORKER_LOST_SUMMARY)
    wake = await landed_wake(job_id)
    if wake is not None:
        await _wake(wake)
    return True
