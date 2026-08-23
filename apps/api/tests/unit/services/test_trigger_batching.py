"""Coalescing of poll-based trigger events (app.services.triggers.batching).

Regression cover for the incident where a Gmail poll trigger fired one full
agent run per inbound email — 56 runs in three minutes, which spent a paying
user's whole daily budget before he had sent a single message.
"""

from datetime import UTC, datetime
import json
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.trigger_configs import GmailNewMessageConfig, GmailPollInboxConfig
from app.models.workflow_models import TriggerConfig, TriggerType
from app.services.triggers.batching import (
    MAX_TRIGGER_BATCH_EVENTS,
    PER_EMAIL_FALLBACK_WINDOW_SECONDS,
    TRIGGER_BATCH_KEY,
    TRIGGER_BATCH_TTL_FLOOR_SECONDS,
    buffer_trigger_event,
    coalesce_window_seconds,
    drain_trigger_batch,
    reschedule_if_refilled,
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

    def lrange(self, key: str, start: int, end: int) -> None:
        # Real Redis rejects non-integer range args; a fake that silently
        # coerces them would excuse a mutant the wire protocol kills.
        if not isinstance(start, int) or not isinstance(end, int):
            raise TypeError("lrange bounds must be integers")
        items = self._store.get(key, [])
        stop = len(items) if end == -1 else end + 1
        self._results.append(list(items[start:stop]))

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
        self.ltrim_calls: list[tuple[str, int, int]] = []
        self.pipeline_transactions: list[bool] = []

    async def rpush(self, key: str, value: str) -> int:
        self.store.setdefault(key, []).append(value)
        return len(self.store[key])

    async def llen(self, key: str) -> int:
        return len(self.store.get(key, []))

    async def ltrim(self, key: str, start: int, end: int) -> None:
        self.ltrim_calls.append((key, start, end))
        items = self.store.get(key, [])
        self.store[key] = items[start:] if end == -1 else items[start : end + 1]

    async def expire(self, key: str, seconds: int) -> None:
        self.expires[key] = seconds

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        self.pipeline_transactions.append(transaction)
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

    def test_account_level_gmail_trigger_falls_back_to_the_daily_window(self) -> None:
        """gmail_new_message declares no interval, and firing per email is never
        a cadence anyone chose — it batches on the daily fallback."""
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_message",
            trigger_data=GmailNewMessageConfig(),
        )
        assert coalesce_window_seconds(config) == PER_EMAIL_FALLBACK_WINDOW_SECONDS

    def test_account_level_gmail_trigger_with_no_trigger_data_still_batches(self) -> None:
        """The 126 prod workflows on this trigger carry trigger_data=None — the
        fallback must key on the trigger name, not the config object."""
        config = TriggerConfig(
            type=TriggerType.INTEGRATION,
            trigger_name="gmail_new_message",
            trigger_data=None,
        )
        assert coalesce_window_seconds(config) == PER_EMAIL_FALLBACK_WINDOW_SECONDS


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
        _pool, fn, workflow_id, context = enqueue.await_args.args
        assert fn == "execute_workflow_by_id"
        assert workflow_id == "wf_1"
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

    async def test_drain_reports_unavailability_as_none_not_empty(self) -> None:
        """None and [] mean different things: [] lets the worker exit "cleanly",
        None tells it the buffer may still hold events it must not claim drained."""
        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = None
            assert await drain_trigger_batch("trigger_batch:wf_1") is None


