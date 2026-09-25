"""Unit tests for the paused-browser-handoff chat-reply resolution path.

_resolve_pending_browser_handoff_turn is the text-channel equivalent of the
browser handoff card's Continue/Cancel buttons: a chat reply on a conversation
with a pending handoff resolves it then runs as a normal turn, so comms voices
the ack with full context instead of a canned line.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.message_models import MessageRequestWithHistory
from app.models.user_models import AuthenticatedUser
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _resolve_pending_browser_handoff_turn,
    _run_chat_stream,
    _StreamState,
)
from tests.helpers import captured_wide_event

CONVERSATION_ID = "conv-1"
STREAM_ID = "stream-1"
USER_ID = "user-1"


def _body(message: str = "yes please continue") -> MessageRequestWithHistory:
    return MessageRequestWithHistory(
        message=message,
        messages=[{"role": "user", "content": message}],
        conversation_id=CONVERSATION_ID,
    )


def _user(user_id: str = USER_ID) -> AuthenticatedUser:
    return AuthenticatedUser(user_id=user_id)


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

    # Patched on the class: monkeypatch restores an instance target by re-setting
    # the instance attribute, which permanently shadows StreamManager.publish_chunk
    # on the process-wide singleton for any later test that patches the class.
    monkeypatch.setattr(
        type(chat_stream.stream_manager), "publish_chunk", AsyncMock(side_effect=capture)
    )
    monkeypatch.setattr(type(chat_stream.stream_manager), "complete_stream", AsyncMock())
    return chunks


class _Inbox:
    """The running browser job's inbox for a conversation: records what a reply posted to it."""

    def __init__(self) -> None:
        self.running_job: str | None = None
        self.posted: list[tuple[str, str]] = []

    async def post(self, conversation_id: str, text: str) -> str | None:
        self.posted.append((conversation_id, text))
        return self.running_job


@pytest.fixture(autouse=True)
def inbox(monkeypatch: pytest.MonkeyPatch) -> _Inbox:
    """Stand in for the job inbox in Redis: a unit test never reaches the process-wide client."""
    inbox = _Inbox()
    monkeypatch.setattr(chat_stream, "post_conversation_message", inbox.post)
    return inbox


@pytest.fixture
def persist(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock()
    monkeypatch.setattr(chat_stream, "_persist_turn", mock)
    return mock


@pytest.mark.unit
class TestNothingPendingOrMissingInputs:
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
        self, published: list[str], persist: AsyncMock, inbox: _Inbox
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="unrelated")
        ):
            async with captured_wide_event() as event:
                result = await _resolve_pending_browser_handoff_turn(
                    _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
                )

        assert result is False
        assert not published
        persist.assert_not_awaited()
        # Offered to a running browser task; with none running, nothing is recorded.
        assert inbox.posted == [(CONVERSATION_ID, "yes please continue")]
        assert "browser" not in event

    async def test_a_reply_during_a_running_browser_task_reaches_that_task(
        self, published: list[str], persist: AsyncMock, inbox: _Inbox
    ) -> None:
        inbox.running_job = "job-7"
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value=None)
        ):
            async with captured_wide_event() as event:
                result = await _resolve_pending_browser_handoff_turn(
                    _body("use the blue one"), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
                )

        assert result is False
        assert inbox.posted == [(CONVERSATION_ID, "use the blue one")]
        assert event["browser"] == {"job_id": "job-7", "message_to_running_job": True}

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
    """An optional-feature lookup failing must not take chat down — chat runs as a normal turn instead (see the docstring on the guarded except)."""

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
    async def test_resolved_continue_runs_the_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="continue")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published

    async def test_state_is_left_for_the_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        state = _StreamState()

        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="continue")
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, state
            )

        assert state.complete_message == ""
        assert state.turn_completed_at is None

    async def test_neither_persists_nor_terminates_the_stream(
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

        assert result is False
        persist.assert_not_awaited()
        assert not published
        chat_stream.stream_manager.complete_stream.assert_not_awaited()


@pytest.mark.unit
class TestCancelResolution:
    async def test_resolved_cancel_runs_the_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="cancel")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(), _user(), CONVERSATION_ID, STREAM_ID, _StreamState()
            )

        assert result is False
        assert not published
        persist.assert_not_awaited()
        chat_stream.stream_manager.complete_stream.assert_not_awaited()


