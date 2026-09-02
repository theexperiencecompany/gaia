"""Unit tests for executor tool_data attachment in the chat stream (stream.py).

Pins the two live-path persistence fixes:
1. _attach_executor_tool_data runs on CANCELLED streams too — reintroducing the
   old `if state.is_cancelled: return` early-exit makes every stopped turn lose
   its executor cards and fails these tests.
2. _finalize_stream tears the session down only AFTER the fallback save — the
   backstop attach drains the session, so teardown-first turns it into dead
   code (this exact bug existed and was caught by writing these tests).

The persist itself goes through ``conversation_repository.append_message_tool_data``;
these tests mock that repository method (never the DB).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import session as sess
from app.agents.core.background.session import RunKind, create_session, get_session
from app.models.message_models import MessageRequestWithHistory
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _attach_executor_tool_data,
    _finalize_stream,
    _resolve_pending_approval_turn,
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


def _state(*, cancelled: bool, saved: bool = False, attached: bool = False) -> _StreamState:
    state = _StreamState()
    state.is_cancelled = cancelled
    state.saved = saved
    state.attached = attached
    return state


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

        with patch.object(chat_stream, "conversation_repository") as repo:
            repo.append_message_tool_data = AsyncMock()
            await _attach_executor_tool_data("s1", body, {"user_id": "u1"}, "conv-1", state)

        repo.append_message_tool_data.assert_awaited_once()
        kwargs = repo.append_message_tool_data.await_args.kwargs
        assert repo.append_message_tool_data.await_args.args[0] == "conv-1"
        assert kwargs["user_id"] == "u1"
        assert kwargs["message_id"] == state.bot_message_id
        assert kwargs["entries"][0]["tool_name"] == "tool_calls_data"

    async def test_no_cards_means_no_mongo_write(self) -> None:
        session = create_session("s1", RunKind.LIVE)
        session.executor_spawned = True
        session.done_event.set()
        body = MagicMock()
        body.voice_mode = False

        with patch.object(chat_stream, "conversation_repository") as repo:
            repo.append_message_tool_data = AsyncMock()
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=False)
            )

        repo.append_message_tool_data.assert_not_awaited()

    async def test_mongo_failure_is_swallowed(self) -> None:
        _ready_session_with_cards("s1")
        body = MagicMock()
        body.voice_mode = False

        with patch.object(chat_stream, "conversation_repository") as repo:
            repo.append_message_tool_data = AsyncMock(side_effect=RuntimeError("mongo down"))
            # best-effort: must not raise into the stream orchestrator
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=True)
            )

    async def test_a_write_that_matched_no_message_is_reported(self) -> None:
        """``append_message_tool_data`` returns False when its
        ``messages.message_id`` filter matched nothing — nothing was written and
        nothing raised. Swallowing that means every executor tool card the user
        watched live is missing after a reload, with no trace in the logs.

        The sibling write in ``result_delivery._persist_follow_up_actions``
        already checks the same flag and logs; this path must not be quieter.
        """
        _ready_session_with_cards("s1")
        body = MagicMock()
        body.voice_mode = False

        with (
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "log") as log,
        ):
            repo.append_message_tool_data = AsyncMock(return_value=False)
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=False)
            )

        assert log.error.called, "a silently dropped tool_data write was never reported"

    async def test_a_successful_write_is_not_reported_as_a_failure(self) -> None:
        """Control: without it, unconditionally logging an error would satisfy
        the test above."""
        _ready_session_with_cards("s1")
        body = MagicMock()
        body.voice_mode = False

        with (
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "log") as log,
        ):
            repo.append_message_tool_data = AsyncMock(return_value=True)
            await _attach_executor_tool_data(
                "s1", body, {"user_id": "u1"}, "conv-1", _state(cancelled=False)
            )

        assert not log.error.called


class TestFinalizeStreamBackstop:
    async def _finalize(self, state: _StreamState):
        with (
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "stream_manager") as sm,
            patch.object(chat_stream, "flush_fs_metrics", return_value={}),
        ):
            repo.append_message_tool_data = AsyncMock()
            sm.cleanup = AsyncMock()
            await _finalize_stream("s1", MagicMock(), {"user_id": "u1"}, "conv-1", state, None)
        return persist, repo

    async def test_unsaved_turn_gets_fallback_save_and_attach(self) -> None:
        """The error path must still drain the session: teardown happening
        before the backstop attach silently produced an empty drain."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=True, saved=False)

        persist, repo = await self._finalize(state)

        persist.assert_awaited_once()
        repo.append_message_tool_data.assert_awaited_once()  # cards drained and pushed
        assert get_session("s1") is None  # session torn down afterwards

    async def test_saved_and_attached_turn_is_not_resaved_or_reattached(self) -> None:
        """The happy path saved early AND finished attaching — the backstop must
        never double-persist or double-attach."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=False, saved=True, attached=True)

        persist, repo = await self._finalize(state)

        persist.assert_not_awaited()
        repo.append_message_tool_data.assert_not_awaited()
        assert get_session("s1") is None  # cleanup still happens

    async def test_saved_but_interrupted_attach_still_attaches_cards(self) -> None:
        """The bug the user hit: a turn cut short DURING the executor wait has
        saved=True (early save ran) but attached=False (attach never finished).
        The backstop must still drain and persist the executor cards, or the
        reloaded turn loses its whole browser card. Gating the attach on `saved`
        (the old behavior) skipped it here — this is the regression pin."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=True, saved=True, attached=False)

        persist, repo = await self._finalize(state)

        persist.assert_not_awaited()  # already saved — no double save
        repo.append_message_tool_data.assert_awaited_once()  # cards STILL attached
        assert get_session("s1") is None


class TestResolvePendingApprovalTurnDegradesOnFailure:
    """A bot-channel classifier lookup failing must not take chat down —
    ``_resolve_pending_approval_turn`` must return False so the message runs
    as a normal turn (see the docstring on the guarded except block)."""

    def _bot_reply_body(self) -> MessageRequestWithHistory:
        return MessageRequestWithHistory(
            message="yes",
            messages=[{"role": "user", "content": "yes"}],
            conversation_id=None,
        )

    async def test_classifier_failure_runs_as_normal_turn(self) -> None:
        with patch.object(
            chat_stream,
            "resolve_pending_from_message",
            new=AsyncMock(side_effect=RuntimeError("classifier unreachable")),
        ):
            result = await _resolve_pending_approval_turn(
                self._bot_reply_body(),
                {"user_id": "u1"},
                "conv-1",
                "stream-1",
                _StreamState(),
                "whatsapp",  # a button-less bot channel — the only source that reaches the classifier
            )

        assert result is False

    async def test_classifier_failure_does_not_publish_or_persist(self) -> None:
        """The degraded path must skip the ack/persist steps entirely — those
        only belong to a genuinely resolved approve/deny."""
        with (
            patch.object(chat_stream, "stream_manager") as sm,
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(
                chat_stream,
                "resolve_pending_from_message",
                new=AsyncMock(side_effect=RuntimeError("classifier unreachable")),
            ),
        ):
            sm.publish_chunk = AsyncMock()
            await _resolve_pending_approval_turn(
                self._bot_reply_body(),
                {"user_id": "u1"},
                "conv-1",
                "stream-1",
                _StreamState(),
                "whatsapp",
            )

        sm.publish_chunk.assert_not_awaited()
        persist.assert_not_awaited()
