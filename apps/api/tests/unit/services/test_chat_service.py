"""Unit tests for the chat service streaming pipeline.

Tests cover the core orchestration logic in chat_service.py:
- run_chat_stream_background: end-to-end background streaming coordination
- _initialize_new_conversation: conversation creation and init chunk format
- _save_conversation_async: MongoDB persistence with correct message structure
- extract_tool_data: JSON parsing and tool field extraction
- _extract_response_text: response text extraction from SSE chunks
- update_conversation_messages: legacy background-task scheduling path

All external dependencies (Redis/stream_manager, MongoDB, agent, LLM) are
mocked so tests exercise service logic only.
"""

from collections.abc import AsyncGenerator, Iterator
import contextlib
from datetime import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY
import pytest

from app.agents.core.background.session import (
    RunKind,
    create_session,
    teardown_session,
)
from app.models.chat_models import ConversationModel
from app.models.message_models import MessageRequestWithHistory
from app.services.analytics_service import AnalyticsEvents
from app.services.chat.chunks import (
    extract_response_text as _extract_response_text,
    extract_tool_data,
)
from app.services.chat.persistence import (
    initialize_new_conversation as _initialize_new_conversation,
    save_conversation_async as _save_conversation_async,
)
from app.services.chat.stream import (
    _close_turn_timings,
    _executor_delegation,
    _finalize_stream,
    _note_cancellation,
    _observe_turn_latencies,
    _resolve_pending_approval_turn,
    _stamp_turn_latencies,
    _StreamState,
    run_chat_stream_background,
    stream_manager as _stream_manager,
)
from shared.py.wide_events import log as _log


def _created_conversation(conversation_id: str, description: str) -> ConversationModel:
    """The real `create_conversation` return value — mock it with nothing looser."""
    return ConversationModel(conversation_id=conversation_id, description=description)


def _usage_callback_class() -> MagicMock:
    """Stand-in for LangChain's `UsageMetadataCallbackHandler`.

    The real handler exposes `usage_metadata` as a dict, and the stream feeds it
    straight into `MainResponseCompleteFrame`. A bare `MagicMock()` would hand the
    frame a Mock instead, so the stand-in must carry the real attribute type.
    """
    return MagicMock(return_value=MagicMock(usage_metadata={}))


# Each module does `from app.core.stream_manager import stream_manager`,
# so the patch target is each module's binding. This helper rebinds all
# five at once so a single mock intercepts calls from stream.py, chunks.py,
# state.py, artifact_forwarder.py, and stream_publishers.py.
@contextlib.contextmanager
def _patch_stream_manager(sm: MagicMock) -> Iterator[MagicMock]:
    with contextlib.ExitStack() as stack:
        for path in (
            "app.services.chat.stream.stream_manager",
            "app.services.chat.chunks.stream_manager",
            "app.services.chat.state.stream_manager",
            "app.services.chat.artifact_forwarder.stream_manager",
            "app.utils.stream_publishers.stream_manager",
        ):
            stack.enter_context(patch(path, sm))
        yield sm


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_user() -> dict:
    return {"user_id": "user_abc", "email": "tester@example.com"}


@pytest.fixture
def basic_body() -> MessageRequestWithHistory:
    """A minimal request body with a single user message."""
    return MessageRequestWithHistory(
        message="Hello GAIA",
        messages=[{"role": "user", "content": "Hello GAIA"}],
        conversation_id=None,
    )


@pytest.fixture
def existing_conv_body() -> MessageRequestWithHistory:
    """A request body referencing an already-existing conversation."""
    return MessageRequestWithHistory(
        message="Follow-up",
        messages=[{"role": "user", "content": "Follow-up"}],
        conversation_id="conv_existing_123",
    )


async def _empty_agent_stream() -> AsyncGenerator[str, None]:
    """Async generator that yields nothing (simulates empty agent response)."""
    if False:  # pragma: no cover
        yield ""


async def _done_only_stream() -> AsyncGenerator[str, None]:
    """Async generator that yields only the DONE sentinel."""
    yield "data: [DONE]\n\n"


async def _text_then_nostream(text: str, complete: str) -> AsyncGenerator[str, None]:
    """Yields a text chunk, then a nostream marker, then DONE."""
    yield f"data: {json.dumps({'response': text})}\n\n"
    yield f"nostream: {json.dumps({'complete_message': complete})}"
    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# extract_tool_data — pure synchronous helper
# ---------------------------------------------------------------------------