@pytest.mark.unit
class TestRedirectResolution:
    """A reply that declines the paused step but says what to do instead resumes the run."""

    async def test_redirect_resolves_then_runs_the_normal_turn(
        self, published: list[str], persist: AsyncMock
    ) -> None:
        state = _StreamState()
        with patch.object(
            chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="redirect")
        ):
            result = await _resolve_pending_browser_handoff_turn(
                _body(message="never mind the login, just tell me the headline"),
                _user(),
                CONVERSATION_ID,
                STREAM_ID,
                state,
            )

        assert result is False
        assert not published
        assert state.complete_message == ""
        persist.assert_not_awaited()


@pytest.mark.unit
class TestTheAgentsThreadLearnsWhatTheUserSaid:
    """The resolution is recorded factually so the normal turn that follows answers with context."""

    @pytest.mark.parametrize("action", ["continue", "redirect", "cancel"])
    async def test_the_reply_and_its_resolution_are_recorded_in_the_conversations_thread(
        self, action: str, published: list[str], persist: AsyncMock
    ) -> None:
        recorded = AsyncMock()
        with (
            patch.object(
                chat_stream, "resolve_handoff_from_message", AsyncMock(return_value=action)
            ),
            patch.object(chat_stream, "record_exchange_in_thread", recorded),
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(message="never mind the login, just tell me the headline"),
                _user(),
                CONVERSATION_ID,
                STREAM_ID,
                _StreamState(),
            )

        recorded.assert_awaited_once()
        conversation_id, user_message, reply = recorded.await_args.args
        assert conversation_id == CONVERSATION_ID
        assert user_message == "never mind the login, just tell me the headline"
        assert reply == f"[Browser handoff resolved: {action}]"

    async def test_an_unrelated_reply_records_nothing(self, published: list[str]) -> None:
        recorded = AsyncMock()
        with (
            patch.object(
                chat_stream, "resolve_handoff_from_message", AsyncMock(return_value="unrelated")
            ),
            patch.object(chat_stream, "record_exchange_in_thread", recorded),
        ):
            await _resolve_pending_browser_handoff_turn(
                _body(message="what is the weather"),
                _user(),
                CONVERSATION_ID,
                STREAM_ID,
                _StreamState(),
            )

        recorded.assert_not_awaited()


@pytest.mark.unit
class TestRunChatStreamNeverShortCircuitsOnHandoffResolution:
    """Handoff resolution records into the thread and the agent always runs: no canned ack ever ends the turn early."""

    def _patched(self, *, handoff_resolved: bool):
        """Mock every collaborator of _run_chat_stream except the handoff resolution branch under test."""
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
            stream_manager=MagicMock(
                publish_chunk=AsyncMock(),
                complete_stream=AsyncMock(),
                is_cancelled=AsyncMock(return_value=False),
                set_error=AsyncMock(),
            ),
            capture_event=MagicMock(),
        )

    async def test_always_runs_the_agent_even_when_a_handoff_resolved(self) -> None:
        body = _body()
        user = _user()
        with self._patched(handoff_resolved=True):
            await _run_chat_stream(
                stream_id=STREAM_ID,
                body=body,
                user=user,
                conversation_id=CONVERSATION_ID,
            )

            chat_stream._consume_agent_stream.assert_awaited_once()
            # Full positional args, not just call-count — pins arg order/identity
            # against a swap mutant (e.g. body<->user, conversation_id<->stream_id).
            handoff_call = chat_stream._resolve_pending_browser_handoff_turn.await_args
            assert handoff_call is not None
            assert handoff_call.args[:4] == (body, user, CONVERSATION_ID, STREAM_ID)
            state = handoff_call.args[4]
            assert isinstance(state, _StreamState)

            register_call = chat_stream.register_executor_capture.call_args
            assert register_call == ((STREAM_ID,), {"voice_mode": body.voice_mode})

            # the finally block still tears the stream down on the normal path,
            # threading the SAME state object built at the top of the function.
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
