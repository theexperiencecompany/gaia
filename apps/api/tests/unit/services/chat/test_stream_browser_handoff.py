"""Unit tests for the paused-browser-handoff chat-reply resolution path.

``_resolve_pending_browser_handoff_turn`` is the text-channel equivalent of the
browser handoff card's Continue/Cancel buttons: a chat reply on a conversation
with a pending handoff can continue or cancel the paused browser task instead
of running as a normal turn. ``_run_chat_stream`` must short-circuit the whole
turn when that resolution fires, and fall through to the normal agent run
otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.browser import BROWSER_HANDOFF_ACK_CANCEL, BROWSER_HANDOFF_ACK_CONTINUE
from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory
from app.models.stream_events import MainResponseCompleteFrame
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _resolve_pending_browser_handoff_turn,
    _run_chat_stream,
    _StreamState,
)
from app.utils.agent_utils import format_sse_data, format_sse_response

CONVERSATION_ID = "conv-1"
STREAM_ID = "stream-1"
USER_ID = "user-1"


def _body(message: str = "yes please continue") -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message=message,
        messages=[{"role": "user", "content": message}],
        conversation_id=CONVERSATION_ID,
    )


def _user(user_id: str | None = USER_ID) -> dict[str, str | None]:
    return {"user_id": user_id}


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Chunks published to the client, in order."""
    chunks: list[str] = []

    async def capture(stream_id: str, chunk: str) -> None:
        # Invariant for every test in this file, so it is enforced here rather
        # than restated in each: a chunk published to the wrong stream (or to
        # None) is a reply the user's browser never receives.
        assert stream_id == STREAM_ID
        chunks.append(chunk)

    monkeypatch.setattr(chat_stream.stream_manager, "publish_chunk", AsyncMock(side_effect=capture))
    monkeypatch.setattr(chat_stream.stream_manager, "complete_stream", AsyncMock())
    return chunks


