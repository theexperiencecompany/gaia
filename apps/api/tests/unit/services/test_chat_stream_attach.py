"""Unit tests for the chat stream orchestrator (app/services/chat/stream.py).

Covers every phase helper of the turn pipeline — init chunk, agent stream
consumption, description tasks, usage accounting, error surfacing, HIL
approval resolution, persistence, executor tool_data attachment, and finalize
teardown — plus the two orchestrators (``run_chat_stream_background`` and
``_run_chat_stream``) themselves.

Two sections pin live-path persistence fixes:
1. _attach_executor_tool_data runs on CANCELLED streams too — reintroducing the
   old `if state.is_cancelled: return` early-exit makes every stopped turn lose
   its executor cards and fails these tests.
2. _finalize_stream tears the session down only AFTER the fallback save — the
   backstop attach drains the session, so teardown-first turns it into dead
   code (this exact bug existed and was caught by writing these tests).

The persist itself goes through ``conversation_repository.append_message_tool_data``;
these tests mock that repository method (never the DB).
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langgraph.errors import GraphRecursionError
import pytest

from app.agents.core.background import session as sess
from app.agents.core.background.session import RunKind, create_session, get_session
from app.constants.cache import EXECUTOR_WAIT_TIMEOUT, VOICE_EXECUTOR_RESULT_TIMEOUT_S
from app.constants.hil import HIL_ACK_APPROVED, HIL_ACK_DENIED, HIL_CLASSIFIER_HISTORY_TURNS
from app.constants.log_tags import LogTag
from app.models.message_models import (
    FileData,
    MessageRequestWithHistory,
    ReplyToMessageData,
    SelectedCalendarEventData,
    SelectedWorkflowData,
)
from app.models.stream_events import (
    ConversationDescriptionFrame,
    ConversationInitializedFrame,
    ErrorFrame,
    MainResponseCompleteFrame,
)
from app.services.chat import stream as chat_stream
from app.services.chat.stream import (
    _attach_executor_tool_data,
    _consume_agent_stream,
    _finalize_description,
    _finalize_stream,
    _handle_stream_error,
    _log_usage_summary,
    _parse_complete_message,
    _persist_turn,
    _publish_description_if_ready,
    _publish_init_chunk,
    _recent_history,
    _resolve_pending_approval_turn,
    _run_chat_stream,
    _set_stream_log_context,
    _start_description_task,
    _StreamState,
    _wait_for_artifact_forwarder,
    run_chat_stream_background,
)
from app.utils.agent_utils import format_sse_data, format_sse_response

USER = {"user_id": "u1", "email": "u1@test.local"}


@pytest.fixture(autouse=True)
def _clean_registry():
    sess._sessions.clear()
    yield
    sess._sessions.clear()


def _body(**overrides: Any) -> MessageRequestWithHistory:
    """A minimal request body; pass keyword overrides for the field under test."""
    defaults: dict[str, Any] = {
        "message": "hello",
        "conversation_id": "conv-1",
        "messages": [{"role": "user", "content": "hello"}],
    }
    defaults.update(overrides)
    return MessageRequestWithHistory(**defaults)


def _sm() -> MagicMock:
    """StreamManager stand-in with every async method pre-wired."""
    sm = MagicMock()
    sm.publish_chunk = AsyncMock()
    sm.is_cancelled = AsyncMock(return_value=False)
    sm.update_progress = AsyncMock()
    sm.complete_stream = AsyncMock()
    sm.set_error = AsyncMock()
    sm.cleanup = AsyncMock()
    return sm


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


async def _agent_stream(*chunks: str) -> AsyncGenerator[str, None]:
    for chunk in chunks:
        yield chunk


async def _coro(value: str) -> str:
    return value


async def _boom(message: str) -> str:
    raise RuntimeError(message)


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
        state = _state(cancelled=False)
        body = MagicMock()
        body.voice_mode = False

        with (
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "log") as log,
        ):
            repo.append_message_tool_data = AsyncMock(return_value=False)
            await _attach_executor_tool_data("s1", body, {"user_id": "u1"}, "conv-1", state)

        log.error.assert_called_once_with(
            f"{LogTag.CHAT} Executor tool_data attach matched no message, dropping cards",
            conversation_id="conv-1",
            message_id=state.bot_message_id,
            entries=1,
        )

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

    @pytest.mark.parametrize(
        ("voice_mode", "expected_timeout"),
        [(False, EXECUTOR_WAIT_TIMEOUT), (True, VOICE_EXECUTOR_RESULT_TIMEOUT_S)],
    )
    async def test_executor_wait_timeout_depends_on_voice_mode(
        self, voice_mode: bool, expected_timeout: float
    ) -> None:
        """Voice turns cap the wait much lower — the user is mid-call and the
        narrated answer still arrives via WebSocket on timeout."""
        with (
            patch.object(chat_stream, "await_executor_done", new_callable=AsyncMock) as wait,
            patch.object(chat_stream, "drain_executor_tool_data", return_value=[]),
        ):
            await _attach_executor_tool_data(
                "s1", _body(voice_mode=voice_mode), USER, "conv-1", _state(cancelled=False)
            )

        wait.assert_awaited_once_with("s1", timeout=expected_timeout)

    async def test_empty_drain_returns_before_any_write(self) -> None:
        """An executor that produced nothing must not even reach the repo."""
        with (
            patch.object(chat_stream, "await_executor_done", new_callable=AsyncMock),
            patch.object(chat_stream, "drain_executor_tool_data", return_value=[]),
            patch.object(chat_stream, "conversation_repository") as repo,
        ):
            repo.append_message_tool_data = AsyncMock()
            await _attach_executor_tool_data(
                "s1", _body(), {"user_id": "u1"}, "conv-1", _state(cancelled=True)
            )

        repo.append_message_tool_data.assert_not_awaited()

    async def test_exact_repository_args(self) -> None:
        state = _StreamState()
        entries = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]
        with (
            patch.object(chat_stream, "await_executor_done", new_callable=AsyncMock),
            patch.object(chat_stream, "drain_executor_tool_data", return_value=entries),
            patch.object(chat_stream, "conversation_repository") as repo,
        ):
            repo.append_message_tool_data = AsyncMock(return_value=True)
            await _attach_executor_tool_data("s1", _body(), {"user_id": "u1"}, "conv-1", state)

        repo.append_message_tool_data.assert_awaited_once_with(
            "conv-1",
            user_id="u1",
            message_id=state.bot_message_id,
            entries=entries,
        )

    async def test_missing_user_id_defaults_to_empty_string(self) -> None:
        entries = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]
        with (
            patch.object(chat_stream, "await_executor_done", new_callable=AsyncMock),
            patch.object(chat_stream, "drain_executor_tool_data", return_value=entries),
            patch.object(chat_stream, "conversation_repository") as repo,
        ):
            repo.append_message_tool_data = AsyncMock(return_value=True)
            await _attach_executor_tool_data("s1", _body(), {}, "conv-1", _StreamState())

        assert repo.append_message_tool_data.await_args.kwargs["user_id"] == ""

    async def test_repository_exception_is_logged_not_raised(self) -> None:
        entries = [{"tool_name": "tool_calls_data", "data": {"tool_call_id": "tc-1"}}]
        with (
            patch.object(chat_stream, "await_executor_done", new_callable=AsyncMock),
            patch.object(chat_stream, "drain_executor_tool_data", return_value=entries),
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "log") as log_mock,
        ):
            repo.append_message_tool_data = AsyncMock(side_effect=RuntimeError("mongo down"))
            await _attach_executor_tool_data(
                "s1", _body(), {"user_id": "u1"}, "conv-1", _StreamState()
            )

        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Failed to update bot message tool_data",
            error="mongo down",
            error_type="RuntimeError",
            conversation_id="conv-1",
        )


class TestFinalizeStreamBackstop:
    async def _finalize(
        self, state: _StreamState
    ) -> tuple[AsyncMock, AsyncMock, MagicMock, dict[str, str]]:
        body = MagicMock()
        user = {"user_id": "u1"}
        with (
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(chat_stream, "conversation_repository") as repo,
            patch.object(chat_stream, "stream_manager") as sm,
            patch.object(chat_stream, "flush_fs_metrics", return_value={}),
        ):
            repo.append_message_tool_data = AsyncMock()
            sm.cleanup = AsyncMock()
            await _finalize_stream("s1", body, user, "conv-1", state, None)
        return persist, repo, body, user

    async def test_unsaved_turn_gets_fallback_save_and_attach(self) -> None:
        """The error path must still drain the session: teardown happening
        before the backstop attach silently produced an empty drain."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=True, saved=False)

        persist, repo, body, user = await self._finalize(state)

        persist.assert_awaited_once_with("s1", body, user, "conv-1", state)
        repo.append_message_tool_data.assert_awaited_once()  # cards drained and pushed
        assert repo.append_message_tool_data.await_args.args[0] == "conv-1"
        assert get_session("s1") is None  # session torn down afterwards

    async def test_saved_turn_is_not_resaved_or_reattached(self) -> None:
        """The happy path saved early and attached already — the backstop must
        never double-persist or double-attach."""
        _ready_session_with_cards("s1")
        state = _state(cancelled=False, saved=True)

        persist, repo, body, user = await self._finalize(state)

        persist.assert_not_awaited()
        repo.append_message_tool_data.assert_not_awaited()
        assert get_session("s1") is None  # cleanup still happens


