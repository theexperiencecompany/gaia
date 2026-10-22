"""Unit tests for executor_status_hook (app.agents.core.nodes.executor_status).

The frame is how comms knows whether its background work is really running. It
reads the busy lock, the holder's liveness and the background subagents over a
real (fake) Redis, so these tests pin the states the lock can actually be in:

* a live holder reads as running;
* a holder whose process died reads NOT running (it once read "STILL RUNNING"
  for the lock's whole 30-minute TTL, so a retry was answered "already on it");
* no holder after a dispatch reads "nothing is running", so a stale
  hand-off in history is never taken as live work;
* result narration stays quiet (the narrated run still holds the lock).
"""

from unittest.mock import MagicMock

import fakeredis.aioredis
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME, EXECUTOR_STATUS_MARKER
from app.agents.core.background.executor_queue import build_lock_value, hold_run_alive
from app.agents.core.background.running_registry import RunningSubagents
from app.agents.core.nodes.executor_status import executor_status_hook
from app.constants.cache import (
    EXECUTOR_BUSY_PREFIX,
    EXECUTOR_BUSY_TTL,
    EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS,
)
from app.constants.general import CALL_EXECUTOR_NAME
from app.models.agent_models import RunningSubagent

CONV = "conv-1"
#: What call_executor answers a hand-off with; literal so this file runs on any revision.
_HANDOFF = "Handed to the executor (task_id: {task_id})."
LOCK_KEY = f"{EXECUTOR_BUSY_PREFIX}{CONV}"


def _config() -> dict:
    return {"configurable": {"thread_id": CONV}}


def _narration_config() -> dict:
    return {"configurable": {"thread_id": CONV, "is_result_narration": True}}


def _dispatched_thread() -> list:
    return [
        HumanMessage(content="archive the promo emails"),
        AIMessage(content="", tool_calls=[{"name": CALL_EXECUTOR_NAME, "args": {}, "id": "c1"}]),
        ToolMessage(content=_HANDOFF.format(task_id="task-1"), tool_call_id="c1"),
        AIMessage(content="on it"),
        HumanMessage(content="did that go through?"),
    ]


async def _hold_live_lock(client: fakeredis.aioredis.FakeRedis, task_id: str) -> None:
    value = build_lock_value("s1", task_id)
    await client.set(LOCK_KEY, value, ex=EXECUTOR_BUSY_TTL)
    await hold_run_alive(CONV, value)


async def _hold_dead_lock(client: fakeredis.aioredis.FakeRedis, task_id: str) -> None:
    """Hold a lock older than a holder takes to start renewing, with no liveness: its process died."""
    age = EXECUTOR_DEAD_HOLDER_MIN_AGE_SECONDS + 5
    await client.set(LOCK_KEY, build_lock_value("s1", task_id), ex=EXECUTOR_BUSY_TTL - age)


async def _frame(messages: list, config: dict | None = None) -> str | None:
    out = await executor_status_hook({"messages": messages}, config or _config(), MagicMock())
    added = out["messages"][len(messages) :]
    if not added:
        return None
    assert len(added) == 1
    assert added[0].additional_kwargs.get(EXECUTOR_STATUS_MARKER) is True
    return str(added[0].content)


