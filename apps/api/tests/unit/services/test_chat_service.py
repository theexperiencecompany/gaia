"""Unit tests for the chat service streaming pipeline.

Tests cover the core orchestration logic in chat_service.py:
- run_chat_stream_background: end-to-end background streaming coordination
- _initialize_new_conversation: conversation creation and init chunk format
- _save_conversation_async: MongoDB persistence with correct message structure
- extract_tool_data: JSON parsing and tool field extraction
- _extract_response_text: response text extraction from SSE chunks
- update_conversation_messages: legacy background-task scheduling path

Mocking strategy:
- KEEP mocks for: stream_manager (Redis I/O), call_agent (external LLM call)
- Mock DB at the collection level (conversations_collection), NOT at service
  function level — this ensures create_conversation, update_messages, and
  _process_token_usage_and_cost all run for real through their logic.
- The deeper payment/rate-limiter deps are mocked where they touch real I/O.
"""

import asyncio
import json
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.message_models import MessageRequestWithHistory
from app.services.chat_service import (
    _extract_response_text,
    _initialize_new_conversation,
    _save_conversation_async,
    extract_tool_data,
    run_chat_stream_background,
    update_conversation_messages,
)


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
    return
    yield  # make it an async generator


async def _done_only_stream() -> AsyncGenerator[str, None]:
    """Async generator that yields only the DONE sentinel."""
    yield "data: [DONE]\n\n"


async def _text_then_nostream(text: str, complete: str) -> AsyncGenerator[str, None]:
    """Yields a text chunk, then a nostream marker, then DONE."""
    yield f"data: {json.dumps({'response': text})}\n\n"
    yield f"nostream: {json.dumps({'complete_message': complete})}"
    yield "data: [DONE]\n\n"


def _make_usage_handler_class() -> MagicMock:
    """Return a mock that acts like the UsageMetadataCallbackHandler class.

    The service calls UsageMetadataCallbackHandler() to get an instance and
    later reads instance.usage_metadata.  We need the instance to have
    usage_metadata == {} (a real empty dict) so that Pydantic accepts it when
    it ends up in MessageModel(metadata=...).
    """
    instance = MagicMock()
    instance.usage_metadata = {}
    handler_class = MagicMock(return_value=instance)
    return handler_class


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


def _make_conversations_collection_mock(
    insert_acknowledged: bool = True,
    update_modified: int = 1,
) -> MagicMock:
    """
    Return a mock that satisfies the Motor collection API used by
    conversation_service: insert_one and update_one.
    """
    col = AsyncMock()

    insert_result = MagicMock()
    insert_result.acknowledged = insert_acknowledged
    col.insert_one = AsyncMock(return_value=insert_result)

    update_result = MagicMock()
    update_result.modified_count = update_modified
    col.update_one = AsyncMock(return_value=update_result)

    return col


# ---------------------------------------------------------------------------
# extract_tool_data — pure synchronous helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
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
                    {"tool_name": "search_results", "data": {"items": []}, "timestamp": "t"}
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
        payload = json.dumps(
            {"tool_output": {"tool_call_id": "call_1", "output": "result text"}}
        )
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


