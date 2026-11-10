"""Every writer of a comms LangGraph thread takes the conversation's lock first.

The graph runs here are real: a LangGraph StateGraph over the in-memory checkpointer.
A run reads the thread's checkpoint when it starts and writes its own on the way out,
so an out-of-band write landing in between forks the checkpoint and the run's write
buries it. Only the Redis lease is faked (in process, same token-and-timeout contract
as redis-py's Lock), because the lease's own behaviour is DistributedLock's to prove.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
import pytest

from app.agents.core import thread_lock
from app.agents.core.agent import call_agent
from app.agents.core.background.comms_narrator import (
    narrate_executor_result,
    record_exchange_in_thread,
    record_executor_cancellation,
    record_executor_report,
    record_platform_delivery,
)
from app.agents.core.thread_lock import CommsThreadLockTimeout, comms_thread_lock
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

CONVERSATION_ID = "conv-lock-1"
NARRATOR = "app.agents.core.background.comms_narrator"
REPLY = "the report is ready"
DELIVERED = "[Delivered to the user]: the invoice is paid"
USER = AuthenticatedUser(user_id="6812f0b3c9a14e2b7d5a91cc", email="u@gaia.local")
THREAD: RunnableConfig = {"configurable": {"thread_id": CONVERSATION_ID}}
SETTLE_SECONDS = 0.05
SHORT_ACQUIRE_SECONDS = 0.05


class _InProcessLock:
    """redis-py's Lock contract on one asyncio.Lock: bounded blocking acquire, owner-checked release."""

    def __init__(self, held: asyncio.Lock, blocking_timeout: float | None) -> None:
        self._held = held
        self._blocking_timeout = blocking_timeout
        self._owns = False

    async def acquire(self) -> bool:
        try:
            await asyncio.wait_for(self._held.acquire(), self._blocking_timeout)
        except TimeoutError:
            return False
        self._owns = True
        return True

    async def extend(self, additional_time: float, replace_ttl: bool = False) -> bool:
        return self._owns

    async def release(self) -> None:
        if self._owns:
            self._owns = False
            self._held.release()


class _InProcessRedis:
    """The hermetic redis client with named locks that really exclude, in process."""

    def __init__(self, rest: object) -> None:
        self._rest = rest
        self._locks: dict[str, asyncio.Lock] = {}

    def __getattr__(self, name: str) -> object:
        return getattr(self._rest, name)

    def lock(
        self,
        name: str,
        *,
        timeout: float,
        blocking_timeout: float | None,
        thread_local: bool,
    ) -> _InProcessLock:
        return _InProcessLock(self._locks.setdefault(name, asyncio.Lock()), blocking_timeout)


class _ThreadState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


class _CommsThread:
    """A comms graph whose model call can be held open, over the in-memory checkpointer."""

    def __init__(self) -> None:
        self.model_call_started = asyncio.Event()
        self.finish_model_call = asyncio.Event()
        builder = StateGraph(_ThreadState)
        builder.add_node("agent", self._agent)
        # Out-of-band writes are attributed to "tools", as in the production graph.
        builder.add_node("tools", self._tools)
        builder.add_edge(START, "agent")
        builder.add_edge("agent", END)
        builder.add_edge("tools", END)
        self.graph = builder.compile(checkpointer=InMemorySaver())

    async def _agent(self, state: _ThreadState) -> dict[str, list[AIMessage]]:
        self.model_call_started.set()
        await self.finish_model_call.wait()
        return {"messages": [AIMessage(content=REPLY)]}

    async def _tools(self, state: _ThreadState) -> dict[str, list[AnyMessage]]:
        return {"messages": []}

    async def contents(self) -> list[str]:
        state = await self.graph.aget_state(THREAD)
        return [str(message.content) for message in state.values["messages"]]


@pytest.fixture
def comms_thread() -> Iterator[_CommsThread]:
    thread = _CommsThread()
    with patch(f"{NARRATOR}.GraphManager.get_graph", AsyncMock(return_value=thread.graph)):
        yield thread


@pytest.fixture(autouse=True)
def in_process_redis(monkeypatch: pytest.MonkeyPatch) -> _InProcessRedis:
    client = _InProcessRedis(redis_cache.redis)
    monkeypatch.setattr(redis_cache, "redis", client)
    return client


async def _narration_run_started(comms_thread: _CommsThread) -> asyncio.Task[str]:
    """Start a narration run (a real comms graph run) and wait until its model call is in flight."""
    run = asyncio.create_task(
        narrate_executor_result("done", "result", CONVERSATION_ID, USER, preamble="")
    )
    await asyncio.wait_for(comms_thread.model_call_started.wait(), timeout=5)
    return run


async def _finish_with_write_in_flight(
    comms_thread: _CommsThread, run: asyncio.Task[str], write: asyncio.Task[None]
) -> None:
    """Let the write try to land while the run is mid-flight, then let the run finish."""
    await asyncio.sleep(SETTLE_SECONDS)
    comms_thread.finish_model_call.set()
    await asyncio.gather(run, write)


