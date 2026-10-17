"""Behavior tests for app.agents.core.background.thread_record.

A message that bypassed the comms graph must still land in the thread the next
turn reads: the comms graph's checkpoint, written as the tools node.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from langchain_core.messages import AIMessage, HumanMessage
import pytest

from app.agents.core.background.thread_record import (
    record_exchange_in_thread,
    record_platform_delivery,
)
from app.constants.cache import EXECUTOR_BUSY_PREFIX
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    PROACTIVE_RECORD_JOB_PREFIX,
    PROACTIVE_RECORD_RETRY_DELAY,
    PROACTIVE_RECORD_TASK,
)
from tests.helpers import captured_wide_event

# Real SET NX / WATCH semantics for the executor busy lock the write takes.
pytestmark = pytest.mark.usefixtures("fake_redis")

MODULE = "app.agents.core.background.thread_record"
CONVERSATION_ID = "conv-1"
POOL = MagicMock(name="arq-pool")


def _fake_comms_graph(*, interrupted: bool = False) -> MagicMock:
    graph = MagicMock()
    graph.aupdate_state = AsyncMock()
    task = MagicMock(interrupts=(MagicMock(),) if interrupted else ())
    graph.aget_state = AsyncMock(return_value=MagicMock(tasks=(task,)))
    return graph


def _patch_graph(graph: MagicMock) -> MagicMock:
    return patch(f"{MODULE}.GraphManager.get_graph", AsyncMock(return_value=graph))


class TestRecordPlatformDelivery:
    async def test_delivered_message_is_appended_to_the_checkpoint(self) -> None:
        graph = _fake_comms_graph()
        get_graph = AsyncMock(return_value=graph)
        with patch(f"{MODULE}.GraphManager.get_graph", get_graph):
            await record_platform_delivery(CONVERSATION_ID, "Report is ready. It has 3 pages.")

        # The comms graph specifically — a wrong graph writes into a thread
        # whose next turn would read a message it never sent.
        assert {call.args for call in get_graph.await_args_list} == {("comms_agent",)}
        graph.aupdate_state.assert_awaited_once()
        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        # as_node="tools": as "agent" makes aupdate_state evaluate should_continue,
        # which needs a store it cannot inject, so the write raises and is lost.
        assert call.kwargs["as_node"] == "tools"
        messages = call.args[1]["messages"]
        assert len(messages) == 1
        assert isinstance(messages[0], AIMessage)
        assert messages[0].content == "Report is ready. It has 3 pages."

    async def test_blank_text_is_a_no_op(self) -> None:
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_platform_delivery(CONVERSATION_ID, "   ")

        graph.aupdate_state.assert_not_called()

    async def test_failure_to_record_is_swallowed_and_reported_on_the_wide_event(self) -> None:
        """A checkpoint failure must not break the caller, but log.error must land in the wide event's errors[]."""
        graph = _fake_comms_graph()
        graph.aupdate_state = AsyncMock(side_effect=RuntimeError("checkpoint down"))
        with _patch_graph(graph):
            async with captured_wide_event() as event:
                await record_platform_delivery(CONVERSATION_ID, "hello")

        (error,) = [e for e in event["errors"] if "Failed to record" in e["msg"]]
        assert error["msg"] == (f"{LogTag.AGENT} Failed to record messages in conversation thread")
        assert error["conversation_id"] == CONVERSATION_ID
        assert error["error"] == "checkpoint down"
        assert error["error_type"] == "RuntimeError"


