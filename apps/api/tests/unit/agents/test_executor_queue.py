"""Unit tests for executor queue mechanics (executor_queue.py).

Pins the lock-handoff contract (pop overwrites the busy lock BEFORE returning,
so call_executor can never sneak in through a delete→re-set gap), the queued
session registration, and the queue-item serialization rules.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.core.background import executor_queue as eq, session as sess
from app.agents.core.background.executor_queue import (
    LockState,
    build_lock_value,
    enqueue_task,
    get_lock_state,
    parse_lock_value,
    pop_next_queued_run,
    reclaim_stranded_task,
    release_lock_if_owned,
)
from app.agents.core.background.session import RunKind, get_session
from app.constants.cache import EXECUTOR_BUSY_TTL, EXECUTOR_QUEUE_TTL


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _queue_item(**overrides) -> str:
    item = {
        "task": "summarize my inbox",
        "task_id": "task-7",
        "configurable": {
            "user_id": "u1",
            "email": "u1@x.com",
            "user_name": "Uno",
            "stream_id": "old-stream",
        },
        "user_time_str": "2026-06-13T10:00:00",
        "conversation_id": "conv-1",
        "user_message_id": "msg-1",
    }
    item.update(overrides)
    return json.dumps(item)


@pytest.mark.unit
class TestLockValue:
    def test_roundtrip(self) -> None:
        value = build_lock_value("stream-1", "task-1")
        assert parse_lock_value(value) == ("stream-1", "task-1")

    def test_missing_stream_id_builds_parseable_value(self) -> None:
        assert parse_lock_value(build_lock_value(None, "task-1")) == ("", "task-1")

    def test_parse_without_separator_returns_value_as_stream(self) -> None:
        assert parse_lock_value("legacy") == ("legacy", "")


@pytest.mark.unit
class TestPopNextQueuedRun:
    async def test_empty_queue_returns_none(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.lpop = AsyncMock(return_value=None)
            assert await pop_next_queued_run("conv-1") is None

    async def test_unparseable_item_returns_none_without_taking_lock(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.lpop = AsyncMock(return_value="{not json")
            redis.client.set = AsyncMock()
            assert await pop_next_queued_run("conv-1") is None
            redis.client.set.assert_not_awaited()

    async def test_valid_item_prepares_run_and_overwrites_lock(self) -> None:
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.lpop = AsyncMock(return_value=_queue_item())
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await pop_next_queued_run("conv-1")

        assert prepared is not None
        run = prepared.run

        # Run identity: QUEUED kind assigned at the pop site (never parsed
        # from the stream id), task wiring intact.
        assert run.kind is RunKind.QUEUED
        assert run.is_queued is True
        assert run.task_id == "task-7"
        assert run.user_message_id == "msg-1"
        assert run.conversation_id == "conv-1"
        assert run.user == {"user_id": "u1", "email": "u1@x.com", "name": "Uno"}

        # The popped item's stale stream_id is replaced by the fresh queued one.
        assert prepared.configurable["stream_id"] == run.stream_id
        assert run.stream_id != "old-stream"
        assert prepared.task == "summarize my inbox"
        assert prepared.user_time.year == 2026

        # Lock overwritten with the new run's value BEFORE returning, via the RAW
        # client.set — the value must be the unquoted lock string get_lock_state
        # reads back, NOT redis_cache.set's JSON-encoded (quoted) form.
        redis.client.set.assert_awaited_once()
        args, kwargs = redis.client.set.await_args
        assert args[0] == "executor:busy:conv-1"
        assert args[1] == build_lock_value(run.stream_id, "task-7")
        assert kwargs["ex"] == EXECUTOR_BUSY_TTL

        # Session registered as QUEUED with the executor pre-marked spawned
        # (queued runs have no chat_service to register for them).
        session = get_session(run.stream_id)
        assert session is not None
        assert session.kind is RunKind.QUEUED
        assert session.executor_spawned is True

        # Stream progress started + frontend told to open a live subscription.
        sm.start_stream.assert_awaited_once()
        ws.broadcast_to_user.assert_awaited_once()
        event = ws.broadcast_to_user.await_args.args[1]
        assert event["type"] == "executor.stream_started"
        assert event["stream_id"] == run.stream_id
        assert event["task_id"] == "task-7"

    async def test_workflow_context_survives_the_queue(self) -> None:
        item = _queue_item(
            configurable={
                "user_id": "u1",
                "workflow_id": "wf-1",
                "workflow_title": "Digest",
                "workflow_notify_on_completion": False,
            }
        )
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.lpop = AsyncMock(return_value=item)
            redis.client.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await pop_next_queued_run("conv-1")

        assert prepared is not None
        assert prepared.run.workflow_id == "wf-1"
        assert prepared.run.workflow_notify_on_completion is False
        assert prepared.run.executor_owns_tool_data is True


@pytest.mark.unit
class TestLockOwnership:
    """The ownership contract behind safe finalize handoffs (BUG C fix)."""

    async def test_matching_value_is_ours(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("s1", "t1"))
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.OURS

    async def test_missing_lock_is_free(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=None)
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.FREE

    async def test_other_value_is_foreign(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("other", "t9"))
            assert await get_lock_state("conv-1", "s1", "t1") is LockState.FOREIGN

    async def test_release_deletes_only_when_owned(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("s1", "t1"))
            redis.delete = AsyncMock()
            await release_lock_if_owned("conv-1", "s1", "t1")
            redis.delete.assert_awaited_once()

    async def test_release_never_deletes_a_foreign_lock(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.get = AsyncMock(return_value=build_lock_value("other", "t9"))
            redis.delete = AsyncMock()
            await release_lock_if_owned("conv-1", "s1", "t1")
            redis.delete.assert_not_awaited()


@pytest.mark.unit
class TestReclaimStrandedTask:
    """The post-release recheck that closes the strand window (BUG A fix)."""

    async def test_empty_queue_reclaims_nothing(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.llen = AsyncMock(return_value=0)
            redis.client.set = AsyncMock()
            assert await reclaim_stranded_task("conv-1") is None
            redis.client.set.assert_not_awaited()  # never touches the lock

    async def test_lost_nx_claim_backs_off(self) -> None:
        """A concurrent call_executor acquired the lock first — its finalize
        will drain the queue, so reclaim must yield rather than trample."""
        with patch.object(eq, "redis_cache") as redis:
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=None)  # NX lost
            assert await reclaim_stranded_task("conv-1") is None

    async def test_won_claim_pops_and_returns_the_stranded_task(self) -> None:
        sentinel = object()
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(
                eq, "pop_next_queued_run", new_callable=AsyncMock, return_value=sentinel
            ) as pop,
        ):
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=True)  # NX won
            assert await reclaim_stranded_task("conv-1") is sentinel
            pop.assert_awaited_once_with("conv-1")

    async def test_won_claim_with_raced_empty_queue_frees_the_sentinel(self) -> None:
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "pop_next_queued_run", new_callable=AsyncMock, return_value=None),
        ):
            redis.client.llen = AsyncMock(return_value=1)
            redis.client.set = AsyncMock(return_value=True)
            redis.delete = AsyncMock()
            assert await reclaim_stranded_task("conv-1") is None
            redis.delete.assert_awaited_once()  # don't block call_executor


@pytest.mark.unit
class TestEnqueueTask:
    async def test_serializes_scalars_and_drops_unsafe_values(self) -> None:
        with patch.object(eq, "redis_cache") as redis:
            redis.client.rpush = AsyncMock()
            redis.client.expire = AsyncMock()

            await enqueue_task(
                queue_key="executor:queue:conv-1",
                task="do it",
                task_id="task-1",
                configurable={
                    "user_id": "u1",
                    "workflow_id": "wf-1",
                    "not_allowlisted": "dropped",
                    "user_message_id": {"nested": "dropped — not a scalar"},
                },
                conversation_id="conv-1",
                user_message_id="msg-1",
            )

            payload = json.loads(redis.client.rpush.await_args.args[1])
            assert payload["task"] == "do it"
            assert payload["configurable"] == {"user_id": "u1", "workflow_id": "wf-1"}
            assert payload["user_message_id"] == "msg-1"
            redis.client.expire.assert_awaited_once_with(
                "executor:queue:conv-1", EXECUTOR_QUEUE_TTL
            )
