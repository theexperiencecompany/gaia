"""Coalescing of poll-based trigger events (app.services.triggers.batching).

Regression cover for the incident where a Gmail poll trigger fired one full
agent run per inbound email — 56 runs in three minutes, which spent a paying
user's whole daily budget before he had sent a single message.
"""

import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Same circular-import guard the sibling base-handler tests use.
sys.modules.setdefault("app.services.workflow.queue_service", MagicMock())
sys.modules.setdefault("app.services.workflow.trigger_service", MagicMock())

from app.models.trigger_configs import GmailNewMessageConfig, GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.triggers.batching import (
    MAX_TRIGGER_BATCH_EVENTS,
    TRIGGER_BATCH_KEY,
    buffer_trigger_event,
    coalesce_window_seconds,
    drain_trigger_batch,
)

MODULE = "app.services.triggers.batching"


class _FakePipeline:
    """Minimal async-context pipeline recording queued commands."""

    def __init__(self, store: dict[str, list[str]]) -> None:
        self._store = store
        self._results: list[Any] = []
        self._key: str | None = None

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def lrange(self, key: str, _start: int, _end: int) -> None:
        self._results.append(list(self._store.get(key, [])))

    def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._results.append(1)

    async def execute(self) -> list[Any]:
        return self._results


class _FakeRedis:
    """In-memory stand-in for the async Redis client's list operations."""

    def __init__(self) -> None:
        self.store: dict[str, list[str]] = {}
        self.expires: dict[str, int] = {}

    async def rpush(self, key: str, value: str) -> int:
        self.store.setdefault(key, []).append(value)
        return len(self.store[key])

    async def ltrim(self, key: str, start: int, end: int) -> None:
        items = self.store.get(key, [])
        self.store[key] = items[start:] if end == -1 else items[start : end + 1]

    async def expire(self, key: str, seconds: int) -> None:
        self.expires[key] = seconds

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self.store)


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def enqueue(fake_redis: _FakeRedis) -> Any:
    """Patch the Redis client + enqueue seam, yielding the enqueue mock."""
    with (
        patch(f"{MODULE}.redis_cache") as cache,
        patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=MagicMock())),
        patch(f"{MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue_mock,
    ):
        cache.redis = fake_redis
        enqueue_mock.return_value = MagicMock(job_id="job-1")
        yield enqueue_mock


@pytest.mark.unit
class TestCoalesceWindow:
    def test_poll_trigger_batches_over_its_configured_interval(self) -> None:
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_poll_inbox",
            trigger_data=GmailPollInboxConfig(interval=15),
        )
        assert coalesce_window_seconds(config) == 15 * 60

    def test_time_sensitive_trigger_is_never_delayed(self) -> None:
        """A calendar reminder held for a window is a missed meeting."""
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="calendar_event_starting_soon",
            trigger_data=None,
        )
        assert coalesce_window_seconds(config) == 0

    def test_account_level_gmail_trigger_is_not_coalesced(self) -> None:
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_message",
            trigger_data=GmailNewMessageConfig(),
        )
        assert coalesce_window_seconds(config) == 0


@pytest.mark.unit
class TestBufferTriggerEvent:
    async def test_burst_of_events_schedules_exactly_one_run(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        """The whole point: 56 emails must not become 56 agent runs.

        ARQ rejects the duplicate ``_job_id`` by returning None, so every event
        after the first rides the buffer instead of starting its own run.
        """
        enqueue.side_effect = [MagicMock(job_id="job-1")] + [None] * 55

        for index in range(56):
            assert await buffer_trigger_event("wf_1", "user_1", {"id": index}, 900, {})

        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        assert len(fake_redis.store[key]) == 50  # capped, see MAX_TRIGGER_BATCH_EVENTS
        assert enqueue.await_count == 56
        job_ids = {call.kwargs["_job_id"] for call in enqueue.await_args_list}
        assert job_ids == {"trigger_batch:wf_1"}

    async def test_run_is_deferred_by_the_window(self, enqueue: Any) -> None:
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
        assert enqueue.await_args.kwargs["_defer_by"] == 900

    async def test_payload_rides_redis_not_the_job_args(self, enqueue: Any) -> None:
        """The job must carry only the batch key — a per-event payload in the
        args would make every enqueue unique and defeat the dedup entirely."""
        await buffer_trigger_event(
            "wf_1", "user_1", {"subject": "hi"}, 900, {"trigger_type": "integration"}
        )
        _pool, _fn, _workflow_id, context = enqueue.await_args.args
        assert context["trigger_batch_key"] == "trigger_batch:wf_1"
        assert "trigger_data" not in context

    async def test_overflow_keeps_the_newest_events(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        enqueue.return_value = None
        for index in range(MAX_TRIGGER_BATCH_EVENTS + 5):
            await buffer_trigger_event("wf_1", "user_1", {"id": index}, 900, {})

        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        kept = [json.loads(raw)["id"] for raw in fake_redis.store[key]]
        assert kept[-1] == MAX_TRIGGER_BATCH_EVENTS + 4
        assert len(kept) == MAX_TRIGGER_BATCH_EVENTS

    async def test_separate_workflows_do_not_share_a_batch(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
        await buffer_trigger_event("wf_2", "user_2", {"id": 2}, 900, {})

        assert len(fake_redis.store[TRIGGER_BATCH_KEY.format(workflow_id="wf_1")]) == 1
        assert len(fake_redis.store[TRIGGER_BATCH_KEY.format(workflow_id="wf_2")]) == 1
        job_ids = {call.kwargs["_job_id"] for call in enqueue.await_args_list}
        assert job_ids == {"trigger_batch:wf_1", "trigger_batch:wf_2"}


@pytest.mark.unit
class TestDrainTriggerBatch:
    async def test_drain_returns_every_buffered_event_in_order(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        enqueue.return_value = None
        for index in range(3):
            await buffer_trigger_event("wf_1", "user_1", {"id": index}, 900, {})

        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = fake_redis
            events = await drain_trigger_batch(TRIGGER_BATCH_KEY.format(workflow_id="wf_1"))

        assert [event["id"] for event in events] == [0, 1, 2]

    async def test_drain_empties_the_buffer_so_the_next_window_starts_clean(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        enqueue.return_value = None
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")

        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = fake_redis
            assert len(await drain_trigger_batch(key)) == 1
            assert await drain_trigger_batch(key) == []

    async def test_unparseable_event_is_skipped_not_fatal(self, fake_redis: _FakeRedis) -> None:
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = ["{not json", json.dumps({"id": 7})]

        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = fake_redis
            events = await drain_trigger_batch(key)

        assert [event["id"] for event in events] == [7]


@pytest.mark.unit
class TestRedisUnavailable:
    async def test_buffering_reports_failure_so_the_caller_fires_immediately(self) -> None:
        """Losing the user's triggers outright is worse than a burst of runs."""
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue_mock,
        ):
            cache.redis = None
            assert await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {}) is False
        enqueue_mock.assert_not_awaited()

    async def test_drain_returns_nothing_rather_than_raising(self) -> None:
        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = None
            assert await drain_trigger_batch("trigger_batch:wf_1") == []
