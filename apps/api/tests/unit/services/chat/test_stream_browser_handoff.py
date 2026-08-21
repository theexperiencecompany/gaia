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
from app.models.message_models import MessageRequestWithHistory
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _resolve_pending_browser_handoff_turn,
    _run_chat_stream,
    _StreamState,
)

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

    async def capture(_stream_id: str, chunk: str) -> None:
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

        log.error.assert_called_once()
        _args, kwargs = log.error.call_args
        assert kwargs["error_type"] == "ValueError"


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
        assert any(BROWSER_HANDOFF_ACK_CONTINUE in chunk for chunk in published)
        assert not any(BROWSER_HANDOFF_ACK_CANCEL in chunk for chunk in published)

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
        assert any(BROWSER_HANDOFF_ACK_CANCEL in chunk for chunk in published)
        assert not any(BROWSER_HANDOFF_ACK_CONTINUE in chunk for chunk in published)

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

        assert len(published) >= 2
        assert '"main_response_complete": true' in published[1]


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
        with self._patched(handoff_resolved=True):
            await _run_chat_stream(
                stream_id=STREAM_ID,
                body=_body(),
                user=_user(),
                conversation_id=CONVERSATION_ID,
            )

            chat_stream._consume_agent_stream.assert_not_awaited()
            chat_stream._resolve_pending_browser_handoff_turn.assert_awaited_once()
            # the finally block still tears the stream down even on the short-circuit path
            chat_stream._finalize_stream.assert_awaited_once()

    async def test_runs_the_agent_when_nothing_was_pending(self) -> None:
        with self._patched(handoff_resolved=False):
            await _run_chat_stream(
                stream_id=STREAM_ID,
                body=_body(),
                user=_user(),
                conversation_id=CONVERSATION_ID,
            )

            chat_stream._resolve_pending_browser_handoff_turn.assert_awaited_once()
            chat_stream._consume_agent_stream.assert_awaited_once()
            chat_stream._finalize_stream.assert_awaited_once()
