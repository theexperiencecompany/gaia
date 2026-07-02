"""Unit tests for executor tool_data attachment in the chat stream (stream.py).

Pins the two live-path persistence fixes:
1. _attach_executor_tool_data runs on CANCELLED streams too — reintroducing the
   old `if state.is_cancelled: return` early-exit makes every stopped turn lose
   its executor cards and fails these tests.
2. _finalize_stream tears the session down only AFTER the fallback save — the
   backstop attach drains the session, so teardown-first turns it into dead
   code (this exact bug existed and was caught by writing these tests).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import session as sess
from app.agents.core.background.session import RunKind, create_session, get_session
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _attach_executor_tool_data,
    _finalize_stream,
    _StreamState,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _ready_session_with_cards(stream_id: str) -> None:
    """A live session whose executor finished after producing one tool card."""
    session = create_session(stream_id, RunKind.LIVE)
    session.executor_spawned = True
    session.done_event.set()  # executor already signalled completion
    session.tool_events.append(
        {"tool_data": {"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}}
    )


def _state(*, cancelled: bool, saved: bool = False) -> _StreamState:
    state = _StreamState()
    state.is_cancelled = cancelled
    state.saved = saved
    return state


@pytest.mark.unit
class TestAttachExecutorToolData:
    @pytest.mark.parametrize("cancelled", [True, False])
    async def test_attaches_cards_regardless_of_cancellation(self, cancelled) -> None:
        """THE regression test for 'stop the stream → all tool_data is gone':
        the comms path owns a live run's cards, so it must push them onto the
        saved message even when the user cancelled."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=cancelled)

        body = MagicMock()
        body.voice_mode = False

        with patch.object(chat_stream, "conversations_collection") as col:
            col.update_one = AsyncMock()
            await _attach_executor_tool_data("s1", body, {"user_id": "u1"}, "conv-1", state)

        col.update_one.assert_awaited_once()
        query, update = col.update_one.await_args.args
        assert query["messages.message_id"] == state.bot_message_id
        pushed = update["$push"]["messages.$.tool_data"]["$each"]
        assert pushed[0]["tool_name"] == "tool_calls_data"

    async def test_no_cards_means_no_mongo_write(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        session.executor_spawned = True
        session.done_event.set()
        body = MagicMock()
        body.voice_mode = False

        with patch.object(chat_stream, "conversations_collection") as col:
            col.update_one = AsyncMock()
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=False)
            )

        col.update_one.assert_not_awaited()

    async def test_mongo_failure_is_swallowed(self) -> None:
        _ready_session_with_cards("s1")
        body = MagicMock()
        body.voice_mode = False

        with patch.object(chat_stream, "conversations_collection") as col:
            col.update_one = AsyncMock(side_effect=RuntimeError("mongo down"))
            # best-effort: must not raise into the stream orchestrator
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=True)
            )


@pytest.mark.unit
class TestFinalizeStreamBackstop:
    async def _finalize(self, state: _StreamState):
        with (
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(chat_stream, "conversations_collection") as col,
            patch.object(chat_stream, "stream_manager") as sm,
            patch.object(chat_stream, "flush_fs_metrics", return_value={}),
        ):
            col.update_one = AsyncMock()
            sm.cleanup = AsyncMock()
            sm.release_conversation_lock_if_owned = AsyncMock()
            await _finalize_stream("s1", MagicMock(), {"user_id": "u1"}, "conv-1", state, None)
        return persist, col

    async def test_unsaved_turn_gets_fallback_save_and_attach(self) -> None:
        """The error path must still drain the session: teardown happening
        before the backstop attach silently produced an empty drain."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=True, saved=False)

        persist, col = await self._finalize(state)

        persist.assert_awaited_once()
        col.update_one.assert_awaited_once()  # cards drained and pushed
        assert get_session("s1") is None  # session torn down afterwards

    async def test_saved_turn_is_not_resaved_or_reattached(self) -> None:
        """The happy path saved early and attached already — the backstop must
        never double-persist or double-attach."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=False, saved=True)

        persist, col = await self._finalize(state)

        persist.assert_not_awaited()
        col.update_one.assert_not_awaited()
        assert get_session("s1") is None  # cleanup still happens