class TestProactiveWritesWaitForTheThread:
    """A proactive record never races a run or lands on a parked interrupt."""

    async def _record(
        self,
        graph: MagicMock,
        conversation_id: str = CONVERSATION_ID,
        text: str = "Digest is ready.",
    ) -> AsyncMock:
        enqueue = AsyncMock()
        with (
            _patch_graph(graph),
            patch(f"{MODULE}.enqueue_worker_job", enqueue),
            patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=POOL)),
        ):
            await record_platform_delivery(conversation_id, text)
        return enqueue

    async def test_the_state_read_is_of_this_conversations_thread(self) -> None:
        graph = _fake_comms_graph()
        await self._record(graph)

        graph.aget_state.assert_awaited_once_with({"configurable": {"thread_id": CONVERSATION_ID}})

    async def test_a_free_thread_is_written_now_and_its_lock_released(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        graph = _fake_comms_graph()
        enqueue = await self._record(graph)

        graph.aupdate_state.assert_awaited_once()
        enqueue.assert_not_awaited()
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION_ID}") is None

    async def test_a_running_executor_hands_the_write_to_a_retrying_job(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        lock = f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION_ID}"
        await fake_redis.set(lock, "stream-1:task-1")
        graph = _fake_comms_graph()
        enqueue = await self._record(graph)

        graph.aupdate_state.assert_not_awaited()
        (pool, task, conversation_id, text) = enqueue.await_args.args
        assert (pool, task, conversation_id, text) == (
            POOL,
            PROACTIVE_RECORD_TASK,
            CONVERSATION_ID,
            "Digest is ready.",
        )
        assert enqueue.await_args.kwargs["_defer_by"] == PROACTIVE_RECORD_RETRY_DELAY
        assert re.fullmatch(
            f"{PROACTIVE_RECORD_JOB_PREFIX}[0-9a-f]{{32}}", enqueue.await_args.kwargs["_job_id"]
        )
        # The run's lock is untouched.
        assert await fake_redis.get(lock) == "stream-1:task-1"

    async def test_a_pending_interrupt_defers_the_write_and_frees_the_lock(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        graph = _fake_comms_graph(interrupted=True)
        enqueue = await self._record(graph)

        graph.aupdate_state.assert_not_awaited()
        enqueue.assert_awaited_once()
        assert await fake_redis.get(f"{EXECUTOR_BUSY_PREFIX}{CONVERSATION_ID}") is None

    async def test_a_failed_state_read_is_retried_in_a_job_and_warned(self) -> None:
        graph = _fake_comms_graph()
        graph.aget_state = AsyncMock(side_effect=RuntimeError("checkpointer down"))
        async with captured_wide_event() as event:
            enqueue = await self._record(graph)

        enqueue.assert_awaited_once()
        (warning,) = event["warnings"]
        assert warning["msg"] == (
            f"{LogTag.AGENT} Recording a delivered message failed; retrying in a job"
        )
        assert warning["conversation_id"] == CONVERSATION_ID
        assert warning["error"] == "checkpointer down"

    async def test_one_retry_job_per_conversation_and_message(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        async def job_id(conversation_id: str, text: str) -> str:
            lock = f"{EXECUTOR_BUSY_PREFIX}{conversation_id}"
            await fake_redis.set(lock, "stream-1:task-1")
            enqueue = await self._record(_fake_comms_graph(), conversation_id, text)
            await fake_redis.delete(lock)
            return str(enqueue.await_args.kwargs["_job_id"])

        first = await job_id("conv-1", "Digest is ready.")
        assert await job_id("conv-1", "Digest is ready.") == first
        assert await job_id("conv-2", "Digest is ready.") != first
        assert await job_id("conv-1", "Invoice is due.") != first


class TestRecordExchangeInThread:
    async def test_the_user_message_and_reply_are_appended_in_order(self) -> None:
        """A reply that resolved a paused task never ran the graph; the thread must still hold both turns."""
        graph = _fake_comms_graph()
        with _patch_graph(graph):
            await record_exchange_in_thread(CONVERSATION_ID, "cancel that step", "Cancelled it.")

        call = graph.aupdate_state.await_args
        assert call.args[0] == {"configurable": {"thread_id": CONVERSATION_ID}}
        assert call.kwargs["as_node"] == "tools"
        user_turn, reply = call.args[1]["messages"]
        assert isinstance(user_turn, HumanMessage)
        assert user_turn.content == "cancel that step"
        assert isinstance(reply, AIMessage)
        assert reply.content == "Cancelled it."