class TestFinalizeStreamCleanup:
    async def _finalize(
        self,
        state: _StreamState,
        *,
        artifact_task: asyncio.Task[None] | None = None,
        persist_error: Exception | None = None,
        fs_metrics: dict[str, Any] | None = None,
    ) -> tuple[AsyncMock, MagicMock, MagicMock, MagicMock, AsyncMock]:
        """Run _finalize_stream with every seam mocked; return (persist, sm, log, teardown, attach)."""
        sm = _sm()
        log_mock = MagicMock()
        with (
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(
                chat_stream, "_attach_executor_tool_data", new_callable=AsyncMock
            ) as attach,
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(chat_stream, "teardown_executor_capture") as teardown,
            patch.object(chat_stream, "flush_fs_metrics", return_value=fs_metrics or {}),
            patch.object(chat_stream, "log", log_mock),
        ):
            if persist_error is not None:
                persist.side_effect = persist_error
            await _finalize_stream("s1", _body(), USER, "conv-1", state, artifact_task)
        return persist, sm, log_mock, teardown, attach

    async def test_artifact_forwarder_task_is_cancelled(self) -> None:
        task = asyncio.create_task(asyncio.Event().wait())
        persist, sm, log_mock, teardown, _ = await self._finalize(
            _state(cancelled=True, saved=True), artifact_task=task
        )
        assert task.cancelled()

    async def test_fallback_save_failure_is_logged_and_teardown_still_runs(self) -> None:
        persist, sm, log_mock, teardown, attach = await self._finalize(
            _state(cancelled=True, saved=False), persist_error=RuntimeError("save failed")
        )
        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Fallback save failed for stream",
            stream_id="s1",
            error="save failed",
            error_type="RuntimeError",
            conversation_id="conv-1",
        )
        attach.assert_not_awaited()  # persist failed, so the backstop attach never ran
        teardown.assert_called_once_with("s1")
        sm.cleanup.assert_awaited_once_with("s1")

    async def test_wide_event_summary_fields(self) -> None:
        state = _state(cancelled=True, saved=True)
        state.complete_message = "hello"
        state.tool_data = {"tool_data": [{"tool_name": "search_results"}, {"no_name": True}]}
        state.todo_progress_accumulated = {"executor": {"progress": 0.5}}
        fs = {"read": {"count": 2, "total_ms": 3, "max_ms": 2}}
        _, sm, log_mock, teardown, _ = await self._finalize(state, fs_metrics=fs)

        kwargs = log_mock.set.call_args.kwargs
        assert kwargs["response_length"] == 5
        assert kwargs["tool_calls_count"] == 2
        assert kwargs["tool_types"] == ["search_results"]
        assert kwargs["todo_progress_sources"] == ["executor"]
        assert kwargs["fs"] == fs
        log_mock.debug.assert_called_once_with(
            f"{LogTag.CHAT} Background stream completed and saved", stream_id="s1"
        )

    async def test_empty_fs_metrics_are_elided(self) -> None:
        state = _state(cancelled=False, saved=True)
        state.complete_message = ""
        state.tool_data = {}  # no "tool_data" key — .get() default must hold
        _, sm, log_mock, teardown, _ = await self._finalize(state, fs_metrics={})

        kwargs = log_mock.set.call_args.kwargs
        assert "fs" not in kwargs
        assert kwargs["tool_calls_count"] == 0
        assert kwargs["tool_types"] == []
        assert kwargs["todo_progress_sources"] == []


class TestParseCompleteMessage:
    def test_parses_complete_message_and_cancelled(self) -> None:
        chunk = f"nostream: {json.dumps({'complete_message': 'done', 'cancelled': True})}"
        assert _parse_complete_message(chunk) == ("done", True)

    def test_missing_fields_default(self) -> None:
        assert _parse_complete_message(f"nostream: {json.dumps({})}") == ("", False)

    def test_non_dict_json_returns_empty(self) -> None:
        assert _parse_complete_message("nostream: []") == ("", False)
        assert _parse_complete_message('nostream: "plain string"') == ("", False)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_complete_message("nostream: {")


class TestRecentHistory:
    def test_drops_trailing_user_message(self) -> None:
        messages = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        assert _recent_history(messages) == messages[:-1]

    def test_trailing_assistant_message_is_kept(self) -> None:
        messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        assert _recent_history(messages) == messages

    def test_caps_window_to_classifier_history_turns(self) -> None:
        messages = [{"role": "user", "content": f"m{i}"} for i in range(7)]
        result = _recent_history(messages)
        assert result == messages[:-1][-HIL_CLASSIFIER_HISTORY_TURNS:]

    def test_empty_history(self) -> None:
        assert _recent_history([]) == []