@pytest.mark.unit
class TestRescheduleIfRefilled:
    async def test_refilled_buffer_gets_a_follow_up_run(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = [json.dumps({"id": 99})]

        assert await reschedule_if_refilled(
            "wf_1", key, 900, {"trigger_type": "integration", "trigger_data": {"count": 3}}
        )

        assert enqueue.await_args.kwargs["_defer_by"] == 900
        # A unique id: this run's own id is still occupied, so reusing it
        # would strand the refill exactly like the events it exists to save.
        assert enqueue.await_args.kwargs["_job_id"].startswith("trigger_batch:wf_1:refill:")
        context = enqueue.await_args.args[3]
        assert context["trigger_batch_key"] == key
        assert "trigger_data" not in context  # the drained events must not ride along

    async def test_empty_buffer_schedules_nothing(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")

        assert not await reschedule_if_refilled("wf_1", key, 900, {})
        enqueue.assert_not_awaited()


@pytest.mark.unit
class TestBufferTtl:
    async def test_short_window_ttl_survives_a_worker_outage(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        """Observed live: a 1-minute window's 4x TTL (240s) expired the batch
        during a 268s worker outage, so the run fired against nothing and the
        events silently vanished. The floor makes short windows restart-proof."""
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 60, {})
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        assert fake_redis.expires[key] == TRIGGER_BATCH_TTL_FLOOR_SECONDS

    async def test_long_window_ttl_still_scales_with_the_window(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        day = 24 * 60 * 60
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, day, {})
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        assert fake_redis.expires[key] == day * 4


@pytest.fixture
def batch_log() -> Any:
    """Spy on the module's logger so warning payloads — which reach the wide
    event and page a human — are pinned as behaviour, not decoration."""
    with patch(f"{MODULE}.log") as log_mock:
        yield log_mock


@pytest.mark.unit
class TestObservableBehaviour:
    """The parts of the contract that only show up operationally: what gets
    enqueued by name, what lands in Redis, and what the warnings say."""

    async def test_the_scheduled_job_is_the_workflow_executor(self, enqueue: Any) -> None:
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
        assert enqueue.await_args.args[1] == "execute_workflow_by_id"

    async def test_non_json_payload_fields_are_stringified_not_fatal(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        """Webhook payloads carry datetimes after model parsing; default=str is
        what keeps the buffer write from raising on them."""
        await buffer_trigger_event(
            "wf_1", "user_1", {"at": datetime(2026, 8, 23, tzinfo=UTC)}, 900, {}
        )

        raw = fake_redis.store[TRIGGER_BATCH_KEY.format(workflow_id="wf_1")][0]
        assert json.loads(raw)["at"] == "2026-08-23 00:00:00+00:00"

    async def test_redis_unavailable_warns_with_the_workflow_identified(self) -> None:
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.log") as log_mock,
            patch(f"{MODULE}.enqueue_worker_job", new_callable=AsyncMock),
        ):
            cache.redis = None
            await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})

        log_mock.warning.assert_called_once_with(
            "[TRIGGER] Redis unavailable — trigger event cannot be batched",
            workflow_id="wf_1",
            user_id="user_1",
        )

    async def test_overflow_trims_to_the_cap_and_reports_the_drop(
        self, fake_redis: _FakeRedis, enqueue: Any, batch_log: Any
    ) -> None:
        enqueue.return_value = None
        for index in range(MAX_TRIGGER_BATCH_EVENTS + 5):
            await buffer_trigger_event("wf_1", "user_1", {"id": index}, 900, {})

        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        assert fake_redis.ltrim_calls[-1] == (key, -MAX_TRIGGER_BATCH_EVENTS, -1)
        batch_log.warning.assert_called_with(
            "[TRIGGER] Trigger batch full — oldest events dropped",
            workflow_id="wf_1",
            user_id="user_1",
            dropped_count=1,
            max_batch=MAX_TRIGGER_BATCH_EVENTS,
        )

    async def test_exactly_at_the_cap_nothing_is_trimmed_or_warned(
        self, fake_redis: _FakeRedis, enqueue: Any, batch_log: Any
    ) -> None:
        enqueue.return_value = None
        for index in range(MAX_TRIGGER_BATCH_EVENTS):
            await buffer_trigger_event("wf_1", "user_1", {"id": index}, 900, {})

        assert fake_redis.ltrim_calls == []
        batch_log.warning.assert_not_called()
        assert len(fake_redis.store[TRIGGER_BATCH_KEY.format(workflow_id="wf_1")]) == (
            MAX_TRIGGER_BATCH_EVENTS
        )

    async def test_drain_uses_a_transactional_pipeline(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        """Read-and-delete must be atomic — a non-transactional drain lets an
        event slip in between and be deleted unread."""
        enqueue.return_value = None
        await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
        with patch(f"{MODULE}.redis_cache") as cache:
            cache.redis = fake_redis
            await drain_trigger_batch(TRIGGER_BATCH_KEY.format(workflow_id="wf_1"))

        assert fake_redis.pipeline_transactions == [True]

    async def test_unparseable_event_is_reported_with_its_batch_key(
        self, fake_redis: _FakeRedis
    ) -> None:
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = ["{not json"]
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.log") as log_mock,
        ):
            cache.redis = fake_redis
            await drain_trigger_batch(key)

        log_mock.warning.assert_called_once_with(
            "[TRIGGER] Discarding unparseable buffered trigger event",
            batch_key=key,
        )

    async def test_refill_job_id_shape_is_exact(self, fake_redis: _FakeRedis, enqueue: Any) -> None:
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = [json.dumps({"id": 1})]

        await reschedule_if_refilled("wf_1", key, 900, {})

        job_id = enqueue.await_args.kwargs["_job_id"]
        assert re.fullmatch(r"trigger_batch:wf_1:refill:[0-9a-f]{12}", job_id)
        assert enqueue.await_args.args[1] == "execute_workflow_by_id"
        assert enqueue.await_args.args[2] == "wf_1"


