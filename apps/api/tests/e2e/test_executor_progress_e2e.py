"""A real executor run's progress, as comms sees it mid-run, and gone once it ends.

The run is the real one: run_executor_background on the REAL compiled executor
graph (only the model is scripted), the real stream writer, keep-alive beat,
finalize and lock release, over fakeredis. The model is gated on its second
call, which holds the run mid-flight right after it planned and called a tool;
comms' real status hook is read at that moment.

Not exercised: delivery of the result to the conversation (deliver_result is
doubled, it has its own suite) and a real LLM choosing these calls.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import PrivateAttr
import pytest

from app.agents.core.background import executor_runner as er
from app.agents.core.background.executor_progress import progress_key
from app.agents.core.background.executor_queue import build_lock_value
from app.agents.core.background.session import ExecutorRun, RunKind, create_session
from app.agents.core.nodes.executor_status import executor_status_hook
from app.agents.core.subagents.subagent_runner import SubagentExecutionContext
from app.constants.cache import EXECUTOR_BUSY_PREFIX, EXECUTOR_BUSY_TTL
from app.constants.general import CALL_EXECUTOR_NAME, EXECUTOR_THREAD_PREFIX
from app.models.user_models import AuthenticatedUser
from tests.e2e._harness.graph_run import RecordingFakeModel, call, executor_graph

CONV = "conv-progress"
STREAM = "stream-progress"
TASK_ID = "task-progress"
USER_ID = "507f1f77bcf86cd799439011"
HOLDER = build_lock_value(STREAM, TASK_ID)
LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONV}"
WAIT_S = 20


class GatedModel(RecordingFakeModel):
    """Answers its first call at once, then holds every later one until released."""

    _reached: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _release: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)

    async def _agenerate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        if self._prompts:
            self._reached.set()
            await self._release.wait()
        return await super()._agenerate(messages, *args, **kwargs)


def _model() -> GatedModel:
    first = AIMessage(
        content="",
        tool_calls=[
            call(
                "plan_tasks",
                {
                    "tasks": [
                        {"content": "Find this week's promo emails"},
                        {"content": "Archive them"},
                    ]
                },
                call_id="p1",
            ),
            call("get_tool_schema", {"tool_name": "GMAIL_FETCH_EMAILS"}, call_id="t1"),
        ],
    )
    return GatedModel(
        responses=[first, AIMessage(content="Archived 12 promo emails.")],
        profile={"max_input_tokens": 1_000_000},
    )


def _context(graph: Any) -> SubagentExecutionContext:
    configurable: dict[str, Any] = {
        "thread_id": f"{EXECUTOR_THREAD_PREFIX}{CONV}",
        "conversation_id": CONV,
        "user_id": USER_ID,
    }
    return SubagentExecutionContext(
        subagent_graph=graph,
        agent_name="executor_agent",
        config={"configurable": dict(configurable), "recursion_limit": 50},  # type: ignore[typeddict-item]
        configurable=configurable,  # type: ignore[typeddict-item]
        integration_id="executor",
        initial_state={"messages": [HumanMessage(content="archive this week's promo emails")]},  # type: ignore[typeddict-item]
        user_id=USER_ID,
        stream_id=STREAM,
    )


async def _comms_status() -> str | None:
    """Return the status frame comms' next turn would get: the real hook on a thread that handed off."""
    messages = [
        HumanMessage(content="archive this week's promo emails"),
        AIMessage(content="", tool_calls=[{"name": CALL_EXECUTOR_NAME, "args": {}, "id": "c1"}]),
        ToolMessage(content="Handed to the executor.", tool_call_id="c1"),
        HumanMessage(content="how's it going?"),
    ]
    out = await executor_status_hook(
        {"messages": messages}, {"configurable": {"thread_id": CONV}}, MagicMock()
    )
    added = out["messages"][len(messages) :]
    return str(added[0].content) if added else None


@pytest.fixture
async def running() -> AsyncIterator[tuple[GatedModel, asyncio.Task[None]]]:
    model = _model()
    async with executor_graph([], model=model) as graph:
        run = ExecutorRun(
            stream_id=STREAM,
            conversation_id=CONV,
            user=AuthenticatedUser(user_id=USER_ID),
            kind=RunKind.LIVE,
            task_id=TASK_ID,
            user_message_id=None,
        )
        create_session(STREAM, RunKind.LIVE)
        with (
            patch("app.services.analytics_service.capture"),
            patch.object(
                er, "prepare_executor_execution", AsyncMock(return_value=(_context(graph), None))
            ),
            patch.object(er, "deliver_result", AsyncMock(return_value=(None, None))),
        ):
            task = asyncio.create_task(
                er.run_executor_background(run, "archive promos", {"user_id": USER_ID})
            )
            try:
                await asyncio.wait_for(model._reached.wait(), WAIT_S)
                yield model, task
            finally:
                model._release.set()
                await asyncio.wait_for(task, WAIT_S)


async def test_mid_run_comms_sees_the_plan_and_the_calls_with_their_inputs(
    fake_redis: fakeredis.aioredis.FakeRedis,
    running: tuple[GatedModel, asyncio.Task[None]],
) -> None:
    # call_executor's acquire, which the fixture's run would otherwise not have.
    await fake_redis.set(LOCK_KEY, HOLDER, ex=EXECUTOR_BUSY_TTL)

    frame = await _comms_status()

    assert frame is not None
    assert f"running right now (task_id: {TASK_ID})" in frame
    assert "Plan (executor):" in frame
    assert "- [in_progress] Find this week's promo emails" in frame
    assert "- [pending] Archive them" in frame
    assert 'get_tool_schema(tool_name="GMAIL_FETCH_EMAILS")' in frame
    # The plan is shown as the plan, never as a call.
    assert "plan_tasks(" not in frame


async def test_once_the_run_ends_its_progress_is_gone(
    fake_redis: fakeredis.aioredis.FakeRedis,
    running: tuple[GatedModel, asyncio.Task[None]],
) -> None:
    await fake_redis.set(LOCK_KEY, HOLDER, ex=EXECUTOR_BUSY_TTL)
    model, task = running
    assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 1

    model._release.set()
    await asyncio.wait_for(task, WAIT_S)

    assert await fake_redis.get(LOCK_KEY) is None
    assert await fake_redis.exists(progress_key(CONV, HOLDER)) == 0
    frame = await _comms_status()
    assert frame is not None
    assert "No background work is running right now" in frame
    assert "get_tool_schema" not in frame
