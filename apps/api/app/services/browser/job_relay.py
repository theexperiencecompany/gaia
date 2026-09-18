"""Replay a background job's card feed into the conversation stream that asked for it.

The worker publishes cards to the job's own Redis stream; this forwards them
through the same writer a background subagent uses, which is what puts them on
the live SSE stream and into the turn's collected tool events. Publishing to
the stream from the worker would reach the first but not the second, and the
cards would vanish on reload.
"""

from time import monotonic

from app.agents.core.background.redis_writer import make_redis_stream_writer
from app.config.settings import settings
from app.constants.browser import BROWSER_JOB_RELAY_BLOCK_MS
from app.constants.log_tags import LogTag
from app.core.stream_manager import stream_manager
from app.services.browser.job_events import JOB_TERMINAL_FRAME, read_job_events
from shared.py.wide_events import log


async def relay_job_events(job_id: str, stream_id: str) -> None:
    """Replay a job's card feed into a conversation's live stream until it ends.

    Runs in the API process under spawn_background_task, from 0-0 so a late or
    restarted relay still shows every card. Never raises.
    """
    writer = make_redis_stream_writer(stream_id)
    cursor = "0-0"
    # The longest a run can legitimately take: its own budget plus one handoff.
    budget = (
        settings.BROWSER_USE_TASK_TIMEOUT_SECONDS + settings.BROWSER_USE_HANDOFF_TIMEOUT_SECONDS
    )
    deadline = monotonic() + budget
    try:
        while monotonic() < deadline:
            if await stream_manager.is_cancelled(stream_id):
                return
            for entry_id, payload in await read_job_events(
                job_id, cursor, BROWSER_JOB_RELAY_BLOCK_MS
            ):
                cursor = entry_id
                if payload == JOB_TERMINAL_FRAME:
                    return
                writer(payload)
    except Exception as exc:
        # The relay is fire-and-forget beside the turn: a crash here costs the
        # remaining cards, and must never cost the turn itself.
        log.error(
            f"{LogTag.BROWSER} Browser job relay stopped",
            error_type=type(exc).__name__,
            browser={"job_id": job_id},
        )
