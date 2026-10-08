"""Unit tests for executor_status_hook (app.agents.core.nodes.executor_status).

Pins the live-executor status frame AND the fix for it leaking into result
narration: when comms silently re-voices a finished executor result, that task's
busy lock is still held (the runner frees it just after delivery), so the hook
must NOT inject a "STILL RUNNING" frame into the narration of that very result.
Doing so contradicts the result being delivered and made the reasoning model
return an empty narration, which then fell back to the raw executor text leaking
to the user.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME, EXECUTOR_STATUS_MARKER
from app.agents.core.background.executor_queue import build_lock_value
from app.agents.core.nodes.executor_status import executor_status_hook

MODULE = "app.agents.core.nodes.executor_status"


def _config(thread_id: str = "conv-1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _narration_config() -> dict:
    return {"configurable": {"thread_id": "conv-1", "is_result_narration": True}}


def _redis_holding(lock_value: str) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=lock_value)
    cache = MagicMock()
    cache.client = client
    return cache


async def test_injects_status_when_lock_held_on_interactive_turn() -> None:
    state = {"messages": [HumanMessage(content="did that finish?")]}
    cache = _redis_holding(build_lock_value("s1", "task-123"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    msgs = out["messages"]
    assert len(msgs) == len(state["messages"]) + 1
    injected = msgs[-1]
    assert injected.additional_kwargs.get(EXECUTOR_STATUS_MARKER) is True
    assert "STILL" in injected.content
    assert "task-123" in injected.content


async def test_injects_status_when_state_has_no_messages_key() -> None:
    # Missing "messages" must default to [], not None, or the [*messages, status]
    # spread raises and the hook's own except swallows it into a silent no-op.
    state: dict = {}
    cache = _redis_holding(build_lock_value("s1", "task-9"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    msgs = out.get("messages")
    assert msgs is not None and len(msgs) == 1
    assert msgs[0].additional_kwargs.get(EXECUTOR_STATUS_MARKER) is True
    assert "task-9" in msgs[0].content


async def test_skips_status_during_result_narration() -> None:
    # The narration trigger (name=BACKGROUND_EXECUTOR_NAME) on a run stamped
    # is_result_narration, with the same task's lock still held: the hook must skip
    # before it ever reads the lock, leaving the narration state untouched.
    state = {
        "messages": [
            HumanMessage(
                content="<executor_result>Reminder created</executor_result>",
                name=BACKGROUND_EXECUTOR_NAME,
            )
        ]
    }
    cache = _redis_holding(build_lock_value("s1", "task-123"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _narration_config(), MagicMock())

    assert out["messages"] == state["messages"]
    cache.client.get.assert_not_awaited()


@pytest.mark.regression
async def test_a_narration_run_stays_quiet_after_it_calls_a_tool() -> None:
    # Mid-narration the latest message is the tool's result, not the trigger; the
    # run's flag alone must still keep "STILL RUNNING" out of it.
    state = {
        "messages": [
            HumanMessage(
                content="<executor_result>Done</executor_result>", name=BACKGROUND_EXECUTOR_NAME
            ),
            AIMessage(content="", tool_calls=[{"name": "lookup", "args": {}, "id": "c1"}]),
            ToolMessage(content="looked up", tool_call_id="c1"),
        ]
    }
    cache = _redis_holding(build_lock_value("s1", "task-123"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _narration_config(), MagicMock())

    assert out["messages"] == state["messages"]


async def test_a_later_turn_still_learns_of_a_live_run_after_an_earlier_result_was_narrated() -> (
    None
):
    # Narration triggers persist in the conversation's thread; a new user turn while
    # a second executor runs must still get the status frame.
    state = {
        "messages": [
            HumanMessage(
                content="<executor_result>Done</executor_result>", name=BACKGROUND_EXECUTOR_NAME
            ),
            AIMessage(content="All done."),
            HumanMessage(content="and the other task, did it finish?"),
        ]
    }
    cache = _redis_holding(build_lock_value("s2", "task-456"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    assert out["messages"][-1].additional_kwargs.get(EXECUTOR_STATUS_MARKER) is True
    assert "task-456" in out["messages"][-1].content


async def test_no_status_when_no_lock_held() -> None:
    state = {"messages": [HumanMessage(content="what's up")]}
    cache = _redis_holding(lock_value=None)  # get() returns None -> lock free
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    assert out["messages"] == state["messages"]


async def test_status_frame_forbids_claiming_completion_or_redispatching() -> None:
    """Pin the running-task rule: results are not in, so claim nothing and never re-dispatch."""
    state = {"messages": [HumanMessage(content="did that finish?")]}
    cache = _redis_holding(build_lock_value("s1", "task-123"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    assert (
        "Its results have not arrived yet. Do not claim it finished, and do not "
        "dispatch the same task again." in out["messages"][-1].content
    )