@pytest.fixture
def persist(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(chat_stream, "_persist_turn", mock)
    return mock


@pytest.mark.unit
class TestNothingPendingOrMissingInputs:
    async def test_no_user_id_returns_false_without_looking_up_handoff(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(chat_stream, "resolve_handoff_from_message") as resolve:
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(user_id=None), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        resolve.assert_not_called()
        assert result is False
        assert not published
        persist.assert_not_awaited()

    async def test_empty_message_returns_false_without_looking_up_handoff(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        body = _body(message="")
        # Client omits empty-text turns from ``messages``, so the trailing
        # history entry here is the previous assistant reply, not this turn.
        body.messages = [{"role": "assistant", "content": "ok"}]
        with patch.object(chat_stream, "resolve_handoff_from_message") as resolve:
            result = await _resolve_pending_browser_handoff_turn(
                body, _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        resolve.assert_not_called()
        assert result is False
        assert not published

    async def test_falsy_empty_string_user_id_returns_false_without_looking_up_handoff(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        # "" is falsy but not None — pins ``not user_id`` against a mutant
        # that narrows the guard to ``user_id is None``.
        with patch.object(chat_stream, "resolve_handoff_from_message") as resolve:
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(user_id=""), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        resolve.assert_not_called()
        assert result is False
        assert not published
        persist.assert_not_awaited()

    async def test_nothing_pending_runs_as_a_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value=None)
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published
        persist.assert_not_awaited()

    async def test_unrelated_reply_runs_as_a_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="unrelated")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published
        persist.assert_not_awaited()

    @pytest.mark.parametrize("action", ["Continue", "Cancel", "continued", "", "cancel "])
    async def test_near_miss_action_runs_as_a_normal_turn(
        self, action: str, published: list[str], persist: AsyncMock
    ) -> None:
        # Pins the ``action not in ("continue", "cancel")`` membership check
        # against a mutant that pads either literal in the tuple.
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value=action)
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published
        persist.assert_not_awaited()

    async def test_resolve_handoff_from_message_called_with_exact_args(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value=None)
        ) as resolve:
            await _resolve_pending_browser_handoff_turn(
                _body(message="hello there"),
                _user(user_id="user-42"),
                CONVERSATION_ID,
                STREAM_ID,
                _StreamState(),
            )

        resolve.assert_awaited_once_with(CONVERSATION_ID, "user-42", "hello there")


@pytest.mark.unit
class TestLookupFailureDegradesToNormalTurn:
    """An optional-feature lookup failing must not take chat down — chat runs
    as a normal turn instead (see the docstring on the guarded except)."""

    async def test_exception_returns_false(self, published: list[str], persist: AsyncMock) -> None:
        with patch.object(
            chat_stream,
            "resolve_handoff_from_message",
            AsyncMock(side_effect=RuntimeError("redis unreachable")),
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published, (
            "a degraded lookup must not publish an ack for a turn it didn't resolve"
        )
        persist.assert_not_awaited()

    async def test_exception_is_logged_with_type_and_no_leaked_traceback_message(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with (
            patch.object(chat_stream, "log") as log,
            patch.object(
                chat_stream,
                "resolve_handoff_from_message",
                AsyncMock(side_effect=ValueError("boom")),
            ),
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        log.error.assert_called_once_with(
            f"{LogTag.CHAT} Pending browser-handoff check failed; normal turn",
            error_type="ValueError",
        )


@pytest.mark.unit
class TestContinueResolution:
    async def test_publishes_the_exact_continue_ack(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="continue")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is True
        assert published[0] == format_sse_response(BROWSER_HANDOFF_ACK_CONTINUE)
        # Pins the destination stream, not just the payload — a mutant that
        # publishes the ack to the wrong stream (e.g. None) leaves the payload
        # assertion above green while the user's browser never sees the reply.
        assert chat_stream.stream_manager.publish_chunk.await_args_list[0].args[0] == STREAM_ID

    async def test_state_is_stamped_with_the_ack_and_completion_time(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        state = _StreamState()
        before = datetime.now(UTC)

        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="continue")
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, state
            )

        assert state.complete_message == BROWSER_HANDOFF_ACK_CONTINUE
        assert state.turn_completed_at is not None
        assert state.turn_completed_at >= before

    async def test_persists_and_terminates_the_stream_in_order(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        body = _body()
        user = _user()
        state = _StreamState()

        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="continue")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                body, user, CONVERSATION_ID, STREAM_ID, state
            )

        assert result is True
        persist.assert_awaited_once_with(STREAM_ID, body, user, CONVERSATION_ID, state)
        assert published[-1] == "data: [DONE]\n\n"
        # Pins the destination stream of the closing [DONE] chunk — a mutant
        # that sends it to None instead of STREAM_ID never reaches the client.
        assert chat_stream.stream_manager.publish_chunk.await_args_list[-1].args[0] == STREAM_ID
        chat_stream.stream_manager.complete_stream.assert_awaited_once_with(STREAM_ID)


@pytest.mark.unit
class TestCancelResolution:
    async def test_publishes_the_exact_cancel_ack(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="cancel")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is True
        assert published[0] == format_sse_response(BROWSER_HANDOFF_ACK_CANCEL)

    async def test_state_is_stamped_with_the_cancel_ack(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        state = _StreamState()

        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="cancel")
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, state
            )

        assert state.complete_message == BROWSER_HANDOFF_ACK_CANCEL

    async def test_completion_frame_is_published_before_persist(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="cancel")
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert len(published) == 3
        assert published[1] == format_sse_data(
            MainResponseCompleteFrame(main_response_complete=True).model_dump()
        )
        assert published[2] == "data: [DONE]\n\n"
        # Every publish in the turn must target the resolved stream, not just
        # carry the right payload — a mutant swapping the stream_id argument
        # for None on any of these three calls silently drops the chunk.
        call_args_list = chat_stream.stream_manager.publish_chunk.await_args_list
        assert [call.args[0] for call in call_args_list] == [STREAM_ID, STREAM_ID, STREAM_ID]


@pytest.mark.unit
class TestRunChatStreamShortCircuitsOnHandoffResolution:
    """The orchestrator must return without running the agent when the
    browser-handoff resolver fully handled the turn, and must fall through to
    the normal turn otherwise."""

    def _patched(self, *, handoff_resolved: bool):
        """Mock every collaborator of ``_run_chat_stream`` except the handoff
        resolution branch under test."""
        return patch.multiple(
            chat_stream,
            register_executor_capture=MagicMock(),
            _set_stream_log_context=MagicMock(),
            _publish_init_chunk=AsyncMock(),
            _resolve_pending_approval_turn=AsyncMock(return_value=False),
            schedule_last_active_touch=MagicMock(),
            forward_artifact_events=AsyncMock(),
            _resolve_pending_browser_handoff_turn=AsyncMock(return_value=handoff_resolved),
            _start_description_task=MagicMock(return_value=None),
            _consume_agent_stream=AsyncMock(return_value=None),
            _log_usage_summary=MagicMock(),
            _persist_turn=AsyncMock(),
            _attach_executor_tool_data=AsyncMock(),
            _finalize_description=AsyncMock(),
            _finalize_stream=AsyncMock(),
            stream_manager=MagicMock(publish_chunk=AsyncMock(), complete_stream=AsyncMock()),
            capture_event=MagicMock(),
        )

    async def test_returns_early_without_running_the_agent(self) -> None:
        body = _body()
        user = _user()
        with self._patched(handoff_resolved=True):
            await _run_chat_stream(
                stream_id=STREAM_ID,
                body=body,
                user=user,
                conversation_id=CONVERSATION_ID,
            )

            chat_stream._consume_agent_stream.assert_not_awaited()
            # Full positional args, not just call-count — pins arg order/identity
            # against a swap mutant (e.g. body<->user, conversation_id<->stream_id).
            handoff_call = chat_stream._resolve_pending_browser_handoff_turn.await_args
            assert handoff_call is not None
            assert handoff_call.args[:4] == (body, user, CONVERSATION_ID, STREAM_ID)
            state = handoff_call.args[4]
            assert isinstance(state, _StreamState)

            register_call = chat_stream.register_executor_capture.call_args
            assert register_call == ((STREAM_ID,), {"voice_mode": body.voice_mode})

            # the finally block still tears the stream down even on the short-circuit
            # path, threading the SAME state object built at the top of the function.
            chat_stream._finalize_stream.assert_awaited_once()
            finalize_call = chat_stream._finalize_stream.await_args
            assert finalize_call is not None
            assert finalize_call.args[:5] == (STREAM_ID, body, user, CONVERSATION_ID, state)

    async def test_runs_the_agent_when_nothing_was_pending(self) -> None:
        body = _body()
        user = _user()
        with self._patched(handoff_resolved=False):
            await _run_chat_stream(
                stream_id=STREAM_ID,
                body=body,
                user=user,
                conversation_id=CONVERSATION_ID,
            )

            handoff_call = chat_stream._resolve_pending_browser_handoff_turn.await_args
            assert handoff_call is not None
            assert handoff_call.args[:4] == (body, user, CONVERSATION_ID, STREAM_ID)
            chat_stream._consume_agent_stream.assert_awaited_once()
            chat_stream._finalize_stream.assert_awaited_once()
