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
    build_lock_value,
    enqueue_task,
    parse_lock_value,
    pop_next_queued_run,
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
            redis.set = AsyncMock()
            assert await pop_next_queued_run("conv-1") is None
            redis.set.assert_not_awaited()

    async def test_valid_item_prepares_run_and_overwrites_lock(self) -> None:
        with (
            patch.object(eq, "redis_cache") as redis,
            patch.object(eq, "StreamManager") as sm,
            patch.object(eq, "websocket_manager") as ws,
        ):
            redis.client.lpop = AsyncMock(return_value=_queue_item())
            redis.set = AsyncMock()
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

        # Lock overwritten with the new run's value BEFORE returning.
        redis.set.assert_awaited_once()
        args, kwargs = redis.set.await_args
        assert args[0] == "executor:busy:conv-1"
        assert args[1] == build_lock_value(run.stream_id, "task-7")
        assert kwargs["ttl"] == EXECUTOR_BUSY_TTL

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
            redis.set = AsyncMock()
            sm.start_stream = AsyncMock()
            ws.broadcast_to_user = AsyncMock()

            prepared = await pop_next_queued_run("conv-1")

        assert prepared is not None
        assert prepared.run.workflow_id == "wf-1"
        assert prepared.run.workflow_notify_on_completion is False
        assert prepared.run.executor_owns_tool_data is True


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
