"""The job's replayable card feed: ordered replay, resume from a cursor, a poisoned frame that must not kill a reader, and the wait for its end.

Real code over fakeredis.
"""

import asyncio
import json
from typing import Any

import fakeredis.aioredis
import pytest

from app.constants.browser import BROWSER_JOB_EVENTS_PREFIX
from app.constants.log_tags import LogTag
from app.services.browser import job_events as job_events_mod
from app.services.browser.job_events import JOB_GUIDANCE_FRAME, JOB_TERMINAL_FRAME
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

KEY = f"{BROWSER_JOB_EVENTS_PREFIX}job-1"


@pytest.fixture(autouse=True)
def redis(fake_redis: fakeredis.aioredis.FakeRedis) -> fakeredis.aioredis.FakeRedis:
    return fake_redis


def _frame(step: int) -> dict[str, Any]:
    return {"tool_data": {"tool_name": "browser_task_data", "data": {"step": step}}}


async def test_frames_replay_in_order_and_a_cursor_resumes_after_itself(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    for step in (1, 2, 3):
        await job_events_mod.publish_job_event("job-1", _frame(step))

    events = await job_events_mod.read_job_events("job-1", "0-0")
    resumed = await job_events_mod.read_job_events("job-1", events[1][0])

    assert [payload for _, payload in events] == [_frame(1), _frame(2), _frame(3)]
    assert [payload for _, payload in resumed] == [_frame(3)]
    assert await redis.ttl(KEY) > 0
    # The newest frame is where a reader that wants only what comes next starts.
    assert await job_events_mod.feed_end("job-1") == events[2][0]
    assert await job_events_mod.feed_end("job-2") == "0-0"


async def test_the_whole_feed_reads_back_as_its_cards_alone() -> None:
    await job_events_mod.publish_job_event("job-1", _frame(1))
    await job_events_mod.publish_job_event("job-1", JOB_GUIDANCE_FRAME)
    await job_events_mod.publish_job_event("job-1", _frame(2))
    await job_events_mod.publish_job_event("job-1", JOB_TERMINAL_FRAME)

    assert await job_events_mod.read_cards("job-1") == [_frame(1), _frame(2)]


async def test_a_poisoned_frame_is_dropped_and_logged_not_raised(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """One unreadable entry must not end the relay; every other card still has to reach the user."""
    await job_events_mod.publish_job_event("job-1", _frame(1))
    malformed = await redis.xadd(KEY, {"payload": "{not json"})
    not_an_object = await redis.xadd(KEY, {"payload": json.dumps(["not", "a", "mapping"])})
    await job_events_mod.publish_job_event("job-1", _frame(5))

    async with captured_wide_event() as event:
        events = await job_events_mod.read_job_events("job-1", "0-0")
        cards = await job_events_mod.read_cards("job-1")

    assert [payload for _, payload in events] == [_frame(1), _frame(5)]
    assert cards == [_frame(1), _frame(5)]
    errors = [(error["msg"], error["entry_id"]) for error in event["errors"]]
    assert (
        errors
        == [
            (f"{LogTag.BROWSER} Dropping malformed browser job frame", malformed),
            (f"{LogTag.BROWSER} Dropping non-object browser job frame", not_an_object),
        ]
        * 2
    )


async def test_a_read_waits_for_the_next_frame_and_the_feed_is_capped(
    monkeypatch: pytest.MonkeyPatch, redis: fakeredis.aioredis.FakeRedis
) -> None:
    reading = asyncio.create_task(job_events_mod.read_job_events("job-1", "0-0"))
    for _ in range(20):
        await asyncio.sleep(0)
    await job_events_mod.publish_job_event("job-1", _frame(1))

    assert [payload for _, payload in await reading] == [_frame(1)]

    monkeypatch.setattr(job_events_mod, "BROWSER_JOB_EVENTS_MAXLEN", 2)
    for step in (2, 3, 4):
        await job_events_mod.publish_job_event("job-1", _frame(step))
    assert await redis.xlen(KEY) == 2


async def test_the_end_is_found_after_the_cards_before_it(monkeypatch: pytest.MonkeyPatch) -> None:
    await job_events_mod.publish_job_event("job-1", _frame(1))
    first_read = asyncio.Event()
    read = job_events_mod.read_job_events

    async def _read_then_mark(job_id: str, cursor: str) -> Any:
        events = await read(job_id, cursor)
        first_read.set()
        return events

    monkeypatch.setattr(job_events_mod, "read_job_events", _read_then_mark)
    waiting = asyncio.create_task(job_events_mod.wait_for_job_end("job-1", within_seconds=5))
    await first_read.wait()

    await job_events_mod.publish_job_event("job-1", JOB_TERMINAL_FRAME)

    assert await waiting is True


async def test_a_feed_that_never_ends_is_waited_on_only_as_long_as_asked() -> None:
    await job_events_mod.publish_job_event("job-1", _frame(1))

    assert await job_events_mod.wait_for_job_end("job-1", within_seconds=0.05) is False