@pytest.mark.unit
class TestRedisCommandFailure:
    async def test_a_redis_write_error_degrades_to_immediate_dispatch(self) -> None:
        """A raised RedisError must behave like a missing client: report the
        failure and return False so the caller dispatches the event instead of
        dropping it."""
        from redis.exceptions import RedisError

        client = MagicMock()
        client.rpush = AsyncMock(side_effect=RedisError("boom"))
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.log") as log_mock,
            patch(f"{MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue_mock,
        ):
            cache.redis = client
            assert await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {}) is False

        enqueue_mock.assert_not_awaited()
        log_mock.warning.assert_called_once_with(
            "[TRIGGER] Redis write failed — trigger event cannot be batched",
            workflow_id="wf_1",
            user_id="user_1",
            error="boom",
            error_type="RedisError",
        )

    async def test_drain_reports_redis_unavailability(self) -> None:
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.log") as log_mock,
        ):
            cache.redis = None
            assert await drain_trigger_batch("trigger_batch:wf_1") is None

        log_mock.warning.assert_called_once_with(
            "[TRIGGER] Redis unavailable — trigger batch cannot be drained"
        )


@pytest.mark.unit
class TestEnqueuePool:
    async def test_jobs_are_enqueued_on_the_arq_pool(self, fake_redis: _FakeRedis) -> None:
        """Both scheduling paths must hand enqueue the real ARQ pool — a None
        pool only fails at send time, far from the mistake."""
        pool = MagicMock(name="arq-pool")
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
            patch(f"{MODULE}.enqueue_worker_job", new_callable=AsyncMock) as enqueue_mock,
        ):
            cache.redis = fake_redis
            await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {})
            assert enqueue_mock.await_args.args[0] is pool

            fake_redis.store["trigger_batch:wf_1"] = [json.dumps({"id": 2})]
            await reschedule_if_refilled("wf_1", "trigger_batch:wf_1", 900, {})
            assert enqueue_mock.await_args.args[0] is pool

    async def test_an_enqueue_failure_degrades_to_immediate_dispatch(
        self, fake_redis: _FakeRedis
    ) -> None:
        """A buffered event with no scheduled run would sit until the next
        event or expire — a scheduling failure must fall back to dispatching
        the event now, duplicate risk and all."""
        with (
            patch(f"{MODULE}.redis_cache") as cache,
            patch(f"{MODULE}.log") as log_mock,
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=MagicMock())),
            patch(
                f"{MODULE}.enqueue_worker_job",
                new_callable=AsyncMock,
                side_effect=ConnectionError("arq down"),
            ),
        ):
            cache.redis = fake_redis
            assert await buffer_trigger_event("wf_1", "user_1", {"id": 1}, 900, {}) is False

        log_mock.warning.assert_called_once_with(
            "[TRIGGER] Batch run scheduling failed — dispatching event immediately",
            workflow_id="wf_1",
            user_id="user_1",
            error="arq down",
            error_type="ConnectionError",
        )


@pytest.mark.unit
class TestRefillTtlRenewal:
    async def test_refill_renews_the_buffer_ttl(self, fake_redis: _FakeRedis, enqueue: Any) -> None:
        """A workflow gate-rejected all day reschedules repeatedly; without TTL
        renewal the buffer set at first-write time expires under the cycle and
        the events the follow-up job exists to drain silently vanish."""
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = [json.dumps({"id": 1})]

        assert await reschedule_if_refilled("wf_1", key, 900, {})

        assert fake_redis.expires[key] == TRIGGER_BATCH_TTL_FLOOR_SECONDS

    async def test_refill_ttl_scales_with_long_windows(
        self, fake_redis: _FakeRedis, enqueue: Any
    ) -> None:
        day = 24 * 60 * 60
        key = TRIGGER_BATCH_KEY.format(workflow_id="wf_1")
        fake_redis.store[key] = [json.dumps({"id": 1})]

        await reschedule_if_refilled("wf_1", key, day, {})

        assert fake_redis.expires[key] == day * 4