async def test_a_live_run_reads_as_running(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await _hold_live_lock(fake_redis, "task-123")

    frame = await _frame([HumanMessage(content="did that finish?")])

    assert frame is not None
    assert "running right now (task_id: task-123)" in frame
    assert "has not arrived" in frame


@pytest.mark.regression
async def test_a_dead_holder_reads_as_not_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_dead_lock(fake_redis, "task-7")

    frame = await _frame(_dispatched_thread())

    assert frame is not None
    assert "No background work is running" in frame
    assert "task-7" in frame
    assert "stopped before it finished" in frame


@pytest.mark.regression
async def test_a_dispatch_with_no_run_left_reads_as_nothing_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    frame = await _frame(_dispatched_thread())

    assert frame is not None
    assert "No background work is running right now" in frame


async def test_every_frame_states_facts_and_leaves_the_call_to_comms(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # The comms prompt explains how call_executor behaves; the frame only says what is true now.
    idle = await _frame(_dispatched_thread())
    await _hold_dead_lock(fake_redis, "task-1")
    dead = await _frame(_dispatched_thread())
    await _hold_live_lock(fake_redis, "task-1")
    running = await _frame(_dispatched_thread())

    for frame in (idle, dead, running):
        assert frame is not None
        assert "do not" not in frame.lower()
        assert "call_executor" not in frame


async def test_background_subagents_still_working_read_as_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await RunningSubagents(CONV).claim(
        RunningSubagent(
            subagent_id="sa-1",
            subagent_thread_id="t-1",
            integration_id="gmail",
            agent_name="gmail_agent",
            task_summary="archive promos",
            started_at="2026-10-12T10:00:00+00:00",
            stream_id="s-sub",
            dispatched_by="s1",
        )
    )

    frame = await _frame(_dispatched_thread())

    assert frame is not None
    assert "Background work is running right now" in frame


async def test_a_chat_that_never_handed_work_off_gets_no_frame(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await _frame([HumanMessage(content="what's up")]) is None


async def test_a_live_run_is_framed_even_before_this_thread_dispatched(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # A workflow or subagent landing can start a run this comms thread never dispatched.
    await _hold_live_lock(fake_redis, "task-9")

    frame = await _frame([])

    assert frame is not None
    assert "task-9" in frame


async def test_skips_status_during_result_narration(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_live_lock(fake_redis, "task-123")
    messages = [
        HumanMessage(
            content="<executor_result>Reminder created</executor_result>",
            name=BACKGROUND_EXECUTOR_NAME,
        )
    ]

    assert await _frame(messages, _narration_config()) is None


@pytest.mark.regression
async def test_a_narration_run_stays_quiet_after_it_calls_a_tool(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # Mid-narration the latest message is the tool's result, not the trigger; the
    # run's flag alone must still keep the status frame out of it.
    await _hold_live_lock(fake_redis, "task-123")
    messages = [
        HumanMessage(
            content="<executor_result>Done</executor_result>", name=BACKGROUND_EXECUTOR_NAME
        ),
        AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "c1"}]),
        ToolMessage(content="looked up", tool_call_id="c1"),
    ]

    assert await _frame(messages, _narration_config()) is None


async def test_a_later_turn_still_learns_of_a_live_run_after_an_earlier_result_was_narrated(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    # Narration triggers persist in the conversation's thread; a new user turn while
    # a second executor runs must still get the status frame.
    await _hold_live_lock(fake_redis, "task-456")
    messages = [
        HumanMessage(
            content="<executor_result>Done</executor_result>", name=BACKGROUND_EXECUTOR_NAME
        ),
        AIMessage(content="All done."),
        HumanMessage(content="and the other task, did it finish?"),
    ]

    frame = await _frame(messages)

    assert frame is not None
    assert "task-456" in frame


# ── The hand-off itself carries its live state ───────────────────────


async def _sent(messages: list, config: dict | None = None) -> list:
    out = await executor_status_hook({"messages": messages}, config or _config(), MagicMock())
    return out["messages"]


def _handoff_of(messages: list) -> str:
    return next(str(m.content) for m in messages if isinstance(m, ToolMessage))


@pytest.mark.regression
async def test_an_ended_handoff_no_longer_reads_as_pending(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """The hand-off near the user's message out-voted the note at the top: "already on it"."""
    handoff = _handoff_of(await _sent(_dispatched_thread()))

    assert handoff.endswith(
        "[Status now: ended, but its result never reached this chat. What it did is in "
        "the executor's own history, so call_executor can find out.]"
    )


@pytest.mark.regression
async def test_a_dead_runs_handoff_says_it_stopped(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_dead_lock(fake_redis, "task-1")

    handoff = _handoff_of(await _sent(_dispatched_thread()))

    assert handoff.endswith(
        "[Status now: ended. It stopped before it finished and delivered no result.]"
    )


async def test_a_running_handoff_says_so(fake_redis: fakeredis.aioredis.FakeRedis) -> None:
    await _hold_live_lock(fake_redis, "task-1")

    handoff = _handoff_of(await _sent(_dispatched_thread()))

    assert (
        "[Status now: still running. Anything the user adds to it goes through call_executor"
        in handoff
    )


async def test_an_answered_handoff_is_left_as_it_was(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    thread = [
        *_dispatched_thread()[:3],
        HumanMessage(
            content="<executor_result>Archived 12</executor_result>", name=BACKGROUND_EXECUTOR_NAME
        ),
        AIMessage(content="Archived 12."),
        HumanMessage(content="thanks"),
    ]

    assert _handoff_of(await _sent(thread)) == _handoff_of(thread)


async def test_only_the_latest_open_handoff_is_annotated(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    older = _dispatched_thread()[:3]
    thread = [
        *older,
        HumanMessage(
            content="<executor_result>done</executor_result>", name=BACKGROUND_EXECUTOR_NAME
        ),
        HumanMessage(content="now archive the newsletters"),
        AIMessage(content="", tool_calls=[{"name": CALL_EXECUTOR_NAME, "args": {}, "id": "c2"}]),
        ToolMessage(content=_HANDOFF.format(task_id="task-2"), tool_call_id="c2"),
    ]

    sent = await _sent(thread)
    handoffs = [str(m.content) for m in sent if isinstance(m, ToolMessage)]

    assert "Status now" not in handoffs[0]
    assert handoffs[1].endswith(
        "[Status now: ended, but its result never reached this chat. What it did is in "
        "the executor's own history, so call_executor can find out.]"
    )


async def test_the_checkpointed_thread_is_never_changed(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    thread = _dispatched_thread()
    before = [m.model_copy() for m in thread]

    await _sent(thread)

    assert [m.content for m in thread] == [m.content for m in before]


async def test_narration_leaves_the_handoff_alone(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    thread = _dispatched_thread()

    sent = await _sent(thread, _narration_config())

    assert _handoff_of(sent) == _handoff_of(thread)


async def test_the_idle_frame_says_every_handoff_has_ended(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    assert await _frame(_dispatched_thread()) == (
        "No background work is running right now. Every earlier hand-off in this chat has "
        "finished or stopped, even one whose result you have not seen."
    )


async def test_a_holder_without_a_task_id_is_named_unknown(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await _hold_live_lock(fake_redis, "")

    frame = await _frame(_dispatched_thread())

    assert frame is not None
    assert "(task_id: unknown)" in frame


async def test_subagents_still_working_mark_the_handoff_running(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    await RunningSubagents(CONV).claim(
        RunningSubagent(
            subagent_id="sa-2",
            subagent_thread_id="t-2",
            integration_id="gmail",
            agent_name="gmail_agent",
            task_summary="archive",
            started_at="2026-10-12T10:00:00+00:00",
            stream_id="s-sub",
            dispatched_by="s1",
        )
    )

    handoff = _handoff_of(await _sent(_dispatched_thread()))

    assert "[Status now: still running." in handoff
