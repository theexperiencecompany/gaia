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

from langchain_core.messages import HumanMessage

from app.agents.context.slots import BACKGROUND_EXECUTOR_NAME, EXECUTOR_STATUS_MARKER
from app.agents.core.background.executor_queue import build_lock_value
from app.agents.core.nodes.executor_status import executor_status_hook

MODULE = "app.agents.core.nodes.executor_status"


def _config(thread_id: str = "conv-1") -> dict:
    return {"configurable": {"thread_id": thread_id}}


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
    # A state with no "messages" key must still get the status frame: the hook
    # defaults it to [] so the [*messages, status] spread stays a list. A None
    # default (the obvious mistake) makes that spread raise, which the hook's
    # own except would swallow into a silent no-op.
    state: dict = {}
    cache = _redis_holding(build_lock_value("s1", "task-9"))
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    msgs = out.get("messages")
    assert msgs is not None and len(msgs) == 1
    assert msgs[0].additional_kwargs.get(EXECUTOR_STATUS_MARKER) is True
    assert "task-9" in msgs[0].content


async def test_skips_status_during_result_narration() -> None:
    # The last message is the narration trigger (name=BACKGROUND_EXECUTOR_NAME) and
    # the same task's lock is still held; the hook must skip before it ever reads
    # the lock, leaving the narration state untouched.
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
        out = await executor_status_hook(state, _config(), MagicMock())

    assert out["messages"] == state["messages"]
    cache.client.get.assert_not_awaited()


async def test_no_status_when_no_lock_held() -> None:
    state = {"messages": [HumanMessage(content="what's up")]}
    cache = _redis_holding(lock_value=None)  # get() returns None -> lock free
    with patch(f"{MODULE}.redis_cache", cache):
        out = await executor_status_hook(state, _config(), MagicMock())

    assert out["messages"] == state["messages"]