class TestSetStreamLogContext:
    def _full_body(self) -> MessageRequestWithHistory:
        return MessageRequestWithHistory(
            message="hello",
            conversation_id="conv-1",
            messages=[
                {"role": "user", "content": "hi"},
                {"role": "user", "content": "hello world"},
            ],
            fileIds=["f1", "f2"],
            fileData=[FileData(fileId="f3", url="http://x/3.png", filename="3.png")],
            toolCategory="calendar",
            replyToMessage=ReplyToMessageData(id="r1", content="prev", role="user"),
            selectedCalendarEvent=SelectedCalendarEventData(
                id="ce-1",
                summary="Meeting",
                description="",
                start={"dateTime": "2026-01-01T10:00:00Z"},
                end={"dateTime": "2026-01-01T11:00:00Z"},
            ),
            selectedWorkflow=SelectedWorkflowData(id="wf-1", title="t", description="d", steps=[]),
            selectedTool="calendar_tool",
        )

    def test_attaches_full_chat_context(self) -> None:
        body = self._full_body()
        log_mock = MagicMock()
        with patch.object(chat_stream, "log", log_mock):
            _set_stream_log_context(body, "u1", "conv-1", "s1", True)

        kwargs = log_mock.set.call_args.kwargs
        assert kwargs["user"] == {"id": "u1"}
        assert kwargs["chat"] == {
            "conversation_id": "conv-1",
            "stream_id": "s1",
            "is_new_conversation": True,
            "message_count": 2,
            "has_files": True,
            "file_count": 3,
            "tool_category": "calendar",
            "has_reply": True,
            "has_calendar_event": True,
            "selected_workflow_id": "wf-1",
        }
        assert kwargs["user_message_length"] == len("hello world")
        assert kwargs["selected_tool"] == "calendar_tool"

    def test_bare_body_gets_empties(self) -> None:
        log_mock = MagicMock()
        with patch.object(chat_stream, "log", log_mock):
            _set_stream_log_context(_body(messages=[]), None, "conv-1", "s1", False)

        kwargs = log_mock.set.call_args.kwargs
        assert kwargs["user"] == {}
        assert kwargs["chat"]["message_count"] is None
        assert kwargs["chat"]["has_files"] is False
        assert kwargs["chat"]["file_count"] == 0
        assert kwargs["chat"]["has_reply"] is False
        assert kwargs["chat"]["has_calendar_event"] is False
        assert kwargs["chat"]["selected_workflow_id"] is None
        assert kwargs["user_message_length"] == 0
        assert kwargs["selected_tool"] is None

    def test_files_only_body_has_files_true(self) -> None:
        """has_files is OR over both file sources — a fileData-only send counts."""
        log_mock = MagicMock()
        body = _body(
            fileIds=[], fileData=[FileData(fileId="f1", url="http://x/1.png", filename="1.png")]
        )
        with patch.object(chat_stream, "log", log_mock):
            _set_stream_log_context(body, "u1", "conv-1", "s1", False)

        kwargs = log_mock.set.call_args.kwargs
        assert kwargs["chat"]["has_files"] is True
        assert kwargs["chat"]["file_count"] == 1


class TestStartDescriptionTask:
    async def test_existing_conversation_returns_none(self) -> None:
        with patch.object(
            chat_stream, "generate_and_update_description", new_callable=AsyncMock
        ) as gen:
            task = _start_description_task(False, _body(), "conv-1", USER)
        assert task is None
        gen.assert_not_called()

    async def test_new_conversation_spawns_task_with_last_message(self) -> None:
        body = _body(
            messages=[
                {"role": "user", "content": "a"},
                {"role": "user", "content": "b"},
                {"role": "user", "content": "c"},
            ],
            selectedTool="calendar_tool",
            selectedWorkflow=SelectedWorkflowData(id="wf-9", title="t", description="d", steps=[]),
        )
        with patch.object(
            chat_stream, "generate_and_update_description", new_callable=AsyncMock
        ) as gen:
            gen.return_value = "title"
            task = _start_description_task(True, body, "conv-1", USER)

        assert isinstance(task, asyncio.Task)
        gen.assert_called_once_with(
            "conv-1",
            {"role": "user", "content": "c"},
            USER,
            "calendar_tool",
            body.selectedWorkflow,
        )
        assert await task == "title"

    async def test_empty_history_passes_none_last_message(self) -> None:
        with patch.object(
            chat_stream, "generate_and_update_description", new_callable=AsyncMock
        ) as gen:
            task = _start_description_task(True, _body(messages=[]), "conv-1", USER)

        gen.assert_called_once_with("conv-1", None, USER, None, None)
        await task


class TestPublishDescriptionIfReady:
    async def test_none_task_is_returned_unchanged(self) -> None:
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            assert await _publish_description_if_ready("s1", None) is None
        sm.publish_chunk.assert_not_awaited()

    async def test_pending_task_is_returned_untouched(self) -> None:
        gate = asyncio.Event()
        task = asyncio.create_task(_gated("desc", gate))
        sm = _sm()
        try:
            with patch.object(chat_stream, "stream_manager", sm):
                result = await _publish_description_if_ready("s1", task)
            assert result is task
            sm.publish_chunk.assert_not_awaited()
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_done_task_publishes_description_frame_and_is_cleared(self) -> None:
        task = asyncio.create_task(_coro("Great title"))
        await task
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            result = await _publish_description_if_ready("s1", task)

        assert result is None
        expected = f"data: {json.dumps(ConversationDescriptionFrame(conversation_description='Great title').model_dump())}\n\n"
        sm.publish_chunk.assert_awaited_once_with("s1", expected)

    async def test_failed_task_is_logged_and_cleared(self) -> None:
        task = asyncio.create_task(_boom("desc failed"))
        with pytest.raises(RuntimeError):
            await task
        sm = _sm()
        with (
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(chat_stream, "log") as log_mock,
        ):
            result = await _publish_description_if_ready("s1", task)

        assert result is None
        sm.publish_chunk.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Failed to get conversation description",
            error="desc failed",
            error_type="RuntimeError",
        )


async def _gated(value: str, gate: asyncio.Event) -> str:
    await gate.wait()
    return value


class TestFinalizeDescription:
    async def test_none_task_skips_publish(self) -> None:
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            await _finalize_description(None, "s1")
        sm.publish_chunk.assert_not_awaited()

    async def test_publishes_task_result(self) -> None:
        task = asyncio.create_task(_coro("Conversation title"))
        await task
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            await _finalize_description(task, "s1")
        expected = f"data: {json.dumps(ConversationDescriptionFrame(conversation_description='Conversation title').model_dump())}\n\n"
        sm.publish_chunk.assert_awaited_once_with("s1", expected)

    async def test_task_failure_is_logged_and_publish_skipped(self) -> None:
        task = asyncio.create_task(_boom("desc failed"))
        with pytest.raises(RuntimeError):
            await task
        sm = _sm()
        with (
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(chat_stream, "log") as log_mock,
        ):
            await _finalize_description(task, "s1")
        sm.publish_chunk.assert_not_awaited()
        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Failed to get conversation description",
            error="desc failed",
            error_type="RuntimeError",
        )


class TestPublishInitChunk:
    async def test_existing_conversation_builds_identity_frame(self) -> None:
        body = _body()
        state = _StreamState()
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            await _publish_init_chunk(body, USER, "conv-1", "s1", state, False)

        expected = ConversationInitializedFrame(
            user_message_id=state.user_message_id,
            user_message_content="hello",
            bot_message_id=state.bot_message_id,
            stream_id="s1",
        ).model_dump(exclude={"conversation_id", "conversation_description"})
        sm.publish_chunk.assert_awaited_once_with("s1", f"data: {json.dumps(expected)}\n\n")

    async def test_new_conversation_delegates_to_initializer(self) -> None:
        body = _body(conversation_id=None)
        state = _StreamState()
        sm = _sm()
        with (
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(
                chat_stream, "initialize_new_conversation", new_callable=AsyncMock
            ) as init,
        ):
            init.return_value = "init-chunk-data"
            await _publish_init_chunk(body, USER, "conv-1", "s1", state, True)

        init.assert_awaited_once_with(
            body=body,
            user=USER,
            conversation_id="conv-1",
            user_message_id=state.user_message_id,
            bot_message_id=state.bot_message_id,
            stream_id="s1",
        )
        sm.publish_chunk.assert_awaited_once_with("s1", "init-chunk-data")


