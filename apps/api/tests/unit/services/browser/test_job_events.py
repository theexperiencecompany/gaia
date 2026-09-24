"""The job's replayable card feed: ordered replay from 0-0, resume from a cursor, and a poisoned frame that must not kill the relay."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import (
    BROWSER_JOB_EVENTS_MAXLEN,
    BROWSER_JOB_EVENTS_PREFIX,
)
from app.services.browser import job_events as job_events_mod
from app.services.browser.job_lifetime import browser_job_ttl_seconds
from tests._harness.redis_fakes import FakeRedisClient
from tests.helpers import captured_wide_event


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeRedisClient:
    client = FakeRedisClient()
    fake_cache = MagicMock()
    fake_cache.client = client
    monkeypatch.setattr(job_events_mod, "redis_cache", fake_cache)
    return client


def _frame(step: int) -> dict[str, Any]:
    return {"tool_data": {"tool_name": "browser_task_data", "data": {"step": step}}}


@pytest.mark.unit
async def test_every_published_frame_replays_from_the_start_in_order(
    fake_client: FakeRedisClient,
) -> None:
    for step in (1, 2, 3):
        await job_events_mod.publish_job_event("job-1", _frame(step))

    events = await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [payload for _, payload in events] == [_frame(1), _frame(2), _frame(3)]


@pytest.mark.unit
async def test_reading_from_a_cursor_returns_only_what_came_after_it(
    fake_client: FakeRedisClient,
) -> None:
    for step in (1, 2, 3):
        await job_events_mod.publish_job_event("job-1", _frame(step))

    events = await job_events_mod.read_job_events("job-1", "0-0", 0)
    resumed = await job_events_mod.read_job_events("job-1", events[1][0], 0)

    assert [payload for _, payload in resumed] == [_frame(3)]


@pytest.mark.unit
async def test_the_feed_is_capped_and_expires_with_the_job(fake_client: FakeRedisClient) -> None:
    await job_events_mod.publish_job_event("job-1", _frame(1))

    key = f"{BROWSER_JOB_EVENTS_PREFIX}job-1"
    assert fake_client.xadd_calls == [(key, BROWSER_JOB_EVENTS_MAXLEN, True)]
    assert fake_client.expire_calls == [(key, browser_job_ttl_seconds())]


@pytest.mark.unit
async def test_a_poisoned_frame_is_dropped_and_logged_not_raised(
    fake_client: FakeRedisClient,
) -> None:
    """One unreadable entry must not end the relay — every other card still has to reach the user."""
    await job_events_mod.publish_job_event("job-1", _frame(1))
    key = f"{BROWSER_JOB_EVENTS_PREFIX}job-1"
    fake_client.streams[key].append(("2-0", {"payload": "{not json"}))
    fake_client.streams[key].append(("3-0", {"payload": json.dumps(["not", "a", "mapping"])}))
    fake_client.streams[key].append(("4-0", {}))
    await job_events_mod.publish_job_event("job-1", _frame(5))

    async with captured_wide_event() as event:
        events = await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [payload for _, payload in events] == [_frame(1), _frame(5)]
    errors = event["errors"]
    assert [error["entry_id"] for error in errors] == ["2-0", "3-0", "4-0"]
    # An unparseable frame and a parseable non-object one are told apart in the log.
    assert errors[0]["msg"] and errors[1]["msg"]
    assert errors[0]["msg"] != errors[1]["msg"]


@pytest.mark.unit
async def test_a_blocking_read_passes_its_budget_to_redis_and_a_zero_does_not_block(
    fake_client: FakeRedisClient,
) -> None:
    """block=0 must mean "whatever is there now": the worker drains the whole feed with it and can never hang on an empty stream."""
    await job_events_mod.read_job_events("job-1", "0-0", 1000)
    await job_events_mod.read_job_events("job-1", "0-0", 1)
    await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [block for _, block in fake_client.xread_calls] == [1000, 1, None]


@pytest.mark.unit
async def test_reading_a_feed_that_has_no_frames_yet_is_empty(
    fake_client: FakeRedisClient,
) -> None:
    assert await job_events_mod.read_job_events("job-unknown", "0-0", 0) == []
