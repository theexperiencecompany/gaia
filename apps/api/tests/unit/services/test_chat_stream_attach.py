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

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.callbacks import UsageMetadataCallbackHandler
import pytest

from app.agents.core.agent import AgentRunOptions, StreamMessageIds
from app.agents.core.background import session as sess
from app.agents.core.background.session import RunKind, create_session, get_session
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _attach_executor_tool_data,
    _consume_agent_stream,
    _finalize_stream,
    _resolve_pending_approval_turn,
    _StreamState,
    _TurnContext,
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

    async def test_saved_turn_is_not_resaved_or_reattached(self) -> None:
        """The happy path saved early and attached already — the backstop must
        never double-persist or double-attach."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=False, saved=True)

        persist, repo = await self._finalize(state)

        persist.assert_not_awaited()
        repo.append_message_tool_data.assert_not_awaited()
        assert get_session("s1") is None  # cleanup still happens


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


class TestConsumeAgentStreamCallsTheAgent:
    """``_consume_agent_stream`` is the only place the turn's identity is handed
    to ``call_agent``: the request, the user, the conversation, the usage
    collector + source (as ``AgentRunOptions``) and the three message ids (as
    ``StreamMessageIds``). Every one of them is a keyword the agent reads and
    nothing here reads back, so a dropped or nulled argument produces a turn
    that streams normally and is attributed to nobody.
    """

    async def test_the_turn_identity_reaches_call_agent_intact(self) -> None:
        captured: dict[str, Any] = {}

        async def _no_chunks() -> AsyncGenerator[str, None]:
            return
            yield ""  # pragma: no cover - makes this an async generator

        # The real ``call_agent`` signature, so a dropped positional/keyword
        # raises TypeError here instead of silently shifting an argument.
        async def fake_call_agent(
            request: MessageRequestWithHistory,
            conversation_id: str,
            user: AuthenticatedUser,
            options: AgentRunOptions | None = None,
            ids: StreamMessageIds | None = None,
        ) -> AsyncGenerator[str, None]:
            captured.update(
                request=request,
                conversation_id=conversation_id,
                user=user,
                options=options,
                ids=ids,
            )
            return _no_chunks()

        body = MessageRequestWithHistory(message="hi", messages=[], conversation_id="conv-1")
        user: AuthenticatedUser = {"user_id": "u1"}
        state = _StreamState(turn_id="turn-1")
        usage_callback = UsageMetadataCallbackHandler()
        turn = _TurnContext(
            conversation_id="conv-1",
            stream_id="stream-1",
            source="whatsapp",
            usage_callback=usage_callback,
        )

        with patch.object(chat_stream, "call_agent", fake_call_agent):
            left_over = await _consume_agent_stream(body, user, turn, None, state)

        assert left_over is None
        assert captured["request"] is body
        assert captured["user"] is user
        assert captured["conversation_id"] == "conv-1"

        options = captured["options"]
        assert isinstance(options, AgentRunOptions)
        assert options.usage_metadata_callback is usage_callback
        assert options.source == "whatsapp"

        assert captured["ids"] == StreamMessageIds(
            stream_id="stream-1",
            user_message_id=state.user_message_id,
            bot_message_id=state.bot_message_id,
        )


class TestRunChatStreamTurnDerivations:
    """``_run_chat_stream`` derives two values before any collaborator runs — the
    turn state (whose ``user_message_id`` IS the client's send id) and the
    new-conversation flag — then passes both on by value. Neither is read back,
    so a wrong derivation streams a perfectly normal-looking turn: the reply is
    persisted under an id the client never optimistically rendered, or the
    conversation row / description path is chosen for the wrong branch.
    """

    async def _run(self, body: MessageRequestWithHistory) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        async def fake_publish_init(
            body_: MessageRequestWithHistory,
            user_: AuthenticatedUser,
            conversation_id_: str,
            stream_id_: str,
            state_: _StreamState,
            is_new_conversation_: bool,
        ) -> None:
            seen["is_new_conversation"] = is_new_conversation_

        async def fake_consume(
            body_: MessageRequestWithHistory,
            user_: AuthenticatedUser,
            turn_: _TurnContext,
            description_task_: object,
            state_: _StreamState,
        ) -> None:
            seen["turn"] = turn_
            seen["state"] = state_

        with (
            patch.object(chat_stream, "stream_manager") as sm,
            patch.object(chat_stream, "register_executor_capture"),
            patch.object(chat_stream, "_set_stream_log_context"),
            patch.object(chat_stream, "_publish_init_chunk", fake_publish_init),
            patch.object(
                chat_stream, "_resolve_pending_approval_turn", AsyncMock(return_value=False)
            ),
            patch.object(chat_stream, "schedule_last_active_touch"),
            patch.object(chat_stream, "forward_artifact_events", AsyncMock()),
            patch.object(chat_stream, "_start_description_task", MagicMock(return_value=None)),
            patch.object(chat_stream, "_consume_agent_stream", fake_consume),
            patch.object(chat_stream, "_log_usage_summary"),
            patch.object(chat_stream, "_persist_turn", AsyncMock()),
            patch.object(chat_stream, "_attach_executor_tool_data", AsyncMock()),
            patch.object(chat_stream, "_finalize_description", AsyncMock()),
            patch.object(chat_stream, "capture_event"),
            patch.object(chat_stream, "_finalize_stream", AsyncMock()),
        ):
            sm.publish_chunk = AsyncMock()
            sm.complete_stream = AsyncMock()
            await chat_stream._run_chat_stream(
                "stream-1", body, {"user_id": "u1"}, "conv-1", "whatsapp"
            )

        return seen

    async def test_the_clients_send_id_is_the_turns_user_message_id(self) -> None:
        seen = await self._run(
            MessageRequestWithHistory(
                message="hi", messages=[], conversation_id="conv-1", turn_id="turn-abc"
            )
        )

        state = seen["state"]
        assert state.user_message_id == "turn-abc"

        turn = seen["turn"]
        assert turn.conversation_id == "conv-1"
        assert turn.stream_id == "stream-1"
        assert turn.source == "whatsapp"
        assert isinstance(turn.usage_callback, UsageMetadataCallbackHandler)

    async def test_a_request_without_a_conversation_id_is_a_new_conversation(self) -> None:
        seen = await self._run(
            MessageRequestWithHistory(message="hi", messages=[], conversation_id=None)
        )

        assert seen["is_new_conversation"] is True

    async def test_a_request_with_a_conversation_id_is_not_a_new_conversation(self) -> None:
        seen = await self._run(
            MessageRequestWithHistory(message="hi", messages=[], conversation_id="conv-1")
        )

        assert seen["is_new_conversation"] is False