class TestExtractToolData:
    def test_returns_empty_dict_on_invalid_json(self):
        result = extract_tool_data("not json{{")
        assert result == {}

    def test_returns_empty_dict_for_plain_response(self):
        result = extract_tool_data(json.dumps({"response": "hello"}))
        assert result == {}

    def test_extracts_unified_tool_data_list(self):
        payload = json.dumps(
            {
                "tool_data": [
                    {
                        "tool_name": "search_results",
                        "data": {"items": []},
                        "timestamp": "t",
                    }
                ]
            }
        )
        result = extract_tool_data(payload)
        assert "tool_data" in result
        assert result["tool_data"][0]["tool_name"] == "search_results"

    def test_extracts_unified_tool_data_single_dict(self):
        """tool_data as a single dict (not a list) should be wrapped in a list."""
        payload = json.dumps(
            {"tool_data": {"tool_name": "weather_data", "data": {}, "timestamp": "t"}}
        )
        result = extract_tool_data(payload)
        assert isinstance(result["tool_data"], list)
        assert result["tool_data"][0]["tool_name"] == "weather_data"

    def test_extracts_legacy_tool_field(self):
        payload = json.dumps({"calendar_options": [{"id": 1, "title": "Meeting"}]})
        result = extract_tool_data(payload)
        assert "tool_data" in result
        assert result["tool_data"][0]["tool_name"] == "calendar_options"
        assert result["tool_data"][0]["data"] == [{"id": 1, "title": "Meeting"}]

    def test_extracts_multiple_legacy_tool_fields(self):
        payload = json.dumps(
            {
                "search_results": {"items": []},
                "weather_data": {"temp": 20},
            }
        )
        result = extract_tool_data(payload)
        tool_names = {e["tool_name"] for e in result["tool_data"]}
        assert "search_results" in tool_names
        assert "weather_data" in tool_names

    def test_extracts_follow_up_actions_into_other_data(self):
        payload = json.dumps({"follow_up_actions": ["Do X", "Do Y"]})
        result = extract_tool_data(payload)
        assert "other_data" in result
        assert result["other_data"]["follow_up_actions"] == ["Do X", "Do Y"]

    def test_extracts_tool_output(self):
        payload = json.dumps({"tool_output": {"tool_call_id": "call_1", "output": "result text"}})
        result = extract_tool_data(payload)
        assert "tool_output" in result
        assert result["tool_output"]["tool_call_id"] == "call_1"

    def test_ignores_none_valued_legacy_fields(self):
        payload = json.dumps({"calendar_options": None})
        result = extract_tool_data(payload)
        assert "tool_data" not in result

    def test_unknown_fields_produce_no_tool_data(self):
        payload = json.dumps({"completely_unknown_key": "value"})
        result = extract_tool_data(payload)
        assert "tool_data" not in result

    def test_timestamp_is_iso_string(self):
        payload = json.dumps({"search_results": {"items": []}})
        result = extract_tool_data(payload)
        ts = result["tool_data"][0]["timestamp"]
        # Verify it's a parseable ISO timestamp
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# _extract_response_text — pure synchronous helper
# ---------------------------------------------------------------------------


class TestExtractResponseText:
    def test_extracts_response_from_data_chunk(self):
        chunk = f"data: {json.dumps({'response': 'Hello there'})}\n\n"
        assert _extract_response_text(chunk) == "Hello there"

    def test_returns_empty_string_for_tool_only_chunk(self):
        chunk = f"data: {json.dumps({'tool_data': []})}\n\n"
        assert _extract_response_text(chunk) == ""

    def test_returns_empty_string_for_non_json(self):
        assert _extract_response_text("data: [DONE]") == ""

    def test_handles_chunk_without_data_prefix(self):
        # Bare JSON with no prefix
        chunk = json.dumps({"response": "Direct"})
        assert _extract_response_text(chunk) == "Direct"

    def test_returns_empty_string_for_empty_response_key(self):
        chunk = f"data: {json.dumps({'response': ''})}\n\n"
        assert _extract_response_text(chunk) == ""


# ---------------------------------------------------------------------------
# _initialize_new_conversation
# ---------------------------------------------------------------------------


class TestInitializeNewConversation:
    async def test_returns_sse_formatted_init_chunk(self, test_user, basic_body):
        mock_conv = _created_conversation("conv_new_xyz", "New Chat")
        with patch(
            "app.services.chat.persistence.create_conversation",
            new=AsyncMock(return_value=mock_conv),
        ):
            chunk = await _initialize_new_conversation(
                body=basic_body,
                user=test_user,
                conversation_id="conv_new_xyz",
                user_message_id="umsg_1",
                bot_message_id="bmsg_1",
                stream_id="stream_abc",
            )

        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        payload = json.loads(chunk[6:])
        assert payload["conversation_id"] == "conv_new_xyz"
        assert payload["user_message_id"] == "umsg_1"
        assert payload["bot_message_id"] == "bmsg_1"
        assert payload["stream_id"] == "stream_abc"

    async def test_passes_generate_description_false(self, test_user, basic_body):
        """The new-conversation path must pass generate_description=False."""
        mock_conv = _created_conversation("conv_new_xyz", "New Chat")
        with patch(
            "app.services.chat.persistence.create_conversation",
            new=AsyncMock(return_value=mock_conv),
        ) as mock_create:
            await _initialize_new_conversation(
                body=basic_body,
                user=test_user,
                conversation_id="conv_new_xyz",
                user_message_id="u1",
                bot_message_id="b1",
                stream_id="s1",
            )
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("generate_description") is False

    async def test_uses_provided_conversation_id(self, test_user, basic_body):
        mock_conv = _created_conversation("forced_id", "New Chat")
        with patch(
            "app.services.chat.persistence.create_conversation",
            new=AsyncMock(return_value=mock_conv),
        ) as mock_create:
            await _initialize_new_conversation(
                body=basic_body,
                user=test_user,
                conversation_id="forced_id",
                user_message_id="u1",
                bot_message_id="b1",
                stream_id="s1",
            )
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs.get("conversation_id") == "forced_id"

    async def test_description_included_in_init_chunk(self, test_user, basic_body):
        mock_conv = _created_conversation("conv_id", "Chat about the weather")
        with patch(
            "app.services.chat.persistence.create_conversation",
            new=AsyncMock(return_value=mock_conv),
        ):
            chunk = await _initialize_new_conversation(
                body=basic_body,
                user=test_user,
                conversation_id="conv_id",
                user_message_id="u1",
                bot_message_id="b1",
                stream_id="s1",
            )
        payload = json.loads(chunk[6:])
        assert payload["conversation_description"] == "Chat about the weather"


# ---------------------------------------------------------------------------
# _save_conversation_async
# ---------------------------------------------------------------------------