class TestHandleStreamError:
    async def test_publishes_error_frame_and_returns_message(self) -> None:
        sm = _sm()
        error = RuntimeError("boom")
        with (
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(chat_stream, "log") as log_mock,
        ):
            user_error = await _handle_stream_error("s1", error)

        assert user_error == "boom"
        expected = f"data: {json.dumps(ErrorFrame(error='boom').model_dump())}\n\n"
        sm.publish_chunk.assert_awaited_once_with("s1", expected)
        sm.set_error.assert_awaited_once_with("s1", "boom")
        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Background stream error for", stream_id="s1", error=error
        )

    async def test_recursion_error_gets_friendly_message(self) -> None:
        """A recursion-limit stop is an expected degradation — never surface the
        raw LangGraph internals to the user."""
        sm = _sm()
        with patch.object(chat_stream, "stream_manager", sm):
            user_error = await _handle_stream_error(
                "s1", GraphRecursionError("Recursion limit of 25 reached")
            )

        friendly = (
            "I hit my step limit on this one before finishing. "
            "Ask me to continue and I'll pick up where I left off."
        )
        assert user_error == friendly
        expected = f"data: {json.dumps(ErrorFrame(error=friendly).model_dump())}\n\n"
        sm.publish_chunk.assert_awaited_once_with("s1", expected)
        sm.set_error.assert_awaited_once_with("s1", friendly)


class TestLogUsageSummary:
    def _state_with_usage(self, usage: dict[str, Any]) -> _StreamState:
        state = _StreamState()
        state.usage_metadata = usage
        state.complete_message = "hello"
        state.follow_up_actions = ["a", "b"]
        state.is_cancelled = False
        return state

    def test_emits_aggregated_totals_merged_into_existing_model(self) -> None:
        state = self._state_with_usage(
            {
                "gpt-4": {
                    "input_tokens": 1,
                    "output_tokens": 3,
                    "input_token_details": {"cache_read": 1},
                }
            }
        )
        log_mock = MagicMock()
        log_mock.get.return_value = {"model": {"provider": "anthropic"}}
        with patch.object(chat_stream, "log", log_mock):
            _log_usage_summary(state)

        log_mock.set.assert_called_once_with(
            model={
                "provider": "anthropic",
                "tokens_used": 4,
                "input_tokens": 1,
                "output_tokens": 3,
                "cached_tokens": 1,
                "cache_hit_rate": 1.0,
            },
            response_length=5,
            follow_up_actions_count=2,
            is_cancelled=False,
        )

    def test_zero_input_tokens_yields_zero_hit_rate(self) -> None:
        state = self._state_with_usage(
            {"m": {"input_tokens": 0, "output_tokens": 2, "cached_content_token_count": 5}}
        )
        log_mock = MagicMock()
        log_mock.get.return_value = {}
        with patch.object(chat_stream, "log", log_mock):
            _log_usage_summary(state)

        model = log_mock.set.call_args.kwargs["model"]
        assert model["cache_hit_rate"] == 0.0
        assert model["cached_tokens"] == 5
        assert model["tokens_used"] == 2
        assert model["input_tokens"] == 0

    def test_non_integer_rate_is_rounded_to_four_decimals(self) -> None:
        """1/7 must round to 0.1429 — neither int-rounding nor 5-digit
        rounding nor a multiplication-turned rate may pass."""
        state = self._state_with_usage(
            {
                "gpt-4": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "input_token_details": {"cache_read": 1},
                }
            }
        )
        log_mock = MagicMock()
        log_mock.get.return_value = {}
        with patch.object(chat_stream, "log", log_mock):
            _log_usage_summary(state)

        model = log_mock.set.call_args.kwargs["model"]
        assert model["cache_hit_rate"] == 0.1429
        assert model["tokens_used"] == 10

    def test_cancelled_flag_and_empty_counts_flow_through(self) -> None:
        state = self._state_with_usage({})
        state.is_cancelled = True
        state.complete_message = "x" * 10
        state.follow_up_actions = []
        log_mock = MagicMock()
        log_mock.get.return_value = {}
        with patch.object(chat_stream, "log", log_mock):
            _log_usage_summary(state)

        kwargs = log_mock.set.call_args.kwargs
        assert kwargs["response_length"] == 10
        assert kwargs["follow_up_actions_count"] == 0
        assert kwargs["is_cancelled"] is True
        assert kwargs["model"]["cache_hit_rate"] == 0.0


