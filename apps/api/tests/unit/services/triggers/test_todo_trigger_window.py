"""Unit tests for app.services.triggers.todo_trigger_window.

A todo's trigger window is its cost fence: one agent run per window, and every
event inside it held for the run at the window's end. Redis is fakeredis, so
the window key's value and TTL and the held list behave as in production.
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import RedisError

from app.db.redis import redis_cache
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import (
    SubscriptionAction,
    SubscriptionResolution,
    TriggerOrigin,
    TriggerSubscription,
    TriggerSubscriptionStatus,
)
from app.services.triggers.todo_trigger_window import (
    TriggerWindow,
    buffer_todo_trigger_event,
    hold_trigger_event_while_paused,
    open_trigger_window,
    release_trigger_events_held_while_paused,
    reschedule_todo_trigger_drain,
    trigger_window,
)
from app.utils.occurrence import occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

TODO_ID = "todo-1"
WINDOW_KEY = f"todo_trigger_window:{TODO_ID}"
BATCH_KEY = f"trigger_batch:todo:{TODO_ID}"
HOLD_KEY = f"trigger_hold:todo:{TODO_ID}"
REFILLED = "[TRIGGER] Trigger batch refilled mid-run — follow-up run scheduled"


def _watch(
    cooldown_seconds: int,
    action: SubscriptionAction = SubscriptionAction.EXECUTE,
    status: TriggerSubscriptionStatus = TriggerSubscriptionStatus.ACTIVE,
) -> TriggerSubscription:
    return TriggerSubscription(
        trigger_name="gmail_new_message",
        action=action,
        resolution=SubscriptionResolution.ACCOUNT,
        cooldown_seconds=cooldown_seconds,
        status=status,
    )


def _todo(*watches: TriggerSubscription) -> TodoDocument:
    return TodoDocument(
        id=TODO_ID, user_id="user-1", title="Chase Acme", trigger_subscriptions=list(watches)
    )


def _now() -> int:
    return occurrence_stamp(datetime.now(UTC))


def _event(message_id: str = "m-1") -> TriggerOrigin:
    return TriggerOrigin(
        subscription_id="sub-1",
        trigger_name="gmail_new_message",
        payload={"message_id": message_id},
    )


@pytest.fixture
def pool() -> Iterator[MagicMock]:
    """Serve an ARQ pool whose enqueue_job records the drain runs scheduled."""
    arq_pool = MagicMock(enqueue_job=AsyncMock(return_value=MagicMock()))
    with patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=arq_pool)):
        yield arq_pool


class TestTriggerWindowSize:
    def test_the_window_is_the_longest_live_execute_cooldown(self) -> None:
        before = _now()
        window = trigger_window(
            _todo(
                _watch(300),
                _watch(900),
                _watch(3600, action=SubscriptionAction.NOTIFY),
            )
        )

        assert (window.key, window.seconds) == (WINDOW_KEY, 900)
        assert before + 900 <= window.end <= _now() + 900

    def test_a_paused_watch_does_not_stretch_the_window(self) -> None:
        """Dispatch never fires a paused watch, so its cooldown must not hold back the live one's replies."""
        window = trigger_window(
            _todo(_watch(300), _watch(3600, status=TriggerSubscriptionStatus.PAUSED))
        )

        assert window.seconds == 300

    def test_a_todo_with_no_live_execute_watch_opens_no_window(self) -> None:
        before = _now()
        window = trigger_window(
            _todo(
                _watch(600, action=SubscriptionAction.NOTIFY),
                _watch(600, status=TriggerSubscriptionStatus.PAUSED),
            )
        )

        assert window.seconds == 0
        assert before <= window.end <= _now()


class TestOpenTriggerWindow:
    async def test_the_window_holds_its_end_until_it_closes(self, fake_redis) -> None:
        await open_trigger_window(TriggerWindow(key=WINDOW_KEY, seconds=900, end=1_790_000_900))

        assert await fake_redis.get(WINDOW_KEY) == "1790000900"
        assert 899 <= await fake_redis.ttl(WINDOW_KEY) <= 900

    async def test_a_one_second_window_still_opens(self, fake_redis) -> None:
        await open_trigger_window(TriggerWindow(key=WINDOW_KEY, seconds=1, end=1_790_000_001))

        assert await fake_redis.get(WINDOW_KEY) == "1790000001"

    async def test_a_zero_window_stays_shut(self, fake_redis) -> None:
        with patch.object(fake_redis, "set", AsyncMock()) as write:
            await open_trigger_window(TriggerWindow(key=WINDOW_KEY, seconds=0, end=1_790_000_000))

        write.assert_not_awaited()
        assert await fake_redis.exists(WINDOW_KEY) == 0

    async def test_without_redis_the_run_goes_on_and_says_so(self, monkeypatch) -> None:
        monkeypatch.setattr(redis_cache, "redis", None)

        async with captured_wide_event() as event:
            await open_trigger_window(TriggerWindow(key=WINDOW_KEY, seconds=900, end=1))

        assert event["warnings"] == [
            {"msg": "todo_trigger.window_unavailable", "window_key": WINDOW_KEY}
        ]

    async def test_a_failed_window_write_does_not_stop_the_run(self, fake_redis) -> None:
        """The run has already drained its held events; an exception here would lose them."""
        with patch.object(fake_redis, "set", AsyncMock(side_effect=RedisError("reset"))):
            async with captured_wide_event() as event:
                await open_trigger_window(TriggerWindow(key=WINDOW_KEY, seconds=900, end=1))

        assert event["warnings"] == [
            {
                "msg": "todo_trigger.window_unavailable",
                "window_key": WINDOW_KEY,
                "error": "reset",
                "error_type": "RedisError",
            }
        ]