@pytest.mark.unit
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
# Tests for this function still mock create_conversation because
# _initialize_new_conversation is a thin wrapper — its own logic (SSE
# formatting, field inclusion) is what we want to assert.
# The deeper create_conversation -> DB path is tested in the orchestration
# section below.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInitializeNewConversation:
    async def test_returns_sse_formatted_init_chunk(self, test_user, basic_body):
        mock_conv = {
            "conversation_id": "conv_new_xyz",
            "description": "New Chat",
        }
        with patch(
            "app.services.chat_service.create_conversation",
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
        mock_conv = {
            "conversation_id": "conv_new_xyz",
            "description": "New Chat",
        }
        with patch(
            "app.services.chat_service.create_conversation",
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
        mock_conv = {
            "conversation_id": "forced_id",
            "description": "New Chat",
        }
        with patch(
            "app.services.chat_service.create_conversation",
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
        mock_conv = {
            "conversation_id": "conv_id",
            "description": "Chat about the weather",
        }
        with patch(
            "app.services.chat_service.create_conversation",
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
#
# The function's own logic (message model construction, token processing
# decision, tool_data assignment) is what we verify.  We mock at the DB
# collection level so update_messages runs for real; we mock the payment /
# rate-limiter I/O so _process_token_usage_and_cost runs for real too.
# ---------------------------------------------------------------------------


def _apply_payment_patches(stack: ExitStack) -> None:
    """Enter the payment/rate-limiter stubs into an ExitStack.

    Stubs out the I/O performed by _process_token_usage_and_cost without
    bypassing the function itself, so the token-processing logic still runs.
    """
    stack.enter_context(
        patch(
            "app.services.chat_service.payment_service.get_user_subscription_status",
            new=AsyncMock(return_value=MagicMock(plan_type=None)),
        )
    )
    stack.enter_context(
        patch(
            "app.services.chat_service.calculate_token_cost",
            new=AsyncMock(return_value={"total_cost": 0.0}),
        )
    )
    stack.enter_context(
        patch(
            "app.services.chat_service.tiered_limiter.check_and_increment",
            new=AsyncMock(),
        )
    )


@pytest.mark.unit
class TestSaveConversationAsync:
    async def test_saves_user_and_bot_messages(self, test_user, basic_body):
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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

        col.update_one.assert_called_once()
        # The $push payload must contain exactly two messages
        call_args = col.update_one.call_args
        push_payload = call_args.args[1]["$push"]["messages"]["$each"]
        types = [m["type"] for m in push_payload]
        assert types == ["user", "bot"]

    async def test_user_message_content_comes_from_last_messages_entry(
        self, test_user
    ):
        body = MessageRequestWithHistory(
            message="Fallback message",
            messages=[
                {"role": "user", "content": "First turn"},
                {"role": "user", "content": "Last turn"},
            ],
            conversation_id="conv_x",
        )
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        user_msg = push_payload[0]
        assert user_msg["response"] == "Last turn"

    async def test_user_message_falls_back_to_body_message(self, test_user):
        body = MessageRequestWithHistory(
            message="Fallback content",
            messages=[],
            conversation_id="conv_y",
        )
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        user_msg = push_payload[0]
        assert user_msg["response"] == "Fallback content"

    async def test_bot_message_contains_complete_message(self, test_user, basic_body):
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        assert bot_msg["response"] == "The answer is 42."

    async def test_message_ids_are_set_on_models(self, test_user, basic_body):
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        assert push_payload[0]["message_id"] == "umsg_specific"
        assert push_payload[1]["message_id"] == "bmsg_specific"

    async def test_token_processing_called_when_metadata_present(
        self, test_user, basic_body
    ):
        """_process_token_usage_and_cost must call calculate_token_cost when
        metadata contains token counts — verified by asserting the downstream
        call, not by mocking the function itself."""
        col = _make_conversations_collection_mock()
        mock_calc = AsyncMock(return_value={"total_cost": 0.001})
        metadata = {
            "claude-3-5-sonnet": {"input_tokens": 100, "output_tokens": 50}
        }
        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=mock_calc,
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="ok",
                tool_data={},
                metadata=metadata,
                user_message_id="u",
                bot_message_id="b",
            )
        mock_calc.assert_called_once_with("claude-3-5-sonnet", 100, 50)

    async def test_token_processing_skipped_when_no_metadata(
        self, test_user, basic_body
    ):
        """No token calls expected when metadata is empty."""
        col = _make_conversations_collection_mock()
        mock_calc = AsyncMock(return_value={"total_cost": 0.0})
        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=mock_calc,
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="ok",
                tool_data={},
                metadata={},
                user_message_id="u",
                bot_message_id="b",
            )
        mock_calc.assert_not_called()

    async def test_token_processing_error_does_not_propagate(
        self, test_user, basic_body
    ):
        """A token processing failure must not prevent the conversation from saving."""
        col = _make_conversations_collection_mock()
        with (
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(side_effect=Exception("payment service down")),
            ),
        ):
            # Should not raise
            await _save_conversation_async(
                body=basic_body,
                user=test_user,
                conversation_id="conv_123",
                complete_message="ok",
                tool_data={},
                metadata={"model": {"input_tokens": 10, "output_tokens": 5}},
                user_message_id="u",
                bot_message_id="b",
            )
        # update_one must still have been called despite the payment error
        col.update_one.assert_called_once()

    async def test_tool_data_applied_to_bot_message(self, test_user, basic_body):
        col = _make_conversations_collection_mock()
        tool_data = {
            "tool_data": [
                {"tool_name": "search_results", "data": {"items": []}, "timestamp": "t"}
            ]
        }
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        assert bot_msg["tool_data"] == tool_data["tool_data"]

    async def test_correct_conversation_id_passed_to_update(
        self, test_user, basic_body
    ):
        col = _make_conversations_collection_mock()
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.services.conversation_service.conversations_collection",
                    col,
                )
            )
            _apply_payment_patches(stack)
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
        # update_one filter must target the right conversation
        filter_arg = col.update_one.call_args.args[0]
        assert filter_arg["conversation_id"] == "specific_conv_id"