class TestConsumeAgentStream:
    async def _consume(
        self,
        chunks: list[str],
        *,
        cancelled: bool = False,
        description_task: asyncio.Task[str] | None = None,
        process: AsyncMock | None = None,
        source: str | None = None,
    ) -> tuple[
        _StreamState,
        MagicMock,
        MagicMock,
        AsyncMock,
        asyncio.Task[str] | None,
        MessageRequestWithHistory,
        MagicMock,
    ]:
        sm = _sm()
        sm.is_cancelled = AsyncMock(return_value=cancelled)
        state = _StreamState()
        log_mock = MagicMock()
        call_agent = AsyncMock(return_value=_agent_stream(*chunks))
        proc_ctx = (
            patch.object(chat_stream, "process_data_chunk", process)
            if process is not None
            else nullcontext()
        )
        body = _body()
        usage_callback = MagicMock()
        with (
            patch.object(chat_stream, "stream_manager", sm),
            patch("app.services.chat.chunks.stream_manager", sm),
            patch("app.utils.stream_publishers.stream_manager", sm),
            patch.object(chat_stream, "call_agent", call_agent),
            patch.object(chat_stream, "log", log_mock),
            proc_ctx,
        ):
            result = await _consume_agent_stream(
                body, USER, "conv-1", "s1", source, usage_callback, description_task, state
            )
        return state, sm, log_mock, call_agent, result, body, usage_callback

    async def test_bot_source_flows_into_call_agent(self) -> None:
        state, sm, _, call_agent, _, _, _ = await self._consume(
            ["data: [DONE]\n\n"], source="telegram"
        )
        call_agent.assert_awaited_once()
        assert call_agent.await_args.kwargs["source"] == "telegram"

    async def test_streams_chunks_and_parses_nostream_marker(self) -> None:
        response_chunk = f"data: {json.dumps({'response': 'partial'})}\n\n"
        state, sm, log_mock, call_agent, result, body, usage_callback = await self._consume(
            [
                response_chunk,
                f"nostream: {json.dumps({'complete_message': 'final'})}",
                "data: [DONE]\n\n",
            ]
        )

        assert state.complete_message == "final"
        assert state.is_cancelled is False
        # The response chunk is forwarded (by process_data_chunk); the nostream
        # marker and the [DONE] sentinel are consumed, never published.
        assert sm.publish_chunk.await_args_list == [call("s1", response_chunk)]
        assert result is None
        call_agent.assert_awaited_once_with(
            request=body,
            user=USER,
            conversation_id="conv-1",
            usage_metadata_callback=usage_callback,
            stream_id="s1",
            user_message_id=state.user_message_id,
            bot_message_id=state.bot_message_id,
            source=None,
        )

    async def test_manager_cancellation_marks_state_and_keeps_consuming(self) -> None:
        """The inner graph driver owns cancellation; this loop just notes the
        flag and keeps consuming until the driver's nostream marker."""
        state, sm, log_mock, _, _, _, _ = await self._consume(
            [
                f"data: {json.dumps({'response': 'a'})}\n\n",
                f"nostream: {json.dumps({'complete_message': 'still done'})}",
            ],
            cancelled=True,
        )

        assert state.is_cancelled is True
        assert state.complete_message == "still done"
        sm.is_cancelled.assert_awaited_once_with("s1")
        log_mock.info.assert_called_once_with(
            f"{LogTag.CHAT} Stream cancelled by user", stream_id="s1"
        )

    async def test_nostream_cancelled_flag_sets_state(self) -> None:
        state, sm, log_mock, _, _, _, _ = await self._consume(
            [f"nostream: {json.dumps({'complete_message': 'stopped', 'cancelled': True})}"]
        )

        assert state.is_cancelled is True
        assert state.complete_message == "stopped"
        sm.publish_chunk.assert_not_awaited()

    async def test_prior_cancellation_survives_clean_nostream(self) -> None:
        """The flag is OR-ed with the marker: a manager-cancelled stream whose
        nostream marker lacks the cancelled key must stay cancelled."""
        state, sm, _, _, _, _, _ = await self._consume(
            [f"nostream: {json.dumps({'complete_message': 'stopped'})}"], cancelled=True
        )

        assert state.is_cancelled is True

    async def test_error_frame_records_state_error_and_passes_through(self) -> None:
        error_chunk = f"data: {json.dumps({'error': 'setup failed'})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume([error_chunk])

        assert state.error == "setup failed"
        assert sm.publish_chunk.await_args_list == [call("s1", error_chunk)]

    async def test_malformed_error_frame_does_not_set_state_error(self) -> None:
        chunk = 'data: {"error": '
        state, sm, _, _, _, _, _ = await self._consume([chunk])

        assert state.error == ""
        assert sm.publish_chunk.await_args_list == [call("s1", chunk)]

    async def test_error_payload_without_data_prefix_is_not_parsed(self) -> None:
        """The error frame check requires BOTH a data: prefix and an "error"
        key — an error-looking payload on a raw event is a passthrough. The
        chunk's first six chars are NOT the data: prefix but its tail IS valid
        JSON, so a check that ORs the conditions would parse it."""
        chunk = 'xxxxxx{"error": "boom"}'
        state, sm, _, _, _, _, _ = await self._consume([chunk])

        assert state.error == ""
        assert sm.publish_chunk.await_args_list == [call("s1", chunk)]

    async def test_response_containing_error_keyword_is_not_an_error(self) -> None:
        """The error frame must carry a real "error" KEY — a value that happens
        to contain the word must not mark the turn failed."""
        chunk = f"data: {json.dumps({'response': 'x', 'note': 'error'})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume([chunk])

        assert state.error == ""
        assert sm.publish_chunk.await_args_list == [call("s1", chunk)]

    async def test_non_data_chunk_is_published_as_is(self) -> None:
        chunk = "raw event line"
        state, sm, _, _, _, _, _ = await self._consume([chunk])

        assert sm.publish_chunk.await_args_list == [call("s1", chunk)]

    async def test_chunks_after_done_sentinel_are_still_processed(self) -> None:
        """[DONE] is skipped, not a stop — the loop keeps draining chunks."""
        first = f"data: {json.dumps({'response': 'a'})}\n\n"
        second = f"data: {json.dumps({'response': 'b'})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume(["data: [DONE]\n\n", first, second])

        assert sm.publish_chunk.await_args_list == [call("s1", first), call("s1", second)]

    async def test_chunks_after_nostream_marker_are_still_processed(self) -> None:
        nostream = f"nostream: {json.dumps({'complete_message': 'done'})}"
        later = f"data: {json.dumps({'response': 'b'})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume([nostream, later])

        assert state.complete_message == "done"
        assert sm.publish_chunk.await_args_list == [call("s1", later)]

    async def test_tool_data_chunk_accumulates_into_state(self) -> None:
        tool_entry = {"tool_name": "search_results", "data": {"items": []}, "timestamp": "t"}
        chunk = f"data: {json.dumps({'tool_data': tool_entry})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume([chunk])

        assert state.tool_data["tool_data"][0] == tool_entry
        assert sm.publish_chunk.await_args_list == [
            call("s1", f"data: {json.dumps({'tool_data': tool_entry})}\n\n")
        ]

    async def test_process_failure_falls_back_to_passthrough_and_logs(self) -> None:
        bad = f"data: {json.dumps({'response': 'x'})}\n\n"
        process = AsyncMock(side_effect=RuntimeError("bad chunk"))
        state, sm, log_mock, _, _, _, _ = await self._consume([bad], process=process)

        assert sm.publish_chunk.await_args_list == [call("s1", bad)]
        assert process.await_count == 1
        log_mock.error.assert_called_once_with(
            f"{LogTag.CHAT} Error processing chunk",
            error="bad chunk",
            error_type="RuntimeError",
            conversation_id="conv-1",
        )

    async def test_follow_up_actions_flow_into_state(self) -> None:
        process = AsyncMock(return_value=(["Draft a reply"], True))
        chunk = f"data: {json.dumps({'response': 'x'})}\n\n"
        state, sm, _, _, _, _, _ = await self._consume([chunk], process=process)

        assert state.follow_up_actions == ["Draft a reply"]
        assert sm.publish_chunk.await_args_list == []  # process handled publishing
        process.assert_awaited_once_with(
            "s1",
            chunk,
            state.tool_data,
            state.tool_outputs,
            state.todo_progress_accumulated,
            [],  # the list as it was BEFORE the process result replaced it
        )

    async def test_pending_description_task_is_returned_unchanged(self) -> None:
        gate = asyncio.Event()
        task = asyncio.create_task(_gated("desc", gate))
        response_chunk = f"data: {json.dumps({'response': 'a'})}\n\n"
        try:
            state, sm, _, _, result, _, _ = await self._consume(
                [response_chunk], description_task=task
            )
            assert result is task
            # The pending task published nothing — only the data chunk flowed.
            assert sm.publish_chunk.await_args_list == [call("s1", response_chunk)]
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_done_description_task_publishes_before_data_chunk(self) -> None:
        task = asyncio.create_task(_coro("Great title"))
        await task
        response_chunk = f"data: {json.dumps({'response': 'a'})}\n\n"
        state, sm, _, _, result, _, _ = await self._consume([response_chunk], description_task=task)

        assert result is None
        expected_desc = f"data: {json.dumps(ConversationDescriptionFrame(conversation_description='Great title').model_dump())}\n\n"
        assert sm.publish_chunk.await_args_list == [
            call("s1", expected_desc),
            call("s1", response_chunk),
        ]


class TestWaitForArtifactForwarder:
    async def test_returns_when_already_subscribed(self) -> None:
        subscribed = asyncio.Event()
        subscribed.set()
        with patch.object(chat_stream, "log") as log_mock:
            await _wait_for_artifact_forwarder(subscribed, "s1")
        log_mock.warning.assert_not_called()

    async def test_logs_warning_on_subscribe_timeout(self) -> None:
        subscribed = asyncio.Event()
        with (
            patch.object(chat_stream, "ARTIFACT_FORWARDER_SUBSCRIBE_TIMEOUT", 0.01),
            patch.object(chat_stream, "log") as log_mock,
        ):
            await _wait_for_artifact_forwarder(subscribed, "s1")
        log_mock.warning.assert_called_once_with(
            f"{LogTag.CHAT} Stream artifact forwarder subscribe timeout, seeding uploads anyway",
            stream_id="s1",
        )