class TestHoldingEvents:
    async def test_an_event_inside_an_open_window_drains_at_its_end(self, fake_redis, pool) -> None:
        window_end = _now() + 600
        await fake_redis.set(WINDOW_KEY, str(window_end), ex=600)

        assert await buffer_todo_trigger_event(TODO_ID, _event())

        (held,) = await fake_redis.lrange(BATCH_KEY, 0, -1)
        assert TriggerOrigin.model_validate_json(held) == _event()
        call = pool.enqueue_job.await_args
        assert call.args == ("execute_tracked_todo", TODO_ID)
        assert call.kwargs["_job_id"] == f"trigger_batch:todo:{TODO_ID}:{window_end}"
        assert call.kwargs["trigger_window"] == window_end
        assert 598 <= call.kwargs["_defer_by"] <= 600

    async def test_an_event_with_no_window_open_drains_now(self, fake_redis, pool) -> None:
        before = _now()

        assert await buffer_todo_trigger_event(TODO_ID, _event())

        call = pool.enqueue_job.await_args
        assert call.kwargs["_defer_by"] == 0
        assert before <= call.kwargs["trigger_window"] <= _now()

    async def test_a_refill_drains_at_the_open_windows_end_and_names_the_todo(
        self, fake_redis, pool
    ) -> None:
        window_end = _now() + 300
        await fake_redis.set(WINDOW_KEY, str(window_end), ex=300)
        await fake_redis.rpush(BATCH_KEY, _event().model_dump_json())

        with patch("app.services.triggers.batching.log") as log_mock:
            assert await reschedule_todo_trigger_drain(TODO_ID)

        call = pool.enqueue_job.await_args
        assert call.kwargs["_job_id"] == f"trigger_batch:todo:{TODO_ID}:{window_end}"
        assert 298 <= call.kwargs["_defer_by"] <= 300
        log_mock.info.assert_called_once_with(
            REFILLED, todo_id=TODO_ID, window_seconds=call.kwargs["_defer_by"]
        )

    async def test_an_event_that_cannot_be_held_is_logged_against_its_todo(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(redis_cache, "redis", None)

        with patch("app.services.triggers.batching.log") as log_mock:
            assert not await buffer_todo_trigger_event(TODO_ID, _event())

        assert log_mock.warning.call_args.kwargs == {"todo_id": TODO_ID}

    async def test_nothing_held_schedules_no_drain(self, fake_redis, pool) -> None:
        assert not await reschedule_todo_trigger_drain(TODO_ID)

        pool.enqueue_job.assert_not_awaited()


class TestEventsHeldWhilePaused:
    async def test_an_event_held_while_paused_schedules_no_run(self, fake_redis, pool) -> None:
        assert await hold_trigger_event_while_paused(TODO_ID, _event())

        (held,) = await fake_redis.lrange(HOLD_KEY, 0, -1)
        assert TriggerOrigin.model_validate_json(held) == _event()
        assert await fake_redis.exists(BATCH_KEY) == 0
        pool.enqueue_job.assert_not_awaited()

    async def test_a_release_replays_each_held_event_exactly_once(self, fake_redis, pool) -> None:
        await hold_trigger_event_while_paused(TODO_ID, _event("m-1"))
        await hold_trigger_event_while_paused(TODO_ID, _event("m-2"))

        assert await release_trigger_events_held_while_paused(TODO_ID) == 2
        assert await release_trigger_events_held_while_paused(TODO_ID) == 0

        batch = [
            TriggerOrigin.model_validate_json(e) for e in await fake_redis.lrange(BATCH_KEY, 0, -1)
        ]
        assert batch == [_event("m-1"), _event("m-2")]
        assert await fake_redis.exists(HOLD_KEY) == 0
        assert {c.args for c in pool.enqueue_job.await_args_list} == {
            ("execute_tracked_todo", TODO_ID)
        }

    async def test_a_release_whose_run_cannot_be_scheduled_raises_and_the_retry_schedules_it(
        self, fake_redis, pool
    ) -> None:
        await hold_trigger_event_while_paused(TODO_ID, _event())
        pool.enqueue_job.side_effect = ConnectionError("arq down")

        with pytest.raises(ConnectionError, match="^arq down$"):
            await release_trigger_events_held_while_paused(TODO_ID)

        pool.enqueue_job.side_effect = None
        assert await release_trigger_events_held_while_paused(TODO_ID) == 0
        (held,) = await fake_redis.lrange(BATCH_KEY, 0, -1)
        assert TriggerOrigin.model_validate_json(held) == _event()
        assert pool.enqueue_job.await_args.args == ("execute_tracked_todo", TODO_ID)

    async def test_without_redis_a_release_raises_rather_than_strand_the_events(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(redis_cache, "redis", None)

        with pytest.raises(RuntimeError, match=f"events held for {TODO_ID} cannot replay"):
            await release_trigger_events_held_while_paused(TODO_ID)