# ---------------------------------------------------------------------------
# run_chat_stream_background — top-level orchestrator
#
# These tests mock:
#   - stream_manager   (Redis I/O)
#   - call_agent       (external LLM)
#   - get_user_selected_model  (model config fetch)
#   - generate_and_update_description  (async LLM background task)
#   - UsageMetadataCallbackHandler  (LangChain integration object)
#   - conversations_collection  (MongoDB — DB level, not service level)
#   - payment_service / calculate_token_cost / tiered_limiter (payment I/O)
#
# They do NOT mock: create_conversation, update_messages,
# _save_conversation_async, or _process_token_usage_and_cost.
# If any of those are removed from the service, the relevant test will fail.
# ---------------------------------------------------------------------------


def _apply_orchestration_patches(
    stack: ExitStack,
    sm: MagicMock,
    agent_stream: Any,
    col: MagicMock,
    generate_desc: AsyncMock | None = None,
) -> None:
    """Enter all standard orchestration patches into an ExitStack.

    Patches: stream_manager, call_agent, get_user_selected_model,
    generate_and_update_description, UsageMetadataCallbackHandler,
    conversations_collection, and all payment I/O.
    Does NOT patch: create_conversation, update_messages,
    _save_conversation_async, _process_token_usage_and_cost.
    """
    if generate_desc is None:
        generate_desc = AsyncMock(return_value="Test conv")
    stack.enter_context(patch("app.services.chat_service.stream_manager", sm))
    stack.enter_context(
        patch(
            "app.services.chat_service.call_agent",
            new=AsyncMock(return_value=agent_stream),
        )
    )
    stack.enter_context(
        patch(
            "app.services.chat_service.get_user_selected_model",
            new=AsyncMock(return_value=None),
        )
    )
    stack.enter_context(
        patch(
            "app.services.chat_service.generate_and_update_description",
            new=generate_desc,
        )
    )
    stack.enter_context(
        patch("app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class())
    )
    stack.enter_context(
        patch(
            "app.services.conversation_service.conversations_collection",
            col,
        )
    )
    _apply_payment_patches(stack)


@pytest.mark.unit
class TestRunChatStreamBackground:
    async def test_new_conversation_publishes_init_chunk(
        self, test_user, basic_body
    ):
        """When conversation_id is None, an init chunk must be published first."""
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="Test conv"),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_1",
                body=basic_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
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
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_2",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        first_publish_call = sm.publish_chunk.call_args_list[0]
        first_arg = first_publish_call.args[1]
        payload = json.loads(first_arg[6:])
        assert "user_message_id" in payload
        assert "bot_message_id" in payload
        # Should NOT contain conversation_id for existing conversations
        assert "conversation_id" not in payload

    async def test_done_marker_published_after_agent_completes(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_3",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        published = [call.args[1] for call in sm.publish_chunk.call_args_list]
        assert "data: [DONE]\n\n" in published

    async def test_complete_stream_called_on_success(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_4",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        sm.complete_stream.assert_called_once_with("stream_4")

    async def test_cleanup_always_called_on_success(
        self, test_user, existing_conv_body
    ):
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_5",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        sm.cleanup.assert_called_once_with("stream_5")

    async def test_cleanup_called_even_when_agent_raises(
        self, test_user, existing_conv_body
    ):
        """The finally block must always run cleanup even on agent failure."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent exploded")),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_6",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        sm.cleanup.assert_called_once_with("stream_6")

    async def test_error_chunk_published_before_set_error(
        self, test_user, existing_conv_body
    ):
        """set_error() sends STREAM_ERROR_SIGNAL which breaks the subscriber.
        The human-readable error JSON must be published first."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        publish_calls: list[str] = []

        async def track_publish(stream_id: str, chunk: str) -> None:
            publish_calls.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track_publish)
        set_error_calls: list[str] = []

        async def track_set_error(stream_id: str, err: str) -> None:
            set_error_calls.append(err)

        sm.set_error = AsyncMock(side_effect=track_set_error)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(side_effect=RuntimeError("network timeout")),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_7",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
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

    async def test_save_always_called_even_on_agent_failure(
        self, test_user, existing_conv_body
    ):
        """update_one must be called even when the agent raises, because
        _save_conversation_async is invoked in the finally block."""
        sm = _make_stream_manager_mock()
        sm.get_progress = AsyncMock(return_value=None)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(side_effect=RuntimeError("agent down")),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_8",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        # DB update must still have been attempted
        col.update_one.assert_called()

    async def test_nostream_chunk_sets_complete_message(
        self, test_user, existing_conv_body
    ):
        """nostream: chunk must set complete_message which is later saved."""
        complete_text = "The final answer is here."

        async def agent_with_nostream():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            yield f"nostream: {json.dumps({'complete_message': complete_text})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_with_nostream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_9",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        # The bot message persisted to the DB must carry the complete_message text
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        assert bot_msg["response"] == complete_text

    async def test_nostream_chunk_not_forwarded_to_client(
        self, test_user, existing_conv_body
    ):
        """The nostream: prefix is internal — must never be published to Redis."""

        async def agent_with_nostream():
            yield f"nostream: {json.dumps({'complete_message': 'final'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        published_chunks: list[str] = []

        async def track_publish(stream_id: str, chunk: str) -> None:
            published_chunks.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track_publish)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_with_nostream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_10",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        # No published chunk should contain "nostream"
        for chunk in published_chunks:
            assert "nostream" not in chunk

    async def test_cancellation_stops_stream_loop(
        self, test_user, existing_conv_body
    ):
        """When is_cancelled returns True, no further agent chunks are processed."""

        async def agent_that_yields_many():
            for i in range(5):
                yield f"data: {json.dumps({'response': f'chunk {i}'})}\n\n"

        sm = _make_stream_manager_mock(is_cancelled=True)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_that_yields_many()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_cancel",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        # DB save still called even when cancelled
        col.update_one.assert_called()

    async def test_tool_data_chunks_accumulated_and_saved(
        self, test_user, existing_conv_body
    ):
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
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_with_tool_data()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_tools",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        tool_entries = bot_msg.get("tool_data", [])
        assert len(tool_entries) >= 1
        assert tool_entries[0]["tool_name"] == "search_results"

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
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_with_output()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_merge",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        tool_entries = bot_msg.get("tool_data", [])
        calls_entry = next(
            (e for e in tool_entries if e.get("tool_name") == "tool_calls_data"), None
        )
        assert calls_entry is not None
        assert calls_entry["data"]["output"] == "search results"

    async def test_follow_up_actions_published_to_stream(
        self, test_user, existing_conv_body
    ):
        """follow_up_actions from agent must be published as a separate SSE event."""

        async def agent_with_follow_up():
            payload = {"follow_up_actions": ["Action A", "Action B"]}
            yield f"data: {json.dumps(payload)}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'done'})}"
            yield "data: [DONE]\n\n"

        sm = _make_stream_manager_mock()
        published: list[str] = []

        async def track(stream_id: str, chunk: str) -> None:
            published.append(chunk)

        sm.publish_chunk = AsyncMock(side_effect=track)
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=agent_with_follow_up()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_fu",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        follow_up_chunks = [
            c for c in published
            if c.startswith("data: ") and "follow_up_actions" in c
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
        col = _make_conversations_collection_mock()

        # Agent yields only a partial response without nostream marker
        async def partial_agent():
            yield f"data: {json.dumps({'response': 'partial'})}\n\n"
            # Deliberately NO nostream: marker
            yield "data: [DONE]\n\n"

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=partial_agent()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_recover",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        assert bot_msg["response"] == "recovered text"

    async def test_description_task_spawned_for_new_conversation(
        self, test_user, basic_body
    ):
        """generate_and_update_description must be called for new conversations."""
        mock_desc = AsyncMock(return_value="Generated description")
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=mock_desc,
            ),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_desc",
                body=basic_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="new_id",
            )

        mock_desc.assert_called_once()

    async def test_no_description_task_for_existing_conversation(
        self, test_user, existing_conv_body
    ):
        """generate_and_update_description must NOT be called for existing conversations."""
        mock_desc = AsyncMock(return_value="Should not be called")
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=mock_desc,
            ),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_no_desc",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        mock_desc.assert_not_called()