class TestResolvePendingApprovalTurn:
    @contextmanager
    def _patches(
        self, *, bot: bool = True, action: str | None = None, error: Exception | None = None
    ):
        sm = _sm()
        seen_sources: list[Any] = []

        def _fake_is_bot(source: Any) -> bool:
            seen_sources.append(source)
            return bot

        with (
            patch.object(chat_stream, "is_bot_platform", side_effect=_fake_is_bot),
            patch.object(
                chat_stream, "resolve_pending_from_message", new_callable=AsyncMock
            ) as resolve,
            patch.object(chat_stream, "stream_manager", sm),
            patch.object(chat_stream, "_persist_turn", new_callable=AsyncMock) as persist,
            patch.object(chat_stream, "log") as log_mock,
        ):
            if error is not None:
                resolve.side_effect = error
            else:
                resolve.return_value = action
            yield resolve, sm, persist, log_mock, seen_sources

    async def test_non_bot_source_never_runs_classifier(self) -> None:
        """Web/mobile/desktop render real Approve/Deny buttons — a click is the
        source of truth, so no LLM guesses intent on those clients."""
        with self._patches(bot=False) as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                _body(), USER, "conv-1", "s1", _StreamState(), "web"
            )

        assert handled is False
        resolve.assert_not_awaited()
        assert seen == ["web"]  # the actual source is what's classified

    async def test_bot_without_user_id_returns_false(self) -> None:
        with self._patches() as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                _body(), {}, "conv-1", "s1", _StreamState(), "whatsapp"
            )

        assert handled is False
        resolve.assert_not_awaited()

    async def test_bot_with_empty_message_returns_false(self) -> None:
        body = _body(message="", messages=[{"role": "user", "content": ""}])
        with self._patches() as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                body, USER, "conv-1", "s1", _StreamState(), "whatsapp"
            )

        assert handled is False
        resolve.assert_not_awaited()

    async def test_classifier_failure_falls_back_to_normal_turn(self) -> None:
        with self._patches(error=RuntimeError("classifier down")) as (
            resolve,
            sm,
            persist,
            log_mock,
            seen,
        ):
            handled = await _resolve_pending_approval_turn(
                _body(), USER, "conv-1", "s1", _StreamState(), "whatsapp"
            )

        assert handled is False
        log_mock.error.assert_called_once_with(
            f"{LogTag.HIL} Pending-approval check failed; running a normal turn",
            error="classifier down",
            error_type="RuntimeError",
            conversation_id="conv-1",
        )
        sm.publish_chunk.assert_not_awaited()
        persist.assert_not_awaited()

    @pytest.mark.parametrize("action", [None, "needs more context"])
    async def test_non_approval_classification_returns_false(self, action: str | None) -> None:
        with self._patches(action=action) as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                _body(), USER, "conv-1", "s1", _StreamState(), "whatsapp"
            )

        assert handled is False
        sm.publish_chunk.assert_not_awaited()
        persist.assert_not_awaited()

    async def test_approve_acks_streams_and_persists(self) -> None:
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
            {"role": "user", "content": "yes please"},
        ]
        body = _body(message="yes please", messages=messages)
        state = _StreamState()
        with self._patches(action="approve") as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                body, USER, "conv-1", "s1", state, "whatsapp"
            )

        assert handled is True
        # Classifier gets the prior turns only (trailing user message dropped).
        resolve.assert_awaited_once_with("conv-1", "u1", "yes please", messages[:-1])
        assert state.complete_message == HIL_ACK_APPROVED
        assert state.turn_completed_at is not None
        assert state.turn_completed_at.tzinfo is not None  # UTC-aware, not naive
        sm.publish_chunk.assert_awaited()
        assert sm.publish_chunk.await_args_list == [
            call("s1", format_sse_response(HIL_ACK_APPROVED)),
            call(
                "s1",
                format_sse_data(
                    MainResponseCompleteFrame(main_response_complete=True).model_dump(
                        exclude_none=True
                    )
                ),
            ),
            call("s1", "data: [DONE]\n\n"),
        ]
        persist.assert_awaited_once_with("s1", body, USER, "conv-1", state)
        sm.complete_stream.assert_awaited_once_with("s1")

    async def test_deny_acks_with_denied_message(self) -> None:
        state = _StreamState()
        with self._patches(action="deny") as (resolve, sm, persist, log_mock, seen):
            handled = await _resolve_pending_approval_turn(
                _body(), USER, "conv-1", "s1", state, "telegram"
            )

        assert handled is True
        assert state.complete_message == HIL_ACK_DENIED
        assert sm.publish_chunk.await_args_list[0] == call(
            "s1", format_sse_response(HIL_ACK_DENIED)
        )


