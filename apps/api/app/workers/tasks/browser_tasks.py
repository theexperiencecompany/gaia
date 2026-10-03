"""The ARQ tasks of a browser job: the one that runs it, and the reaper of jobs whose worker died.

The run itself is the job runner's, and the telling of its ending job_teller's;
this owns what only a worker can own: the slot the run holds while it really
runs, the executor run woken to tell a landed result, and the sweep that ends a
job nobody is left to end.
"""

import asyncio
from collections.abc import Mapping

from arq.jobs import Job, JobStatus

from app.agents.core.background.executor_runner import wake_executor_for_inbox
from app.constants.browser import (
    BROWSER_JOB_HEARTBEAT_SECONDS,
    BROWSER_JOB_QUEUE,
    BROWSER_JOB_SLOT_TAKEN_SUMMARY,
    BROWSER_JOB_WORKER_LOST_SUMMARY,
    BrowserRunFailure,
    BrowserSessionStatus,
)
from app.constants.log_tags import LogTag
from app.schemas.browser import BrowserResultSnapshot
from app.schemas.browser_job import BrowserJobFinished, BrowserJobRequest, BrowserJobState
from app.services.browser.job_events import card_frame
from app.services.browser.job_runner import (
    close_job_feed,
    execute_browser_job,
    publish_frame_to_job,
    refuse_browser_job,
)
from app.services.browser.job_teller import end_job
from app.services.browser.jobs import (
    claim_conversation_slot,
    done_state,
    forget_live_job,
    get_conversation_slot,
    get_job_state,
    heartbeat_conversation_slot,
    live_job_ids,
    release_conversation_slot,
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

    Owns the slot heartbeat. The ending was told as it was recorded (job_teller):
    a finished background run's result is in the executor inbox, a stop's notice
    wakes nobody, and a headless run's caller reads the ending itself.
    """
    request = BrowserJobRequest.model_validate(payload)
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
    if request.in_background and isinstance(await done_state(request.job_id), BrowserJobFinished):
        await _wake_executor(request.conversation_id, request.user_id)
    return result.status.value


async def _heartbeat(request: BrowserJobRequest) -> None:
    """Hold the conversation's browser slot for as long as this run is really running.

    One Redis error costs one beat, not the lease: a heartbeat that died on it
    would let the slot lapse under a live run.
    """
    while True:
        await asyncio.sleep(BROWSER_JOB_HEARTBEAT_SECONDS)
        try:
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


async def _wake_executor(conversation_id: str, user_id: str) -> None:
    """Start an executor run to tell the result landed in its inbox, unless one is live to drain it."""
    user = await load_user_context(user_id)
    if user is None:
        log.warning(
            f"{LogTag.BROWSER} Browser job result landed but nobody was woken: user not found",
            browser={"conversation_id": conversation_id},
        )
        return
    await wake_executor_for_inbox(conversation_id, user)


async def reap_browser_jobs(_ctx: Mapping[str, object]) -> str:
    """End every job whose worker died before it ended, told like any other ending; return how many.

    ARQ never retries a browser job, so one whose worker died has no one left
    to end it: its card would spin, its relay wait, and a headless caller block.
    """
    pool = await RedisPoolManager.get_pool()
    reaped: list[str] = []
    for job_id in await live_job_ids():
        state = await get_job_state(job_id)
        if state is None or await done_state(job_id) is not None:
            await forget_live_job(job_id)
            continue
        status = await Job(job_id, pool, _queue_name=BROWSER_JOB_QUEUE).status()
        if status in _WAITING_FOR_A_WORKER:
            continue
        # A worker heartbeats the slot for as long as it runs the job.
        if await get_conversation_slot(state.conversation_id) == job_id:
            continue
        if await _end_lost_job(state):
            reaped.append(job_id)
    log.set_ns("browser", reaped_jobs=reaped)
    return f"reaped={len(reaped)}"


async def _end_lost_job(state: BrowserJobState) -> bool:
    """End a job whose worker died on a worker-lost result card; False when another ending won first."""
    result = BrowserResultSnapshot(
        status=BrowserSessionStatus.FAILED, success=False, summary=BROWSER_JOB_WORKER_LOST_SUMMARY
    )
    lost = BrowserJobFinished(result=result)
    if await end_job(state.job_id, lost) is not lost:
        return False
    log.warning(
        f"{LogTag.BROWSER} Browser job ended by the reaper: its worker died",
        reason=BrowserRunFailure.WORKER_LOST.value,
        browser={"job_id": state.job_id, "status": state.status.value},
    )
    await publish_frame_to_job(state.job_id, card_frame(result))
    await close_job_feed(state.job_id)
    await release_conversation_slot(state.conversation_id, state.job_id)
    if state.in_background:
        await _wake_executor(state.conversation_id, state.user_id)
    return True