class TestNoWriteIsLostToAConcurrentRun:
    async def test_a_platform_delivery_record_during_a_narration_run_survives(
        self, comms_thread: _CommsThread
    ) -> None:
        run = await _narration_run_started(comms_thread)
        write = asyncio.create_task(record_platform_delivery(CONVERSATION_ID, DELIVERED))

        await _finish_with_write_in_flight(comms_thread, run, write)

        assert DELIVERED in await comms_thread.contents()
        assert REPLY in await comms_thread.contents()

    async def test_an_executor_report_record_during_a_narration_run_survives(
        self, comms_thread: _CommsThread
    ) -> None:
        run = await _narration_run_started(comms_thread)
        write = asyncio.create_task(
            record_executor_report(CONVERSATION_ID, "found 3 files", "result")
        )

        await _finish_with_write_in_flight(comms_thread, run, write)

        assert any("found 3 files" in content for content in await comms_thread.contents())

    async def test_a_cancellation_record_during_a_narration_run_survives(
        self, comms_thread: _CommsThread
    ) -> None:
        run = await _narration_run_started(comms_thread)
        write = asyncio.create_task(
            record_executor_cancellation(CONVERSATION_ID, "task-9", "send the report")
        )

        await _finish_with_write_in_flight(comms_thread, run, write)

        assert any("send the report" in content for content in await comms_thread.contents())

    async def test_an_exchange_record_during_a_narration_run_survives(
        self, comms_thread: _CommsThread
    ) -> None:
        run = await _narration_run_started(comms_thread)
        write = asyncio.create_task(
            record_exchange_in_thread(CONVERSATION_ID, "cancel it", "Cancelled.")
        )

        await _finish_with_write_in_flight(comms_thread, run, write)

        contents = await comms_thread.contents()
        assert "cancel it" in contents
        assert "Cancelled." in contents

    async def test_a_write_during_an_interactive_turn_survives(
        self, comms_thread: _CommsThread
    ) -> None:
        config: dict[str, Any] = {
            "agent_name": "comms_agent",
            "configurable": {"thread_id": CONVERSATION_ID, "user_id": USER.user_id},
        }
        initial_state = {"messages": [HumanMessage(content="hello")]}
        request = MessageRequestWithHistory.model_validate(
            {"message": "hello", "messages": [{"role": "user", "content": "hello"}]}
        )

        async def _turn() -> list[str]:
            with patch(
                "app.agents.core.agent._core_agent_logic",
                AsyncMock(return_value=(comms_thread.graph, initial_state, config)),
            ):
                return [frame async for frame in call_agent(request, CONVERSATION_ID, USER)]

        turn = asyncio.create_task(_turn())
        await asyncio.wait_for(comms_thread.model_call_started.wait(), timeout=5)
        write = asyncio.create_task(record_platform_delivery(CONVERSATION_ID, DELIVERED))
        await asyncio.sleep(SETTLE_SECONDS)
        comms_thread.finish_model_call.set()
        await asyncio.gather(turn, write)

        assert DELIVERED in await comms_thread.contents()
        assert REPLY in await comms_thread.contents()


class TestTheLockIsPerConversation:
    async def test_a_write_to_another_conversation_does_not_wait_for_the_run(
        self, comms_thread: _CommsThread
    ) -> None:
        run = await _narration_run_started(comms_thread)

        await asyncio.wait_for(record_platform_delivery("conv-other", DELIVERED), timeout=1)

        comms_thread.finish_model_call.set()
        await run


class TestAWriterThatCannotGetTheLockFailsLoud:
    @pytest.fixture
    def short_wait(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            thread_lock, "COMMS_THREAD_LOCK_ACQUIRE_TIMEOUT_SECONDS", SHORT_ACQUIRE_SECONDS
        )

    @pytest.fixture
    async def held_elsewhere(self) -> AsyncIterator[None]:
        async with comms_thread_lock(CONVERSATION_ID):
            yield

    async def test_a_recorder_raises_and_never_writes_unlocked(
        self, comms_thread: _CommsThread, short_wait: None, held_elsewhere: None
    ) -> None:
        async with captured_wide_event() as event:
            with pytest.raises(CommsThreadLockTimeout):
                await record_platform_delivery(CONVERSATION_ID, DELIVERED)

        (error,) = event["errors"]
        assert error["msg"] == f"{LogTag.LOCK} Comms thread lock not acquired"
        assert error["conversation_id"] == CONVERSATION_ID
        assert (await comms_thread.graph.aget_state(THREAD)).values == {}

    async def test_the_interactive_turn_raises_instead_of_running_unlocked(
        self, comms_thread: _CommsThread, short_wait: None, held_elsewhere: None
    ) -> None:
        config: dict[str, Any] = {
            "agent_name": "comms_agent",
            "configurable": {"thread_id": CONVERSATION_ID, "user_id": USER.user_id},
        }
        request = MessageRequestWithHistory.model_validate(
            {"message": "hello", "messages": [{"role": "user", "content": "hello"}]}
        )
        comms_thread.finish_model_call.set()
        with (
            patch(
                "app.agents.core.agent._core_agent_logic",
                AsyncMock(
                    return_value=(
                        comms_thread.graph,
                        {"messages": [HumanMessage(content="hello")]},
                        config,
                    )
                ),
            ),
            pytest.raises(CommsThreadLockTimeout),
        ):
            [frame async for frame in call_agent(request, CONVERSATION_ID, USER)]

        assert not comms_thread.model_call_started.is_set()