# ---------------------------------------------------------------------------
# New orchestration tests
# These tests verify REAL orchestration — each test is designed to fail if
# the corresponding service call is removed from the production code.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestrationBehavior:
    async def test_new_conversation_created_when_no_id(
        self, test_user, basic_body
    ):
        """When conversation_id is None, MongoDB insert_one must be called.
        If create_conversation is removed from chat_service, this test fails."""
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.generate_and_update_description",
                new=AsyncMock(return_value="Test conv"),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_create",
                body=basic_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="new_conv_id",
            )

        # The conversation document must have been inserted into MongoDB
        col.insert_one.assert_called_once()
        inserted_doc = col.insert_one.call_args.args[0]
        assert inserted_doc["conversation_id"] == "new_conv_id"
        assert inserted_doc["user_id"] == "user_abc"

    async def test_messages_saved_after_stream(
        self, test_user, existing_conv_body
    ):
        """After the agent stream completes, update_one must push user+bot
        messages into MongoDB.  Removing update_messages from _save_conversation_async
        must make this test fail."""
        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()

        async def simple_agent():
            yield f"data: {json.dumps({'response': 'hello'})}\n\n"
            yield f"nostream: {json.dumps({'complete_message': 'hello'})}"
            yield "data: [DONE]\n\n"

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=simple_agent()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_save_msgs",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        col.update_one.assert_called_once()
        filter_arg, update_arg = col.update_one.call_args.args
        assert filter_arg["conversation_id"] == "conv_existing_123"
        pushed = update_arg["$push"]["messages"]["$each"]
        assert len(pushed) == 2
        assert pushed[0]["type"] == "user"
        assert pushed[1]["type"] == "bot"
        assert pushed[1]["response"] == "hello"

    async def test_stream_cancelled_cleans_up_and_saves(
        self, test_user, existing_conv_body
    ):
        """If cancellation happens mid-stream, the conversation is still saved to DB
        and Redis is cleaned up.  Removing either call from the finally block fails
        this test."""
        sm = _make_stream_manager_mock(is_cancelled=True)
        sm.get_progress = AsyncMock(
            return_value={"complete_message": "partial text", "tool_data": {}}
        )
        col = _make_conversations_collection_mock()

        async def multi_chunk_agent():
            for i in range(4):
                yield f"data: {json.dumps({'response': f'chunk {i}'})}\n\n"

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=multi_chunk_agent()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler", _make_usage_handler_class()
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=AsyncMock(return_value={"total_cost": 0.0}),
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=AsyncMock(),
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_cancelled",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        # Conversation must still be saved despite cancellation
        col.update_one.assert_called_once()
        # Redis must be cleaned up
        sm.cleanup.assert_called_once_with("stream_cancelled")
        # The recovered text from Redis progress must be in the bot message
        push_payload = col.update_one.call_args.args[1]["$push"]["messages"]["$each"]
        bot_msg = push_payload[1]
        assert bot_msg["response"] == "partial text"

    async def test_token_usage_tracked(
        self, test_user, existing_conv_body
    ):
        """When the agent returns usage metadata, calculate_token_cost must be called
        and, if costs > 0, check_and_increment must be called.
        Removing _process_token_usage_and_cost from _save_conversation_async fails
        this test."""
        usage_metadata_mock = MagicMock()
        usage_metadata_mock.usage_metadata = {
            "claude-3-5-sonnet": {"input_tokens": 200, "output_tokens": 100}
        }

        sm = _make_stream_manager_mock()
        col = _make_conversations_collection_mock()
        mock_calc = AsyncMock(return_value={"total_cost": 0.005})
        mock_limiter = AsyncMock()

        with (
            patch("app.services.chat_service.stream_manager", sm),
            patch(
                "app.services.chat_service.call_agent",
                new=AsyncMock(return_value=_done_only_stream()),
            ),
            patch(
                "app.services.chat_service.get_user_selected_model",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.services.chat_service.UsageMetadataCallbackHandler",
                return_value=usage_metadata_mock,
            ),
            patch(
                "app.services.conversation_service.conversations_collection",
                col,
            ),
            patch(
                "app.services.chat_service.payment_service.get_user_subscription_status",
                new=AsyncMock(return_value=MagicMock(plan_type=None)),
            ),
            patch(
                "app.services.chat_service.calculate_token_cost",
                new=mock_calc,
            ),
            patch(
                "app.services.chat_service.tiered_limiter.check_and_increment",
                new=mock_limiter,
            ),
        ):
            await run_chat_stream_background(
                stream_id="stream_tokens",
                body=existing_conv_body,
                user=test_user,
                user_time=datetime.now(timezone.utc),
                conversation_id="conv_existing_123",
            )

        mock_calc.assert_called_once_with("claude-3-5-sonnet", 200, 100)
        mock_limiter.assert_called_once()


