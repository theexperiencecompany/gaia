"""Replay a background job's card feed into the turn that started it, and hold its result for that turn.

The worker publishes cards to the job's own Redis stream; this forwards them
into the turn's stream and its collected tool events, one at a time and in
order, which is what puts them on the live SSE stream and on the turn's
message. Publishing to the stream from the worker would reach the first but
not the second, and the cards would vanish on reload.

While the executor run that started the job is alive it may still join and
speak the result, so the relay holds the result for it until that run ends;
the worker tells the user itself only once nothing holds it.
"""

import asyncio
from time import monotonic

from pydantic import TypeAdapter

from app.agents.core.background.redis_writer import publish_to_stream
from app.agents.core.background.session import StreamSession, get_session
from app.constants.browser import BROWSER_JOB_JOINER_REFRESH_SECONDS, BROWSER_JOB_RELAY_BLOCK_MS
from app.constants.log_tags import LogTag
from app.core.stream_manager import StreamProgress, stream_manager
from app.services.browser.job_events import JOB_TERMINAL_FRAME, is_card_frame, read_job_events
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from app.services.browser.jobs import hold_result_for_run, job_cancel_requested, release_result_hold
from shared.py.wide_events import log

_STREAM_PROGRESS: TypeAdapter[StreamProgress] = TypeAdapter(StreamProgress)


async def relay_job_events(job_id: str, stream_id: str) -> None:
    """Replay a job's card feed into a turn's live stream until the job ends or nobody reads the stream.

    Runs in the API process as a logged background task, from 0-0 so a late or
    restarted relay still shows every card. A stopped job is followed to its
    stopped card even though its turn ended with the stop. Never raises.
    """
    # Until the feed itself expires: past the latest the worker lets the job end.
    budget = browser_job_ttl_seconds()
    deadline = monotonic() + budget
    log.set(browser={"job_id": job_id})
    try:
        if _live_run(stream_id) is not None:
            await hold_result_for_run(job_id, stream_id)
        if await _relay_until_the_end(job_id, stream_id, deadline):
            await _hold_for_the_run(job_id, stream_id, deadline)
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
        await release_result_hold(job_id, stream_id)


async def _relay_until_the_end(job_id: str, stream_id: str, deadline: float) -> bool:
    """Forward cards until the job's terminal frame; False when the relay stopped first."""
    cursor = "0-0"
    while monotonic() < deadline:
        for entry_id, payload in await read_job_events(job_id, cursor, BROWSER_JOB_RELAY_BLOCK_MS):
            cursor = entry_id
            if payload == JOB_TERMINAL_FRAME:
                log.set_ns("browser", relay_end="job_finished")
                return True
            if is_card_frame(payload):
                await publish_to_stream(stream_id, payload)
        if await _nobody_listening(stream_id) and not await job_cancel_requested(job_id):
            # The message that speaks the result carries the run's cards from the feed.
            log.set_ns("browser", relay_end="turn_ended")
            return False
        if _live_run(stream_id) is not None:
            await hold_result_for_run(job_id, stream_id)
        else:
            await release_result_hold(job_id, stream_id)
    log.warning(
        f"{LogTag.BROWSER} Browser job relay gave up before the job finished",
        browser={"job_id": job_id},
    )
    return False


async def _hold_for_the_run(job_id: str, stream_id: str, deadline: float) -> None:
    """Keep the result for the executor run that started the job, until that run ends: it may still join and speak it."""
    run = _live_run(stream_id)
    while run is not None and monotonic() < deadline:
        try:
            await asyncio.wait_for(
                run.done_event.wait(), timeout=BROWSER_JOB_JOINER_REFRESH_SECONDS
            )
        except TimeoutError:
            # Still running: re-arm the hold, which lapses on its own if this process dies.
            await hold_result_for_run(job_id, stream_id)
            continue
        return


def _live_run(stream_id: str) -> StreamSession | None:
    """Return the executor run collecting onto this stream, while it has not ended."""
    session = get_session(stream_id)
    return session if session is not None and not session.done_event.is_set() else None


async def _nobody_listening(stream_id: str) -> bool:
    """Whether nothing reads what the relay writes: the turn's live stream finished, and no run collects onto its message."""
    if _live_run(stream_id) is not None:
        return False
    progress = await stream_manager.get_progress(stream_id)
    return progress is None or _STREAM_PROGRESS.validate_python(progress).is_complete