class TestPersistTurn:
    async def _persist(
        self,
        state: _StreamState,
        body: MessageRequestWithHistory | None = None,
        recovered: tuple[str, dict[str, Any]] = ("recovered text", {"tool_data": []}),
    ) -> tuple[AsyncMock, AsyncMock]:
        with (
            patch.object(chat_stream, "recover_stream_state", new_callable=AsyncMock) as recover,
            patch.object(chat_stream, "save_conversation_async", new_callable=AsyncMock) as save,
        ):
            recover.return_value = recovered
            await _persist_turn("s1", body or _body(), USER, "conv-1", state)
        return recover, save

    async def test_saves_recovered_state_with_exact_args(self) -> None:
        state = _StreamState()
        state.user_message_id = "um-1"
        state.bot_message_id = "bm-1"
        state.turn_completed_at = datetime(2026, 1, 1, tzinfo=UTC)
        body = _body()

        recover, save = await self._persist(state, body)

        recover.assert_awaited_once_with("s1", "", {"tool_data": []})
        save.assert_awaited_once()
        kwargs = save.await_args.kwargs
        assert kwargs["body"] is body
        assert kwargs["user"] == USER
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["complete_message"] == "recovered text"
        assert kwargs["tool_data"] == {"tool_data": []}
        assert kwargs["metadata"] == {}
        assert kwargs["user_message_id"] == "um-1"
        assert kwargs["bot_message_id"] == "bm-1"
        assert kwargs["bot_timestamp"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert kwargs["error"] is None
        assert kwargs["follow_up_actions"] is None
        assert state.saved is True

    async def test_error_and_follow_ups_ride_along(self) -> None:
        state = _StreamState()
        state.error = "boom"
        state.follow_up_actions = ["Draft a reply"]

        _, save = await self._persist(state)

        kwargs = save.await_args.kwargs
        assert kwargs["error"] == "boom"
        assert kwargs["follow_up_actions"] == ["Draft a reply"]

    async def test_empty_error_stays_none_not_empty_string(self) -> None:
        state = _StreamState()
        _, save = await self._persist(state)

        assert save.await_args.kwargs["error"] is None
        assert save.await_args.kwargs["complete_message"] == "recovered text"

    async def test_outputs_todo_and_subagent_groups_land_in_saved_tool_data(self) -> None:
        """Every accumulator shaping step must run before the save: the tool
        output is joined onto its card, the todo snapshot rides as a tool entry,
        and subagent start/end pairs are grouped (raw markers popped)."""
        state = _StreamState()
        state.tool_outputs = {"tc-1": "search output"}
        state.todo_progress_accumulated = {"executor": {"progress": 0.5}}
        recovered = (
            "recovered text",
            {
                "tool_data": [
                    {
                        "tool_name": "tool_calls_data",
                        "data": {"tool_call_id": "tc-1"},
                    }
                ],
                "subagent_starts": {"sa-1": {"subagent_name": "researcher"}},
                "subagent_ends": {"sa-1": {"duration_ms": 10}},
            },
        )

        _, save = await self._persist(state, recovered=recovered)

        saved = save.await_args.kwargs["tool_data"]
        entries = saved["tool_data"]
        assert entries[0]["data"]["output"] == "search output"
        assert any(e["tool_name"] == "todo_progress" for e in entries)
        assert any(e["tool_name"] == "subagent_group" for e in entries)
        assert "subagent_starts" not in saved
        assert "subagent_ends" not in saved


class TestRunChatStream:
    def _patches(
        self, *, pending: bool = False, consume_error: Exception | None = None
    ) -> dict[str, Any]:
        sm = _sm()
        return {
            "sm": sm,
            "register": MagicMock(return_value=asyncio.Event()),
            "log_context": MagicMock(),
            "publish_init": AsyncMock(),
            "resolve": AsyncMock(return_value=pending),
            "start_desc": MagicMock(return_value=None),
            "consume": (
                AsyncMock(side_effect=consume_error)
                if consume_error is not None
                else AsyncMock(return_value=None)
            ),
            "persist": AsyncMock(),
            "attach": AsyncMock(),
            "finalize_desc": AsyncMock(),
            "handle_error": AsyncMock(return_value="user error text"),
            "finalize": AsyncMock(),
            "schedule_touch": AsyncMock(),
            "forward": AsyncMock(),
            "wait_forwarder": AsyncMock(),
            "usage_callback_class": MagicMock(return_value=MagicMock(usage_metadata={})),
        }

    @contextmanager
    def _enter_patches(self, m: dict[str, Any]):
        with (
            patch.object(chat_stream, "stream_manager", m["sm"]),
            patch.object(chat_stream, "register_executor_capture", m["register"]),
            patch.object(chat_stream, "_set_stream_log_context", m["log_context"]),
            patch.object(chat_stream, "_publish_init_chunk", m["publish_init"]),
            patch.object(chat_stream, "_resolve_pending_approval_turn", m["resolve"]),
            patch.object(chat_stream, "_start_description_task", m["start_desc"]),
            patch.object(chat_stream, "_consume_agent_stream", m["consume"]),
            patch.object(chat_stream, "_persist_turn", m["persist"]),
            patch.object(chat_stream, "_attach_executor_tool_data", m["attach"]),
            patch.object(chat_stream, "_finalize_description", m["finalize_desc"]),
            patch.object(chat_stream, "_handle_stream_error", m["handle_error"]),
            patch.object(chat_stream, "_finalize_stream", m["finalize"]),
            patch.object(chat_stream, "schedule_last_active_touch", m["schedule_touch"]),
            patch.object(chat_stream, "forward_artifact_events", m["forward"]),
            patch.object(
                chat_stream.FileService, "seed_uploads", new_callable=AsyncMock
            ) as seed_uploads,
            patch.object(chat_stream, "_wait_for_artifact_forwarder", m["wait_forwarder"]),
            patch.object(chat_stream, "UsageMetadataCallbackHandler", m["usage_callback_class"]),
        ):
            yield seed_uploads

    async def test_happy_path_phases_in_order(self) -> None:
        m = self._patches()
        order: list[str] = []
        m["persist"].side_effect = lambda *a, **k: order.append("persist")
        m["attach"].side_effect = lambda *a, **k: order.append("attach")
        description_task = asyncio.create_task(_coro("Great title"))
        await description_task
        m["start_desc"].return_value = description_task
        m["consume"].return_value = description_task
        usage = {"gpt-4": {"input_tokens": 1, "output_tokens": 1}}
        m["usage_callback_class"].return_value.usage_metadata = usage
        body = _body(turn_id="tid-1")
        user = {"user_id": "u1"}

        with self._enter_patches(m) as seed_uploads:
            await _run_chat_stream("s1", body, user, "conv-1", "web")

        m["register"].assert_called_once_with("s1", voice_mode=False)
        m["log_context"].assert_called_once_with(body, "u1", "conv-1", "s1", False)
        state = m["publish_init"].await_args.args[4]
        m["publish_init"].assert_awaited_once_with(body, user, "conv-1", "s1", state, False)
        assert state.user_message_id == "tid-1"  # client turn_id IS the user message id
        m["resolve"].assert_awaited_once_with(body, user, "conv-1", "s1", state, "web")
        m["schedule_touch"].assert_called_once_with("u1", "conv-1")
        m["wait_forwarder"].assert_not_awaited()
        seed_uploads.assert_not_awaited()
        m["start_desc"].assert_called_once_with(False, body, "conv-1", user)
        m["consume"].assert_awaited_once()
        consume_args = m["consume"].await_args.args
        assert consume_args[:5] == (body, user, "conv-1", "s1", "web")
        assert consume_args[5] is m["usage_callback_class"].return_value
        assert consume_args[6] is description_task
        assert consume_args[7] is state
        assert state.usage_metadata == usage
        assert order == ["persist", "attach"]
        m["persist"].assert_awaited_once_with("s1", body, user, "conv-1", state)
        m["attach"].assert_awaited_once_with("s1", body, user, "conv-1", state)
        m["finalize_desc"].assert_awaited_once_with(description_task, "s1")
        assert state.turn_completed_at is not None
        assert state.turn_completed_at.tzinfo is not None  # UTC-aware, not naive
        expected_complete = format_sse_data(
            MainResponseCompleteFrame(main_response_complete=True, usage=usage).model_dump(
                exclude_none=True
            )
        )
        assert m["sm"].publish_chunk.await_args_list == [
            call("s1", expected_complete),
            call("s1", "data: [DONE]\n\n"),
        ]
        m["sm"].complete_stream.assert_awaited_once_with("s1")
        forwarder_subscribed = m["forward"].call_args.kwargs["subscribed"]
        assert isinstance(forwarder_subscribed, asyncio.Event)
        m["forward"].assert_called_once_with(
            "u1", "conv-1", "s1", state.bot_message_id, "web", subscribed=forwarder_subscribed
        )
        m["finalize"].assert_awaited_once()
        finalize_args = m["finalize"].await_args.args
        assert finalize_args[:4] == ("s1", body, user, "conv-1")
        assert finalize_args[4] is state
        assert isinstance(finalize_args[5], asyncio.Task)  # artifact forwarder task

    async def test_pending_approval_handled_ends_turn_before_agent(self) -> None:
        m = self._patches(pending=True)

        with self._enter_patches(m):
            await _run_chat_stream("s1", _body(), {"user_id": "u1"}, "conv-1", None)

        m["publish_init"].assert_awaited_once()  # runs before the approval check
        m["consume"].assert_not_awaited()
        m["persist"].assert_not_awaited()
        m["attach"].assert_not_awaited()
        m["sm"].publish_chunk.assert_not_awaited()
        m["sm"].complete_stream.assert_not_awaited()
        m["finalize"].assert_awaited_once()

    async def test_agent_failure_sets_state_error_and_still_finalizes(self) -> None:
        m = self._patches(consume_error=RuntimeError("boom"))

        with self._enter_patches(m):
            await _run_chat_stream("s1", _body(), {"user_id": "u1"}, "conv-1", None)

        m["handle_error"].assert_awaited_once_with("s1", m["consume"].side_effect)
        m["sm"].publish_chunk.assert_not_awaited()  # no complete frame on failure
        m["sm"].complete_stream.assert_not_awaited()
        m["persist"].assert_not_awaited()  # happy-path save skipped
        m["finalize"].assert_awaited_once()
        assert m["finalize"].await_args.args[4].error == "user error text"

    async def test_new_conversation_seeds_uploads_after_forwarder_subscribed(self) -> None:
        m = self._patches()
        body = _body(
            conversation_id=None,
            fileData=[FileData(fileId="f1", url="http://x/1.png", filename="1.png")],
        )
        user = {"user_id": "u1"}

        with self._enter_patches(m) as seed_uploads:
            await _run_chat_stream("s1", body, user, "conv-1", None)

        m["log_context"].assert_called_once_with(body, "u1", "conv-1", "s1", True)
        m["publish_init"].assert_awaited_once_with(
            body, user, "conv-1", "s1", m["publish_init"].await_args.args[4], True
        )
        m["wait_forwarder"].assert_awaited_once()
        subscribed = m["wait_forwarder"].await_args.args[0]
        assert isinstance(subscribed, asyncio.Event)
        assert m["wait_forwarder"].await_args.args[1] == "s1"
        seed_uploads.assert_awaited_once_with(body.fileData, "u1", "conv-1")

    async def test_voice_mode_and_anonymous_user_skip_housekeeping(self) -> None:
        m = self._patches()
        body = _body(voice_mode=True)

        with self._enter_patches(m) as seed_uploads:
            await _run_chat_stream("s1", body, {}, "conv-1", "whatsapp")

        m["register"].assert_called_once_with("s1", voice_mode=True)
        m["log_context"].assert_called_once_with(body, None, "conv-1", "s1", False)
        m["resolve"].assert_awaited_once()
        assert m["resolve"].await_args.args[5] == "whatsapp"  # source flows through
        m["schedule_touch"].assert_not_called()
        m["forward"].assert_not_called()
        seed_uploads.assert_not_awaited()
        m["consume"].assert_awaited_once()
        assert m["consume"].await_args.args[4] == "whatsapp"

    async def test_existing_conversation_with_files_never_seeds(self) -> None:
        """Uploads are seeded ONLY on the new-conversation branch — an existing
        conversation's files were already seeded at creation time."""
        m = self._patches()
        body = _body(fileData=[FileData(fileId="f1", url="http://x/1.png", filename="1.png")])

        with self._enter_patches(m) as seed_uploads:
            await _run_chat_stream("s1", body, {"user_id": "u1"}, "conv-1", None)

        seed_uploads.assert_not_awaited()
        m["wait_forwarder"].assert_not_awaited()

    async def test_empty_usage_publishes_complete_frame_without_usage_key(self) -> None:
        """With no usage recorded, the frame must omit usage entirely
        (exclude_none) — a null usage key would break strict parsers."""
        m = self._patches()
        body = _body()

        with self._enter_patches(m):
            await _run_chat_stream("s1", body, {"user_id": "u1"}, "conv-1", None)

        expected_complete = format_sse_data(
            MainResponseCompleteFrame(main_response_complete=True).model_dump(exclude_none=True)
        )
        assert m["sm"].publish_chunk.await_args_list == [
            call("s1", expected_complete),
            call("s1", "data: [DONE]\n\n"),
        ]

    async def test_anonymous_user_teardown_runs_without_artifact_task(self) -> None:
        """With no user_id the artifact forwarder is never spawned, so finalize
        must receive None — a non-None default would crash teardown ("" has no
        cancel()). This runs the REAL _finalize_stream to pin that contract."""
        m = self._patches()
        body = _body(
            conversation_id=None,
            fileData=[FileData(fileId="f1", url="http://x/1.png", filename="1.png")],
        )
        with (
            patch.object(chat_stream, "stream_manager", m["sm"]),
            patch.object(chat_stream, "register_executor_capture", m["register"]),
            patch.object(chat_stream, "_set_stream_log_context", m["log_context"]),
            patch.object(chat_stream, "_publish_init_chunk", m["publish_init"]),
            patch.object(chat_stream, "_resolve_pending_approval_turn", m["resolve"]),
            patch.object(chat_stream, "_start_description_task", m["start_desc"]),
            patch.object(chat_stream, "_consume_agent_stream", m["consume"]),
            patch.object(chat_stream, "_persist_turn", m["persist"]),
            patch.object(chat_stream, "_attach_executor_tool_data", m["attach"]),
            patch.object(chat_stream, "_finalize_description", m["finalize_desc"]),
            patch.object(chat_stream, "_handle_stream_error", m["handle_error"]),
            patch.object(chat_stream, "schedule_last_active_touch", m["schedule_touch"]),
            patch.object(chat_stream, "forward_artifact_events", m["forward"]),
            patch.object(
                chat_stream.FileService, "seed_uploads", new_callable=AsyncMock
            ) as seed_uploads,
            patch.object(chat_stream, "_wait_for_artifact_forwarder", m["wait_forwarder"]),
            patch.object(chat_stream, "UsageMetadataCallbackHandler", m["usage_callback_class"]),
            patch.object(chat_stream, "teardown_executor_capture") as teardown,
            patch.object(chat_stream, "flush_fs_metrics", return_value={}),
            patch.object(chat_stream, "log"),
        ):
            await _run_chat_stream("s1", body, {}, "conv-1", "whatsapp")

        m["schedule_touch"].assert_not_called()
        m["forward"].assert_not_called()
        seed_uploads.assert_not_awaited()
        # Happy-path save and attach are mocked, so saved stays False and the
        # real finalize runs the fallback persist + attach — twice each total.
        assert m["persist"].await_count == 2
        assert m["attach"].await_count == 2
        teardown.assert_called_once_with("s1")
        m["sm"].cleanup.assert_awaited_once_with("s1")
        m["handle_error"].assert_not_awaited()


class TestRunChatStreamBackground:
    @pytest.mark.parametrize("source", [None, "telegram"])
    async def test_wraps_and_delegates_to_inner_run(self, source: str | None) -> None:
        body = _body()
        user = {"user_id": "u1"}
        cm = MagicMock()
        cm.__aenter__ = AsyncMock()
        cm.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(chat_stream, "_run_chat_stream", new_callable=AsyncMock) as inner,
            patch.object(chat_stream, "wide_task", return_value=cm) as wt,
        ):
            await run_chat_stream_background("s1", body, user, "conv-1", source)

        inner.assert_awaited_once_with(
            stream_id="s1",
            body=body,
            user=user,
            conversation_id="conv-1",
            source=source,
        )
        wt.assert_called_once_with(
            "chat_stream", trace_id=None, conversation_id="conv-1", stream_id="s1"
        )
        cm.__aenter__.assert_awaited_once()
        cm.__aexit__.assert_awaited_once()

    async def test_request_trace_id_flows_into_wide_task(self) -> None:
        """The spawning request's trace_id is inherited through the copied task
        context and MUST be handed to the wide-event boundary — a run that
        hardcodes ``trace_id=None`` orphans the ``chat_stream`` event from its
        ``http_request`` event and breaks LogQL correlation."""
        body = _body()
        user = {"user_id": "u1"}
        cm = MagicMock()
        cm.__aenter__ = AsyncMock()
        cm.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(chat_stream, "_run_chat_stream", new_callable=AsyncMock),
            patch.object(chat_stream, "wide_task", return_value=cm) as wt,
            patch.object(chat_stream, "get_trace_id", return_value="0123456789abcdef"),
        ):
            await run_chat_stream_background("s1", body, user, "conv-1", "telegram")

        wt.assert_called_once_with(
            "chat_stream",
            trace_id="0123456789abcdef",
            conversation_id="conv-1",
            stream_id="s1",
        )