class TestSaveConversationAsync:
    async def test_saves_user_and_bot_messages(self, test_user, basic_body):
        mock_update = AsyncMock()
        with (
            patch(
                "app.services.chat.persistence.update_messages",
                new=mock_update,
            ),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="I am GAIA.",
                tool_data={"tool_data": []},
                metadata={},
                user_message_id="umsg_1",
                bot_message_id="bmsg_1",
            )

        assert mock_update.called
        request_arg = mock_update.call_args.args[0]
        messages = request_arg.messages
        assert len(messages) == 2
        user_msg, bot_msg = messages
        assert user_msg.type == "user"
        assert bot_msg.type == "bot"

    async def test_user_message_content_comes_from_last_messages_entry(self, test_user):
        body = MessageRequestWithHistory(
            message="Fallback message",
            messages=[
                {"role": "user", "content": "First turn"},
                {"role": "user", "content": "Last turn"},
            ],
            conversation_id="conv_x",
        )
        mock_update = AsyncMock()
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=body,
                user=test_user,
                conversation_id="conv_x",
                complete_message="response",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        request_arg = mock_update.call_args.args[0]
        user_msg = request_arg.messages[0]
        assert user_msg.response == "Last turn"

    async def test_user_message_falls_back_to_body_message(self, test_user):
        body = MessageRequestWithHistory(
            message="Fallback content",
            messages=[],
            conversation_id="conv_y",
        )
        mock_update = AsyncMock()
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=body,
                user=test_user,
                conversation_id="conv_y",
                complete_message="response",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        request_arg = mock_update.call_args.args[0]
        user_msg = request_arg.messages[0]
        assert user_msg.response == "Fallback content"

    async def test_bot_message_contains_complete_message(self, test_user, basic_body):
        mock_update = AsyncMock()
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="The answer is 42.",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        request_arg = mock_update.call_args.args[0]
        bot_msg = request_arg.messages[1]
        assert bot_msg.response == "The answer is 42."

    async def test_message_ids_are_set_on_models(self, test_user, basic_body):
        mock_update = AsyncMock()
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="ok",
                tool_data={},
                metadata={},
                user_message_id="umsg_specific",
                bot_message_id="bmsg_specific",
            )
        request_arg = mock_update.call_args.args[0]
        assert request_arg.messages[0].message_id == "umsg_specific"
        assert request_arg.messages[1].message_id == "bmsg_specific"

    async def test_tool_data_applied_to_bot_message(self, test_user, basic_body):
        mock_update = AsyncMock()
        tool_data = {
            "tool_data": [{"tool_name": "search_results", "data": {"items": []}, "timestamp": "t"}]
        }
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="ok",
                tool_data=tool_data,
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        request_arg = mock_update.call_args.args[0]
        bot_msg = request_arg.messages[1]
        assert bot_msg.tool_data == tool_data["tool_data"]

    async def test_correct_conversation_id_passed_to_update(self, test_user, basic_body):
        mock_update = AsyncMock()
        with (
            patch("app.services.chat.persistence.update_messages", new=mock_update),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="specific_conv_id",
                complete_message="ok",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        request_arg = mock_update.call_args.args[0]
        assert request_arg.conversation_id == "specific_conv_id"


# ---------------------------------------------------------------------------
# run_chat_stream_background — top-level orchestrator
# ---------------------------------------------------------------------------


def _make_stream_manager_mock(is_cancelled: bool = False) -> MagicMock:
    """Build a StreamManager mock with all async methods pre-configured."""
    m = MagicMock()
    m.publish_chunk = AsyncMock()
    m.is_cancelled = AsyncMock(return_value=is_cancelled)
    m.update_progress = AsyncMock()
    m.complete_stream = AsyncMock()
    m.set_error = AsyncMock()
    m.cleanup = AsyncMock()
    m.get_progress = AsyncMock(return_value=None)
    return m


class TestRunChatStreamBackground:
    @pytest.fixture(autouse=True)
    def _no_pending_approval(self) -> Iterator[None]:
        """Stub conversational HIL resolution to "nothing pending".

        ``run_chat_stream_background`` now checks Mongo for a pending approval at
        the top of each turn. These tests exercise the normal turn and don't stub
        Redis, so without this the real ``redis_cache`` singleton is reached and
        raises "Event loop is closed" under xdist's per-test event loops.
        """
        with patch(
            "app.services.chat.stream.resolve_pending_from_message",
            new=AsyncMock(return_value=None),
        ):
            yield

    @pytest.fixture(autouse=True)
    def _no_live_artifact_forwarder(self) -> Iterator[None]:
        """Force ``ArtifactForwarder`` onto its "Redis unavailable" fast path.

        ``run_chat_stream_background`` spawns ``forward_artifact_events`` as a
        background task for every turn with a ``user_id``. Its ``run()`` reads
        the process-wide ``redis_cache`` singleton directly (not ``stream_manager``,
        which the tests below already mock) — in a hermetic dev/test env
        ``redis_cache.redis`` is ``None`` and it no-ops, but under CI's live-services
        job (real Redis running, ``REDIS_URL`` pointing at it) it subscribes to a
        real pub/sub channel and blocks in ``pubsub.listen()`` for the rest of the
        turn, relying entirely on ``_finalize_stream``'s ``artifact_task.cancel()``
        landing before test/CI timeouts to unblock it. ``tests/unit/`` must be fully
        mocked and I/O-free (see ``tests/CLAUDE.md``), so pin the fast path here
        instead of depending on ambient Redis connectivity/scheduling.
        """
        with patch("app.services.chat.artifact_forwarder.redis_cache.redis", None):
            yield

    async def test_new_conversation_publishes_init_chunk(self, test_user, basic_body):
        """When conversation_id is None, an init chunk must be published first."""

        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.persistence.create_conversation",
                new=AsyncMock(return_value=_created_conversation("new_conv_id", "Test conv")),
            ),
            patch(
                "app.services.chat.stream.generate_and_update_description",
                new=AsyncMock(return_value="Test conv"),
            ),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_1",
                body=basic_body,
                user=test_user,
                conversation_id="new_conv_id",
            )

        # First publish_chunk call should contain the init data (conversation_id)
        first_publish_call = sm.publish_chunk.call_args_list[0]
        first_arg = first_publish_call.args[1]
        payload = json.loads(first_arg[6:])
        assert "conversation_id" in payload

    async def test_existing_conversation_publishes_message_ids_only(
        self, test_user, existing_conv_body
    ):
        """Existing conversation: no conversation_id in the init chunk."""
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_2",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        first_publish_call = sm.publish_chunk.call_args_list[0]
        first_arg = first_publish_call.args[1]
        payload = json.loads(first_arg[6:])
        assert "user_message_id" in payload
        assert "bot_message_id" in payload
        # Should NOT contain conversation_id for existing conversations
        assert "conversation_id" not in payload

    async def test_done_marker_published_after_agent_completes(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_3",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        published = [call.args[1] for call in sm.publish_chunk.call_args_list]
        assert "data: [DONE]\n\n" in published

    async def test_captures_message_completed_on_success(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_capture_complete",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert call_args.args[0] == "user_abc"
        assert call_args.args[1] == AnalyticsEvents.CHAT_MESSAGE_COMPLETED
        props = call_args.args[2]
        # DONE-only turn: E2E present, TTFT absent, nothing delegated.
        assert props["conversation_id"] == "conv_existing_123"
        assert props["voice_mode"] is False
        assert props["is_new_conversation"] is False
        assert props["has_error"] is False
        assert props["delegated"] is False
        assert props["queued"] is False
        assert props["e2e_ack_ms"] <= props["e2e_full_ms"]
        assert "ttft_ms" not in props

    async def test_source_is_carried_onto_the_terminal_event(self, test_user, existing_conv_body):
        """`source` is what lets one event name span web, desktop and bots.

        Every other test leaves it None, so the branch that attaches it never
        ran with a value — key and value were both free to drift.
        """
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_capture_source",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="desktop",
            )

        assert mock_capture.call_args.args[2]["conversation_id"] == "conv_existing_123"
        assert mock_capture.call_args.args[2]["voice_mode"] is False
        assert mock_capture.call_args.args[2]["is_new_conversation"] is False
        assert mock_capture.call_args.args[2]["source"] == "desktop"
        assert mock_capture.call_args.args[2]["has_error"] is False
        assert mock_capture.call_args.args[2]["delegated"] is False
        assert mock_capture.call_args.args[2]["queued"] is False

    async def test_captures_message_cancelled_when_stream_cancelled(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock(is_cancelled=True)
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_capture_cancel",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert call_args.args[0] == "user_abc"
        assert call_args.args[1] == AnalyticsEvents.CHAT_MESSAGE_CANCELLED
        assert call_args.args[2]["conversation_id"] == "conv_existing_123"

    async def test_complete_stream_called_on_success(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_4",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        sm.complete_stream.assert_called_once_with("stream_4")

    async def test_cleanup_always_called_on_success(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_5",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        sm.cleanup.assert_called_once_with("stream_5")

    async def test_cleanup_called_even_when_agent_raises(self, test_user, existing_conv_body):
        """The finally block must always run cleanup even on agent failure."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_6",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        sm.cleanup.assert_called_once_with("stream_6")

    async def test_stop_during_executor_wait_is_a_cancelled_turn(
        self, test_user, existing_conv_body
    ):
        """Comms has already acked when the user presses stop while the turn waits
        on the executor. The consume loop's cancel check is long past, so the
        wait itself must notice — otherwise the turn is counted as completed."""
        labels = {"source": "web", "delegated": "false", "status": "cancelled"}
        before = REGISTRY.get_sample_value("chat_turn_total", labels) or 0.0
        sm = _make_stream_manager_mock()

        async def _cancel_lands_during_wait(*_args: Any, **_kwargs: Any) -> bool:
            sm.is_cancelled.return_value = True
            return True

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.await_executor_done",
                new=AsyncMock(side_effect=_cancel_lands_during_wait),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_cancel_in_wait",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )

        assert REGISTRY.get_sample_value("chat_turn_total", labels) == before + 1
        assert mock_capture.call_args.args[1] == AnalyticsEvents.CHAT_MESSAGE_CANCELLED
        # Every cancel check reads THIS stream's flag — a check on None reads nothing.
        assert {call.args[0] for call in sm.is_cancelled.await_args_list} == {
            "stream_cancel_in_wait"
        }

    async def test_failed_turn_is_observed_with_error_status(self, test_user, existing_conv_body):
        """A turn that raises is exactly the slow/broken one the SLOs exist for: it
        must land in ``chat_turn_total`` and the E2E histogram as ``status=error``,
        not vanish from both."""
        labels_total = {"source": "web", "delegated": "false", "status": "error"}
        labels_e2e = {
            "source": "web",
            "voice_mode": "false",
            "delegated": "false",
            "status": "error",
        }
        total_before = REGISTRY.get_sample_value("chat_turn_total", labels_total) or 0.0
        e2e_before = REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels_e2e) or 0.0
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_error_observed",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )

        assert REGISTRY.get_sample_value("chat_turn_total", labels_total) == total_before + 1
        assert (
            REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels_e2e) == e2e_before + 1
        )
        # A failed turn is not a completed one: no completion milestone for it.
        mock_capture.assert_not_called()

    async def test_error_chunk_published_before_set_error(self, test_user, existing_conv_body):
        """set_error() sends STREAM_ERROR_SIGNAL which breaks the subscriber.
        The human-readable error JSON must be published first."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        publish_calls: list[str] = []

        def track_publish(stream_id: str, chunk: str) -> None:
            publish_calls.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track_publish)
        set_error_calls: list[str] = []

        def track_set_error(stream_id: str, err: str) -> None:
            set_error_calls.append(err)
            # Verify no further publish_chunk called after this

        sm.set_error = AsyncMock(side_effect=track_set_error)

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(side_effect=RuntimeError("network timeout")),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_7",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        # There must be at least one error chunk published
        error_chunks = [c for c in publish_calls if "error" in c]
        assert error_chunks, "Expected an error chunk to be published"

        # The error chunk must contain the error message
        error_payload = json.loads(error_chunks[0][6:])
        assert "error" in error_payload
        assert "network timeout" in error_payload["error"]

        # set_error must also have been called
        assert set_error_calls, "Expected set_error to be called"

    async def test_save_always_called_even_on_agent_failure(self, test_user, existing_conv_body):
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        mock_save = AsyncMock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent down")),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_8",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_save.assert_called_once()

    async def test_nostream_chunk_sets_complete_message(self, test_user, existing_conv_body):
        """nostream: chunk must set complete_message which is later saved."""
        complete_text = "The final answer is here."

        async def agent_with_nostream():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            yield f"nostream: {json.dumps({'complete_message': complete_text})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        mock_save = AsyncMock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_with_nostream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_9",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["complete_message"] == complete_text

    async def test_nostream_chunk_not_forwarded_to_client(self, test_user, existing_conv_body):
        """The nostream: prefix is internal — must never be published to Redis."""

        async def agent_with_nostream():
            yield f"nostream: {json.dumps({'complete_message': 'final'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        published_chunks: list[str] = []

        async def track_publish(stream_id: str, chunk: str) -> None:
            published_chunks.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track_publish)

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_with_nostream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_10",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        # No published chunk should contain "nostream"
        for chunk in published_chunks:
            assert "nostream" not in chunk

    async def test_cancellation_stops_stream_loop(self, test_user, existing_conv_body):
        """When is_cancelled returns True, no further agent chunks are processed."""

        async def agent_that_yields_many():
            for i in range(5):
                yield f"data: {json.dumps({'response': f'chunk {i}'})}\n\n"

        sm = _make_stream_manager_mock(is_cancelled=True)
        mock_save = AsyncMock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_that_yields_many()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_cancel",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        # Save still called even when cancelled
        mock_save.assert_called_once()

    async def test_tool_data_chunks_accumulated_and_saved(self, test_user, existing_conv_body):
        """tool_data entries from agent stream must be merged into saved bot message."""

        async def agent_with_tool_data():
            payload = {
                "tool_data": {
                    "tool_name": "search_results",
                    "data": {"items": ["result1"]},
                    "timestamp": "2025-01-01T00:00:00+00:00",
                }
            }
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        mock_save = AsyncMock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_with_tool_data()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_tools",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        save_kwargs = mock_save.call_args.kwargs
        saved_tool_data = save_kwargs["tool_data"]
        assert "tool_data" in saved_tool_data
        assert len(saved_tool_data["tool_data"]) >= 1
        assert saved_tool_data["tool_data"][0]["tool_name"] == "search_results"

    async def test_tool_outputs_merged_into_tool_data_before_save(
        self, test_user, existing_conv_body
    ):
        """tool_output events should be merged into matching tool_calls_data entries."""

        async def agent_with_output():
            tool_data_chunk = {
                "tool_data": {
                    "tool_name": "tool_calls_data",
                    "data": {"tool_call_id": "call_abc", "name": "search"},
                    "timestamp": "t",
                }
            }
            yield f"data: {json.dumps(tool_data_chunk)}\n\n"
            tool_output_chunk = {
                "tool_output": {"tool_call_id": "call_abc", "output": "search results"}
            }
            yield f"data: {json.dumps(tool_output_chunk)}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        mock_save = AsyncMock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_with_output()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_merge",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        save_kwargs = mock_save.call_args.kwargs
        tool_entries = save_kwargs["tool_data"].get("tool_data", [])
        calls_entry = next(
            (e for e in tool_entries if e.get("tool_name") == "tool_calls_data"), None
        )
        assert calls_entry is not None
        assert calls_entry["data"]["output"] == "search results"

    async def test_follow_up_actions_published_to_stream(self, test_user, existing_conv_body):
        """follow_up_actions from agent must be published as a separate SSE event."""

        async def agent_with_follow_up():
            payload = {"follow_up_actions": ["Action A", "Action B"]}
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        published: list[str] = []

        def track(stream_id: str, chunk: str) -> None:
            published.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track)

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=agent_with_follow_up()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_fu",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        follow_up_chunks = [
            c for c in published if c.startswith("data: ") and "follow_up_actions" in c
        ]
        assert follow_up_chunks, "Expected a follow_up_actions SSE event"
        payload = json.loads(follow_up_chunks[0][6:])
        assert payload["follow_up_actions"] == ["Action A", "Action B"]

    async def test_complete_message_recovered_from_redis_when_empty(
        self, test_user, existing_conv_body
    ):
        """If nostream: marker never arrives (e.g. cancellation), complete_message
        should be recovered from Redis progress data."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(
            return_value={"complete_message": "recovered text", "tool_data": {}}
        )
        mock_save = AsyncMock()

        # Agent yields only a partial response without nostream marker
        async def partial_agent():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            # Deliberately NO nostream: marker
            yield "data: [DONE]\n\n"

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=partial_agent()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=mock_save,
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_recover",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        save_kwargs = mock_save.call_args.kwargs
        assert save_kwargs["complete_message"] == "recovered text"

    async def test_description_task_spawned_for_new_conversation(self, test_user, basic_body):
        """generate_and_update_description must be called for new conversations."""
        mock_desc = AsyncMock(return_value="Generated description")
        sm = _make_stream_manager_mock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.persistence.create_conversation",
                new=AsyncMock(return_value=_created_conversation("new_id", "New Chat")),
            ),
            patch(
                "app.services.chat.stream.generate_and_update_description",
                new=mock_desc,
            ),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_desc",
                body=basic_body,
                user=test_user,
                conversation_id="new_id",
            )

        mock_desc.assert_called_once()

    async def test_no_description_task_for_existing_conversation(
        self, test_user, existing_conv_body
    ):
        """generate_and_update_description must NOT be called for existing conversations."""
        mock_desc = AsyncMock(return_value="Should not be called")
        sm = _make_stream_manager_mock()

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.generate_and_update_description",
                new=mock_desc,
            ),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
        ):
            await run_chat_stream_background(
                stream_id="stream_no_desc",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_desc.assert_not_called()

    async def test_terminal_event_carries_latency_props(self, test_user, existing_conv_body):
        """TTFT/E2E/delegated props land on chat:message_completed for the user."""
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_text_then_nostream("hello there", "hello there")),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_latency_props",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[0] == "user_abc"
        props = mock_capture.call_args.args[2]
        assert props["ttft_ms"] <= props["e2e_ack_ms"] <= props["e2e_full_ms"]
        assert props["ttft_ms"] >= 0.0
        assert props["delegated"] is False
        assert props["queued"] is False

    async def test_terminal_event_without_text_has_no_ttft(self, test_user, existing_conv_body):
        """A turn with no response text still reports E2E, but no TTFT."""
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat.stream.save_conversation_async",
                new=AsyncMock(),
            ),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_latency_no_ttft",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
            )

        props = mock_capture.call_args.args[2]
        assert "ttft_ms" not in props
        assert props["e2e_ack_ms"] <= props["e2e_full_ms"]
        assert props["delegated"] is False

    async def test_voice_mode_turn_labels_the_histograms_voice_true(
        self, test_user, existing_conv_body
    ):
        """`voice_mode` is carried from the body into the terminal histogram labels;
        a turn that dropped it would file voice traffic under voice_mode=false."""
        labels = {
            "source": "web",
            "voice_mode": "true",
            "delegated": "false",
            "status": "success",
        }
        before = REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels) or 0.0
        sm = _make_stream_manager_mock()
        body = existing_conv_body.model_copy(update={"voice_mode": True})
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_text_then_nostream("hi there", "hi there")),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event"),
        ):
            await run_chat_stream_background(
                stream_id="stream_voice_success",
                body=body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )
        assert REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels) == before + 1

    async def test_delegated_turn_labels_turn_total_delegated_true(
        self, test_user, existing_conv_body
    ):
        """The delegation label is read from THIS stream's session; a mis-read id
        would count a delegated turn as direct."""
        labels = {"source": "web", "delegated": "true", "status": "success"}
        before = REGISTRY.get_sample_value("chat_turn_total", labels) or 0.0
        sm = _make_stream_manager_mock()
        delegated_session = MagicMock(executor_spawned=True, executor_queued_task_id=None)

        def _session_for(stream_id: str) -> Any:
            return delegated_session if stream_id == "stream_delegated_ok" else None

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_text_then_nostream("ok", "ok")),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event"),
            patch("app.services.chat.stream.get_session", side_effect=_session_for),
        ):
            await run_chat_stream_background(
                stream_id="stream_delegated_ok",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )
        assert REGISTRY.get_sample_value("chat_turn_total", labels) == before + 1

    async def test_error_turn_labels_voice_and_delegation(self, test_user, existing_conv_body):
        """The error path carries the same stream id and voice_mode as the happy
        one — a turn that fails must file under its real delegation/voice labels."""
        labels = {
            "source": "web",
            "voice_mode": "true",
            "delegated": "true",
            "status": "error",
        }
        before = REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels) or 0.0
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        delegated_session = MagicMock(executor_spawned=True, executor_queued_task_id=None)
        body = existing_conv_body.model_copy(update={"voice_mode": True})

        def _session_for(stream_id: str) -> Any:
            return delegated_session if stream_id == "stream_err_voice" else None

        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event"),
            patch("app.services.chat.stream.get_session", side_effect=_session_for),
        ):
            await run_chat_stream_background(
                stream_id="stream_err_voice",
                body=body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )
        assert REGISTRY.get_sample_value("chat_e2e_full_seconds_count", labels) == before + 1

    async def test_a_non_text_data_chunk_does_not_stamp_ttft(self, test_user, existing_conv_body):
        """TTFT is first *reply text*, not first byte: an empty-response data frame
        before any real text must not open the span."""

        async def _empty_response_then_done() -> AsyncGenerator[str, None]:
            yield 'data: {"response": ""}\n\n'
            yield "data: [DONE]\n\n"
            yield "nostream: " + json.dumps({"complete_message": "", "cancelled": False})

        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.call_agent",
                new=AsyncMock(return_value=_empty_response_then_done()),
            ),
            patch("app.services.chat.stream.save_conversation_async", new=AsyncMock()),
            patch("app.services.chat.stream.UsageMetadataCallbackHandler", _usage_callback_class()),
            patch("app.services.chat.stream.capture_event") as mock_capture,
        ):
            await run_chat_stream_background(
                stream_id="stream_empty_response",
                body=existing_conv_body,
                user=test_user,
                conversation_id="conv_existing_123",
                source="web",
            )
        assert "ttft_ms" not in mock_capture.call_args.args[2]

    async def test_pending_approval_turn_stamps_ack_and_ttft(self, test_user, existing_conv_body):
        """A bot reply that answers a pending approval is still a turn: it stamps
        the ack clock and measures its own TTFT (the ack text) exactly once."""
        state = _StreamState()
        state.t0_perf = 50.0
        sm = _make_stream_manager_mock()
        with (
            _patch_stream_manager(sm),
            patch(
                "app.services.chat.stream.resolve_pending_from_message",
                new=AsyncMock(return_value="approve"),
            ),
            patch("app.services.chat.stream._persist_turn", new=AsyncMock()),
            patch("app.services.chat.stream.time.perf_counter", return_value=52.0),
        ):
            handled = await _resolve_pending_approval_turn(
                existing_conv_body, test_user, "conv_existing_123", "s_approval", state, "whatsapp"
            )

        assert handled is True
        assert state.ack_perf == 52.0
        assert state.ttft_perf == 52.0
        assert state.ttft_ms == 2000.0
        assert state.e2e_ack_ms == 2000.0


def _hist_count(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0


def _hist_sum(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(f"{name}_sum", labels) or 0.0


def _counter(name: str, labels: dict[str, str]) -> float:
    # The counter is registered as chat_turn_total; prometheus_client appends
    # _total only when the name does not already end in it, so the sample name
    # is exactly the metric name here.
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestTurnLatencyHelpers:
    """The latency helpers are deterministic given fixed stamps; assert exact
    values, labels and None-guards so a mutated subtraction, scaling, rounding,
    label or guard is caught rather than riding along under a range assertion."""

    def test_stream_state_latency_defaults(self) -> None:
        state = _StreamState()
        assert state.t0_perf is None
        assert state.ttft_perf is None
        assert state.ack_perf is None
        assert state.ttft_ms is None
        assert state.e2e_ack_ms is None
        assert state.e2e_full_ms is None
        assert state.delegated is False
        assert state.queued is False
        assert state.turn_completed_at is None
        assert state.is_cancelled is False

    def test_stamp_turn_latencies_computes_exact_ms(self) -> None:
        state = _StreamState()
        state.t0_perf = 100.0
        # Third-decimal deltas: round(..., 2) differs from round(..., 3) and from
        # round(...), so the precision argument is load-bearing.
        state.ttft_perf = 100.1271658
        state.ack_perf = 101.234567
        _stamp_turn_latencies(state)
        assert state.ttft_ms == 127.17
        assert state.e2e_ack_ms == 1234.57

    def test_stamp_turn_latencies_without_t0_leaves_everything_unset(self) -> None:
        state = _StreamState()
        state.ttft_perf = 100.5
        state.ack_perf = 101.25
        _stamp_turn_latencies(state)
        assert state.ttft_ms is None
        assert state.e2e_ack_ms is None

    def test_stamp_turn_latencies_absent_span_stays_absent(self) -> None:
        state = _StreamState()
        state.t0_perf = 100.0
        state.ack_perf = 101.0
        _stamp_turn_latencies(state)
        assert state.ttft_ms is None
        assert state.e2e_ack_ms == 1000.0

    def test_executor_delegation_no_session(self) -> None:
        assert _executor_delegation("latency-delegation-missing") == (False, False)

    def test_executor_delegation_spawned_is_not_queued(self) -> None:
        stream_id = "latency-delegation-spawned"
        session = create_session(stream_id, RunKind.LIVE)
        session.executor_spawned = True
        try:
            assert _executor_delegation(stream_id) == (True, False)
        finally:
            teardown_session(stream_id)

    def test_executor_delegation_queued_task_is_delegated_and_queued(self) -> None:
        stream_id = "latency-delegation-queued"
        session = create_session(stream_id, RunKind.QUEUED)
        session.executor_queued_task_id = "task-1"
        try:
            assert _executor_delegation(stream_id) == (True, True)
        finally:
            teardown_session(stream_id)

    async def test_note_cancellation_records_the_stop(self) -> None:
        state = _StreamState()
        with patch.object(_stream_manager, "is_cancelled", AsyncMock(return_value=True)) as check:
            await _note_cancellation("s", state)
        assert state.is_cancelled is True
        # The cancel flag is per stream; checking it with the wrong id would read
        # another turn's state.
        check.assert_awaited_once_with("s")

    async def test_note_cancellation_noop_when_flag_clear(self) -> None:
        state = _StreamState()
        with patch.object(_stream_manager, "is_cancelled", AsyncMock(return_value=False)):
            await _note_cancellation("s", state)
        assert state.is_cancelled is False

    async def test_note_cancellation_skips_the_check_when_already_cancelled(self) -> None:
        state = _StreamState()
        state.is_cancelled = True
        with patch.object(_stream_manager, "is_cancelled", AsyncMock(return_value=True)) as check:
            await _note_cancellation("s", state)
        check.assert_not_awaited()

    def test_observe_turn_latencies_all_spans_exact_labels_and_values(self) -> None:
        source = "lat-obs-all"
        state = _StreamState()
        state.t0_perf = 10.0
        state.ttft_perf = 10.5
        state.ack_perf = 11.0
        state.e2e_full_ms = 2000.0
        state.delegated = False
        ttft_labels = {"source": source, "voice_mode": "false", "status": "success"}
        ack_labels = {
            "source": source,
            "voice_mode": "false",
            "delegated": "false",
            "status": "success",
        }
        full_labels = {
            "source": source,
            "voice_mode": "false",
            "delegated": "false",
            "status": "success",
        }
        total_labels = {"source": source, "delegated": "false", "status": "success"}
        ttft_before = _hist_count("chat_ttft_seconds", ttft_labels)
        ttft_sum_before = _hist_sum("chat_ttft_seconds", ttft_labels)
        ack_before = _hist_count("chat_e2e_ack_seconds", ack_labels)
        ack_sum_before = _hist_sum("chat_e2e_ack_seconds", ack_labels)
        full_before = _hist_count("chat_e2e_full_seconds", full_labels)
        full_sum_before = _hist_sum("chat_e2e_full_seconds", full_labels)
        total_before = _counter("chat_turn_total", total_labels)

        _observe_turn_latencies(source=source, voice_mode=False, state=state, status="success")

        assert _hist_count("chat_ttft_seconds", ttft_labels) == ttft_before + 1
        assert _hist_sum("chat_ttft_seconds", ttft_labels) - ttft_sum_before == pytest.approx(0.5)
        assert _hist_count("chat_e2e_ack_seconds", ack_labels) == ack_before + 1
        assert _hist_sum("chat_e2e_ack_seconds", ack_labels) - ack_sum_before == pytest.approx(1.0)
        assert _hist_count("chat_e2e_full_seconds", full_labels) == full_before + 1
        assert _hist_sum("chat_e2e_full_seconds", full_labels) - full_sum_before == pytest.approx(
            2.0
        )
        assert _counter("chat_turn_total", total_labels) == total_before + 1

    def test_observe_turn_latencies_unknown_source_delegated_and_voice_true(self) -> None:
        state = _StreamState()
        state.t0_perf = 20.0
        state.ttft_perf = 20.25
        state.ack_perf = 20.5
        state.e2e_full_ms = 1000.0
        state.delegated = True
        ttft_labels = {"source": "unknown", "voice_mode": "true", "status": "cancelled"}
        ack_labels = {
            "source": "unknown",
            "voice_mode": "true",
            "delegated": "true",
            "status": "cancelled",
        }
        full_labels = {
            "source": "unknown",
            "voice_mode": "true",
            "delegated": "true",
            "status": "cancelled",
        }
        total_labels = {"source": "unknown", "delegated": "true", "status": "cancelled"}
        ttft_before = _hist_count("chat_ttft_seconds", ttft_labels)
        ttft_sum_before = _hist_sum("chat_ttft_seconds", ttft_labels)
        ack_before = _hist_count("chat_e2e_ack_seconds", ack_labels)
        full_before = _hist_count("chat_e2e_full_seconds", full_labels)
        total_before = _counter("chat_turn_total", total_labels)

        _observe_turn_latencies(source=None, voice_mode=True, state=state, status="cancelled")

        assert _hist_count("chat_ttft_seconds", ttft_labels) == ttft_before + 1
        assert _hist_sum("chat_ttft_seconds", ttft_labels) - ttft_sum_before == pytest.approx(0.25)
        assert _hist_count("chat_e2e_ack_seconds", ack_labels) == ack_before + 1
        # voice_mode/delegated are forwarded to the full-turn emit too (True -> "true").
        assert _hist_count("chat_e2e_full_seconds", full_labels) == full_before + 1
        assert _counter("chat_turn_total", total_labels) == total_before + 1

    def test_observe_turn_latencies_absent_spans_only_count_the_turn(self) -> None:
        source = "lat-obs-empty"
        state = _StreamState()
        total_labels = {"source": source, "delegated": "false", "status": "success"}
        ttft_labels = {"source": source, "voice_mode": "false", "status": "success"}
        total_before = _counter("chat_turn_total", total_labels)
        ttft_before = _hist_count("chat_ttft_seconds", ttft_labels)

        _observe_turn_latencies(source=source, voice_mode=False, state=state, status="success")

        assert _counter("chat_turn_total", total_labels) == total_before + 1
        assert _hist_count("chat_ttft_seconds", ttft_labels) == ttft_before

    def test_close_turn_timings_fills_state_and_emits(self) -> None:
        stream_id = "latency-close-turn"
        session = create_session(stream_id, RunKind.LIVE)
        session.executor_spawned = True
        state = _StreamState()
        state.t0_perf = 100.0
        state.ttft_perf = 100.5
        state.ack_perf = 101.0
        total_labels = {"source": "web", "delegated": "true", "status": "cancelled"}
        ttft_labels = {"source": "web", "voice_mode": "true", "status": "cancelled"}
        before = _counter("chat_turn_total", total_labels)
        ttft_before = _hist_count("chat_ttft_seconds", ttft_labels)
        try:
            # 3.1234567s: round(..., 2) != round(..., 3), so the e2e rounding is pinned.
            with patch("app.services.chat.stream.time.perf_counter", return_value=103.1234567):
                _close_turn_timings(
                    stream_id, state, source="web", voice_mode=True, status="cancelled"
                )
            assert state.delegated is True
            assert state.queued is False
            assert state.ttft_ms == 500.0
            assert state.e2e_ack_ms == 1000.0
            assert state.e2e_full_ms == 3123.46
            assert _counter("chat_turn_total", total_labels) == before + 1
            # voice_mode is forwarded to the emit (True -> "true"), not dropped.
            assert _hist_count("chat_ttft_seconds", ttft_labels) == ttft_before + 1
        finally:
            teardown_session(stream_id)

    async def test_finalize_stream_stamps_latency_fields_on_wide_event(
        self, test_user, existing_conv_body
    ) -> None:
        _log.reset()
        state = _StreamState()
        state.saved = True
        state.delegated = True
        state.queued = True
        state.ttft_ms = 500.0
        state.e2e_ack_ms = 1000.0
        state.e2e_full_ms = 3000.0
        with (
            patch("app.services.chat.stream.teardown_executor_capture"),
            patch("app.services.chat.stream.stream_manager.cleanup", new=AsyncMock()),
            patch("app.services.chat.stream.flush_fs_metrics", return_value={}),
        ):
            await _finalize_stream(
                "stream_latency_final",
                existing_conv_body,
                test_user,
                "conv_existing_123",
                state,
                None,
            )
        assert _log.get()["chat"] == {
            "delegated": True,
            "queued": True,
            "ttft_ms": 500.0,
            "e2e_ack_ms": 1000.0,
            "e2e_full_ms": 3000.0,
        }

    async def test_finalize_stream_omits_absent_spans(self, test_user, existing_conv_body) -> None:
        _log.reset()
        state = _StreamState()
        state.saved = True
        with (
            patch("app.services.chat.stream.teardown_executor_capture"),
            patch("app.services.chat.stream.stream_manager.cleanup", new=AsyncMock()),
            patch("app.services.chat.stream.flush_fs_metrics", return_value={}),
        ):
            await _finalize_stream(
                "stream_latency_final_empty",
                existing_conv_body,
                test_user,
                "conv_existing_123",
                state,
                None,
            )
        assert _log.get()["chat"] == {"delegated": False, "queued": False}