# ---------------------------------------------------------------------------
# update_conversation_messages — legacy synchronous scheduler
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUpdateConversationMessages:
    def test_schedules_update_messages_task(self, test_user, basic_body):
        background_tasks = MagicMock()

        with patch(
            "app.services.chat_service._process_token_usage_and_cost"
        ):
            update_conversation_messages(
                background_tasks=background_tasks,
                body=basic_body,
                user=test_user,
                conversation_id="conv_legacy",
                complete_message="Legacy response",
            )

        # Must schedule an update_messages background task
        assert background_tasks.add_task.called
        call_args_list = background_tasks.add_task.call_args_list
        task_funcs = [call.args[0].__name__ for call in call_args_list]
        assert "update_messages" in task_funcs

    def test_schedules_token_processing_when_metadata_present(
        self, test_user, basic_body
    ):
        background_tasks = MagicMock()
        metadata = {"model": {"input_tokens": 10, "output_tokens": 5}}

        update_conversation_messages(
            background_tasks=background_tasks,
            body=basic_body,
            user=test_user,
            conversation_id="conv_legacy",
            complete_message="response",
            metadata=metadata,
        )

        call_args_list = background_tasks.add_task.call_args_list
        task_funcs = [call.args[0].__name__ for call in call_args_list]
        assert "_process_token_usage_and_cost" in task_funcs

    def test_does_not_schedule_token_processing_without_metadata(
        self, test_user, basic_body
    ):
        background_tasks = MagicMock()

        update_conversation_messages(
            background_tasks=background_tasks,
            body=basic_body,
            user=test_user,
            conversation_id="conv_legacy",
            complete_message="response",
            metadata={},
        )

        call_args_list = background_tasks.add_task.call_args_list
        task_funcs = [call.args[0].__name__ for call in call_args_list]
        assert "_process_token_usage_and_cost" not in task_funcs

    def test_update_request_has_correct_conversation_id(
        self, test_user, basic_body
    ):
        background_tasks = MagicMock()

        update_conversation_messages(
            background_tasks=background_tasks,
            body=basic_body,
            user=test_user,
            conversation_id="target_conv_id",
            complete_message="response",
        )

        # Find the update_messages task call
        update_call = next(
            c
            for c in background_tasks.add_task.call_args_list
            if c.args[0].__name__ == "update_messages"
        )
        request_arg = update_call.args[1]
        assert request_arg.conversation_id == "target_conv_id"

    def test_bot_message_id_is_set_when_provided(self, test_user, basic_body):
        background_tasks = MagicMock()

        update_conversation_messages(
            background_tasks=background_tasks,
            body=basic_body,
            user=test_user,
            conversation_id="conv_id",
            complete_message="response",
            bot_message_id="my_bot_msg_id",
        )

        update_call = next(
            c
            for c in background_tasks.add_task.call_args_list
            if c.args[0].__name__ == "update_messages"
        )
        request_arg = update_call.args[1]
        bot_msg = request_arg.messages[1]
        assert bot_msg.message_id == "my_bot_msg_id"

    def test_user_message_id_is_set_when_provided(self, test_user, basic_body):
        background_tasks = MagicMock()

        update_conversation_messages(
            background_tasks=background_tasks,
            body=basic_body,
            user=test_user,
            conversation_id="conv_id",
            complete_message="response",
            user_message_id="my_user_msg_id",
        )

        update_call = next(
            c
            for c in background_tasks.add_task.call_args_list
            if c.args[0].__name__ == "update_messages"
        )
        request_arg = update_call.args[1]
        user_msg = request_arg.messages[0]
        assert user_msg.message_id == "my_user_msg_id"
