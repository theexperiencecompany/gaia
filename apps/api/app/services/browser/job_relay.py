"""Follow a browser job's card feed: live onto the starting turn's message, or into a headless run's stream.

The worker publishes every card to the job's own Redis feed. A background job's
relay replays it onto a detached stream of its own, which the client folds into
the message of the turn that started it (as it folds a background subagent's),
and saves the cards into that message when the job ends. A headless job's tool
call follows the same feed into its own run's stream while it blocks.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import partial
from uuid import uuid4

from app.agents.core.background.executor_queue import open_detached_stream
from app.agents.core.background.folded_stream import close_folded_stream
from app.agents.core.background.redis_writer import publish_to_stream
from app.constants.browser import BROWSER_JOB_STREAM_ID_PREFIX
from app.constants.log_tags import LogTag
from app.constants.streaming import DetachedStreamKind
from app.schemas.browser_job import BrowserJobRequest
from app.services.browser.job_events import JOB_TERMINAL_FRAME, read_job_events
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from app.services.browser.jobs import done_state, get_conversation_slot
from shared.py.wide_events import log

#: Takes one card frame of the feed, in order.
CardSink = Callable[[dict[str, object]], Awaitable[None]]


async def follow_job_cards(job_id: str, conversation_id: str, sink: CardSink) -> None:
    """Hand sink every card of the job's feed, in order, until the feed closes.

    Read from 0-0, so a follower that starts late still sees the run from step
    1. A job that ended with no worker left on it closes its feed no more: once
    the feed is quiet for a beat, its ending recorded and its slot free, the
    follow ends there.
    """
    cursor = "0-0"
    while True:
        events = await read_job_events(job_id, cursor)
        for entry_id, payload in events:
            if payload == JOB_TERMINAL_FRAME:
                return
            await sink(payload)
            cursor = entry_id
        if (
            not events
            and await done_state(job_id) is not None
            and await get_conversation_slot(conversation_id) != job_id
        ):
            log.warning(
                f"{LogTag.BROWSER} Browser job ended with no worker left to close its feed",
                browser={"job_id": job_id},
            )
            return


async def relay_job_cards(request: BrowserJobRequest) -> None:
    """Replay a background job's cards onto a stream folded into its starting turn's message, then save them there.

    Runs as a logged background task beside the turn that started the job, and
    outlives it: a crash here costs the cards, never the job.
    """
    log.set(browser={"job_id": request.job_id})
    stream_id = f"{BROWSER_JOB_STREAM_ID_PREFIX}{uuid4()}"
    await open_detached_stream(
        stream_id,
        conversation_id=request.conversation_id,
        user_id=request.user_id,
        task_id=request.job_id,
        bot_message_id=request.message_id,
        kind=DetachedStreamKind.SUBAGENT,
    )
    try:
        # Until the feed itself expires: past the latest the worker lets the job end.
        async with asyncio.timeout(browser_job_ttl_seconds()):
            await follow_job_cards(
                request.job_id, request.conversation_id, partial(publish_to_stream, stream_id)
            )
    except TimeoutError:
        log.warning(
            f"{LogTag.BROWSER} Browser job relay gave up before the job finished",
            browser={"job_id": request.job_id},
        )
    except Exception as exc:
        log.error(
            f"{LogTag.BROWSER} Browser job relay stopped",
            error_type=type(exc).__name__,
            error=str(exc),
            browser={"job_id": request.job_id},
        )
    finally:
        await close_folded_stream(
            stream_id,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            message_id=request.message_id,
        )
