"""The job's replayable card feed: ordered replay from 0-0, resume from a cursor, and a poisoned frame that must not kill the relay."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.constants.browser import (
    BROWSER_JOB_EVENTS_MAXLEN,
    BROWSER_JOB_EVENTS_PREFIX,
    BROWSER_JOB_TTL_SECONDS,
)
from app.services.browser import job_events as job_events_mod


class _FakeStreamClient:
    """Minimal Redis stream: monotonic entry ids, XREAD returning only entries after the cursor."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.xadd_calls: list[tuple[str, int | None, bool]] = []
        self.expire_calls: list[tuple[str, int]] = []
        self.xread_calls: list[tuple[dict[str, str], int | None]] = []
        self._seq = 0

    async def xadd(
        self,
        name: str,
        fields: dict[str, str],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        self.xadd_calls.append((name, maxlen, approximate))
        self._seq += 1
        entry_id = f"{self._seq}-0"
        self.streams.setdefault(name, []).append((entry_id, dict(fields)))
        return entry_id

    async def expire(self, name: str, time: int) -> bool:
        self.expire_calls.append((name, time))
        return True

    async def xread(
        self,
        streams: dict[str, str],
        *,
        count: int | None = None,
        block: int | None = None,
    ) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        self.xread_calls.append((dict(streams), block))
        results = []
        for name, cursor in streams.items():
            after = [
                entry
                for entry in self.streams.get(name, [])
                if _entry_sort(entry[0]) > _entry_sort(cursor)
            ]
            if after:
                results.append((name, after))
        return results


def _entry_sort(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeStreamClient:
    client = _FakeStreamClient()
    fake_cache = MagicMock()
    fake_cache.client = client
    monkeypatch.setattr(job_events_mod, "redis_cache", fake_cache)
    return client


def _frame(step: int) -> dict[str, Any]:
    return {"tool_data": {"tool_name": "browser_task_data", "data": {"step": step}}}


@pytest.mark.unit
async def test_every_published_frame_replays_from_the_start_in_order(
    fake_client: _FakeStreamClient,
) -> None:
    for step in (1, 2, 3):
        await job_events_mod.publish_job_event("job-1", _frame(step))

    events = await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [payload for _, payload in events] == [_frame(1), _frame(2), _frame(3)]


@pytest.mark.unit
async def test_reading_from_a_cursor_returns_only_what_came_after_it(
    fake_client: _FakeStreamClient,
) -> None:
    for step in (1, 2, 3):
        await job_events_mod.publish_job_event("job-1", _frame(step))

    events = await job_events_mod.read_job_events("job-1", "0-0", 0)
    resumed = await job_events_mod.read_job_events("job-1", events[1][0], 0)

    assert [payload for _, payload in resumed] == [_frame(3)]


@pytest.mark.unit
async def test_the_feed_is_capped_and_expires_with_the_job(fake_client: _FakeStreamClient) -> None:
    await job_events_mod.publish_job_event("job-1", _frame(1))

    key = f"{BROWSER_JOB_EVENTS_PREFIX}job-1"
    assert fake_client.xadd_calls == [(key, BROWSER_JOB_EVENTS_MAXLEN, True)]
    assert fake_client.expire_calls == [(key, BROWSER_JOB_TTL_SECONDS)]


@pytest.mark.unit
async def test_a_poisoned_frame_is_dropped_and_logged_not_raised(
    fake_client: _FakeStreamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One unreadable entry must not end the relay — every other card still has to reach the user."""
    await job_events_mod.publish_job_event("job-1", _frame(1))
    key = f"{BROWSER_JOB_EVENTS_PREFIX}job-1"
    fake_client.streams[key].append(("2-0", {"payload": "{not json"}))
    fake_client.streams[key].append(("3-0", {"payload": json.dumps(["not", "a", "mapping"])}))
    await job_events_mod.publish_job_event("job-1", _frame(4))

    fake_log = MagicMock()
    monkeypatch.setattr(job_events_mod, "log", fake_log)
    events = await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [payload for _, payload in events] == [_frame(1), _frame(4)]
    assert fake_log.error.call_count == 2


@pytest.mark.unit
async def test_a_blocking_read_passes_its_budget_to_redis_and_a_zero_does_not_block(
    fake_client: _FakeStreamClient,
) -> None:
    """block=0 must mean "whatever is there now": the worker drains the whole feed with it and can never hang on an empty stream."""
    await job_events_mod.read_job_events("job-1", "0-0", 1000)
    await job_events_mod.read_job_events("job-1", "0-0", 0)

    assert [block for _, block in fake_client.xread_calls] == [1000, None]


@pytest.mark.unit
async def test_reading_a_feed_that_has_no_frames_yet_is_empty(
    fake_client: _FakeStreamClient,
) -> None:
    assert await job_events_mod.read_job_events("job-unknown", "0-0", 0) == []
