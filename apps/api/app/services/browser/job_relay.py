"""Replay a background job's card feed into the turn that started it, and hold its result for that turn.

The worker publishes cards to the job's own Redis stream; this forwards them
into the turn's stream and its collected tool events, one at a time and in
order, which is what puts them on the live SSE stream and on the turn's
message. Publishing to the stream from the worker would reach the first but
not the second, and the cards would vanish on reload.

While the executor run that started the job is alive it may still join and
speak the result, so the relay holds the result for it until that run ends;
a turn that collected the result holds it the same way, and keeps the telling
only if its run finished. The worker tells the user itself once nothing holds it.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial

from pydantic import TypeAdapter

from app.agents.core.background.redis_writer import publish_to_stream
from app.agents.core.background.session import StreamSession, get_session
from app.constants.browser import BROWSER_JOB_JOINER_REFRESH_SECONDS
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamProgress, stream_manager
from app.services.browser.job_events import JOB_TERMINAL_FRAME, is_card_frame, read_job_events
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from app.services.browser.jobs import (
    drop_joiner_lease,
    hold_result_for_run,
    job_cancel_requested,
    keep_result_claim,
    refresh_joiner_lease,
    release_result_hold,
    settle_result_claim,
)
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

_STREAM_PROGRESS: TypeAdapter[StreamProgress] = TypeAdapter(StreamProgress)


async def relay_job_events(job_id: str, stream_id: str) -> None:
    """Replay a job's card feed into a turn's live stream until the job ends or nobody reads the stream.

    Runs in the API process as a logged background task, from 0-0 so a late or
    restarted relay still shows every card. A stopped job is followed to its
    stopped card even though its turn ended with the stop. Never raises.
    """
    log.set(browser={"job_id": job_id})
    run = live_run(stream_id)
    keeper = (
        spawn_background_task(_hold_until_the_run_ends(job_id, stream_id, run))
        if run is not None
        else None
    )
    try:
        # Until the feed itself expires: past the latest the worker lets the job end.
        async with asyncio.timeout(browser_job_ttl_seconds()):
            await _relay_cards(job_id, stream_id)
            # Ended with the job, the run that started it may still join: wait for it.
            # Ended because nobody listens, that run is over and its keeper with it.
            if keeper is not None:
                await keeper
    except TimeoutError:
        log.warning(
            f"{LogTag.BROWSER} Browser job relay gave up before the job finished",
            browser={"job_id": job_id},
        )
    except Exception as exc:
        # The relay is fire-and-forget beside the turn: a crash here costs the
        # remaining cards, and must never cost the turn itself.
        log.error(
            f"{LogTag.BROWSER} Browser job relay stopped",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": job_id},
        )
    finally:
        if keeper is not None:
            keeper.cancel()
        await release_result_hold(job_id, stream_id)


async def _relay_cards(job_id: str, stream_id: str) -> None:
    """Forward cards until the job's terminal frame, or until nobody reads them any more."""
    cursor = "0-0"
    while True:
        for entry_id, payload in await read_job_events(job_id, cursor):
            if payload == JOB_TERMINAL_FRAME:
                log.set_ns("browser", relay_end="job_finished")
                return
            if is_card_frame(payload):
                await publish_to_stream(stream_id, payload)
            cursor = entry_id
        if await _nobody_listening(stream_id) and not await job_cancel_requested(job_id):
            # The message that speaks the result carries the run's cards from the feed.
            log.set_ns("browser", relay_end="turn_ended")
            return


async def _hold_until_the_run_ends(job_id: str, stream_id: str, run: StreamSession) -> None:
    """Keep the result for the executor run that started the job until that run ends: it may still join and speak it."""
    await _until_the_run_ends(run, partial(hold_result_for_run, job_id, stream_id))


async def hold_collected_result(job_id: str, stream_id: str, run: StreamSession) -> None:
    """Keep the result the turn on stream_id collected until its run ends: told by it if the run finished, by the worker if not."""
    told = False
    try:
        await _until_the_run_ends(run, partial(_keep_collected_result, job_id, stream_id))
        told = not run.executor_failed
    finally:
        await settle_result_claim(job_id, told=told)
        await drop_joiner_lease(job_id, stream_id)


async def _keep_collected_result(job_id: str, stream_id: str) -> None:
    # The claim first, so it never outlives the lease a waiting worker reads.
    await keep_result_claim(job_id)
    await refresh_joiner_lease(job_id, stream_id)


async def _until_the_run_ends(run: StreamSession, beat: Callable[[], Awaitable[None]]) -> None:
    """Return once run ends, or its waiter gave up on it, doing beat on every refresh until then.

    The beat re-arms what this process holds, so it lapses by itself if the process dies.
    """
    while not run.executor_failed:
        await beat()
        try:
            await asyncio.wait_for(
                run.done_event.wait(), timeout=BROWSER_JOB_JOINER_REFRESH_SECONDS
            )
        except TimeoutError:
            continue
        return


def live_run(stream_id: str) -> StreamSession | None:
    """Return the executor run collecting onto this stream, while it has not ended."""
    session = get_session(stream_id)
    return session if session is not None and not session.done_event.is_set() else None


async def _nobody_listening(stream_id: str) -> bool:
    """Whether nothing reads what the relay writes: the turn's live stream finished, and no run collects onto its message."""
    if live_run(stream_id) is not None:
        return False
    progress = await stream_manager.get_progress(stream_id)
    return progress is None or _STREAM_PROGRESS.validate_python(progress).is_complete
