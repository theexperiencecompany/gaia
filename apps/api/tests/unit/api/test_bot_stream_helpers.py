"""Unit tests for the bot chat-stream translation helpers in ``app.api.v1.endpoints.bot``.

These are pure/near-pure functions extracted from ``bot_chat_stream`` — SSE
framing, web-payload-to-bot-frame translation, and the background-task
failure logger. They are exercised only indirectly by the endpoint-level
tests in ``test_bot_endpoint.py``, so this file drives them directly with
exact-value assertions on every branch.
"""

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.endpoints.bot import (
    BOT_STREAM_ERROR_PLAN_REQUIRED,
    _bot_stream_control_frame,
    _bot_stream_entitlement_gate,
    _bot_stream_failure_logger,
    _bot_stream_payload_frame,
    _build_bot_message_request,
    _paywall_notice,
    _paywall_notice_stream,
)
from app.models.bot_models import BotChatRequest
from app.models.message_models import FileData


class TestBotStreamControlFrame:
    """``_bot_stream_control_frame`` — peels Redis SSE framing off one raw chunk."""

    def test_comment_chunk_passes_through_unchanged(self):
        frame, data, stop = _bot_stream_control_frame(": keepalive\n\n", "conv-1")
        assert frame == ": keepalive\n\n"
        assert data is None
        assert stop is False

    def test_non_data_non_comment_line_yields_nothing(self):
        frame, data, stop = _bot_stream_control_frame("event: ping\n\n", "conv-1")
        assert frame is None
        assert data is None
        assert stop is False

    def test_id_tagged_content_chunk_is_parsed_after_stripping_the_id_line(self):
        chunk = 'id: 42\ndata: {"response": "hi"}\n\n'
        frame, data, stop = _bot_stream_control_frame(chunk, "conv-1")
        assert frame is None
        assert data == {"response": "hi"}
        assert stop is False

    def test_id_tagged_done_chunk_still_produces_the_done_frame(self):
        chunk = "id: 7\ndata: [DONE]\n\n"
        frame, data, stop = _bot_stream_control_frame(chunk, "conv-99")
        assert frame == 'data: {"done": true, "conversation_id": "conv-99"}\n\n'
        assert data is None
        assert stop is True

    def test_done_chunk_embeds_the_exact_conversation_id(self):
        frame, data, stop = _bot_stream_control_frame("data: [DONE]\n\n", "conv-abc")
        assert frame is not None
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"done": True, "conversation_id": "conv-abc"}
        assert data is None
        assert stop is True

    def test_valid_json_payload_is_parsed_and_returned_as_data(self):
        frame, data, stop = _bot_stream_control_frame('data: {"a": 1, "b": "x"}\n\n', "conv-1")
        assert frame is None
        assert data == {"a": 1, "b": "x"}
        assert stop is False

    def test_malformed_json_is_dropped_and_logged(self):
        with patch("app.api.v1.endpoints.bot.log") as mock_log:
            frame, data, stop = _bot_stream_control_frame("data: {not-json}\n\n", "conv-1")
        assert frame is None
        assert data is None
        assert stop is False
        mock_log.warning.assert_called_once()
        assert mock_log.warning.call_args.kwargs["error_type"] == "JSONDecodeError"


class TestBotStreamPayloadFrame:
    """``_bot_stream_payload_frame`` — translates one parsed web SSE payload."""

    async def test_keepalive_forwards_a_keepalive_frame(self):
        frame, stop = await _bot_stream_payload_frame({"keepalive": True}, "user-1")
        assert frame == 'data: {"keepalive": true}\n\n'
        assert stop is False

    async def test_rate_limit_card_becomes_a_notice_frame_for_pro_users(self):
        data = {
            "tool_data": {
                "tool_name": "rate_limit_data",
                "data": {"feature": "chat_messages", "current_plan": "pro"},
            }
        }
        frame, stop = await _bot_stream_payload_frame(data, "user-1")
        assert frame is not None
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {
            "notice": {
                "text": "⏳ You've reached your chat messages limit. Please try again later."
            }
        }
        assert stop is False

    async def test_rate_limit_card_appends_an_upgrade_link_for_non_pro_users(self):
        data = {
            "tool_data": {
                "tool_name": "rate_limit_data",
                "data": {"feature": "chat_messages", "current_plan": "free"},
            }
        }
        with patch(
            "app.api.v1.endpoints.bot._bot_upgrade_url",
            new_callable=AsyncMock,
            return_value="https://pay.example/checkout",
        ):
            frame, stop = await _bot_stream_payload_frame(data, "user-1")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload["notice"]["text"].endswith(
            "[Upgrade to Pro](https://pay.example/checkout) for higher limits."
        )
        assert stop is False

    async def test_approval_card_becomes_an_approval_frame(self):
        data = {
            "tool_data": {
                "tool_name": "approval_request",
                "data": {"tool": "send_email", "id": "req-1"},
            }
        }
        frame, stop = await _bot_stream_payload_frame(data, "user-1")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"approval": {"tool": "send_email", "id": "req-1"}}
        assert stop is False

    async def test_message_boundary_is_forwarded_verbatim(self):
        data = {"message_boundary": {"discarded": True, "message_id": "m1"}}
        frame, stop = await _bot_stream_payload_frame(data, "user-1")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"message_boundary": {"discarded": True, "message_id": "m1"}}
        assert stop is False

    @pytest.mark.parametrize(
        "key",
        [
            "conversation_description",
            "user_message_id",
            "bot_message_id",
            "stream_id",
            "tool_data",
            "tool_output",
            "follow_up_actions",
        ],
    )
    async def test_web_only_fields_yield_no_frame(self, key: str):
        frame, stop = await _bot_stream_payload_frame({key: "irrelevant"}, "user-1")
        assert frame is None
        assert stop is False

    @pytest.mark.parametrize(
        "key",
        [
            "conversation_description",
            "user_message_id",
            "bot_message_id",
            "stream_id",
            "tool_data",
            "tool_output",
            "follow_up_actions",
        ],
    )
    async def test_each_web_only_field_takes_priority_over_a_response_field(self, key: str):
        """A payload carrying BOTH a web-only field and `response` is dropped —
        the web-only check runs first, same as the real message stream shape.
        Parametrized per key so a mutation to any single list entry (rather than
        the whole check) still shows up as a different result than the no-op
        catchall branch."""
        frame, stop = await _bot_stream_payload_frame({"response": "hello", key: "x"}, "user-1")
        assert frame is None
        assert stop is False

    async def test_response_field_is_translated_to_text(self):
        frame, stop = await _bot_stream_payload_frame({"response": "hello there"}, "user-1")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"text": "hello there"}
        assert stop is False

    async def test_error_field_is_translated_and_stops_the_stream(self):
        frame, stop = await _bot_stream_payload_frame({"error": "boom"}, "user-1")
        payload = json.loads(frame[len("data: ") : -2])
        assert payload == {"error": "boom"}
        assert stop is True

    async def test_unrecognized_shape_yields_no_frame(self):
        frame, stop = await _bot_stream_payload_frame({"some_other_field": 1}, "user-1")
        assert frame is None
        assert stop is False


class TestBuildBotMessageRequest:
    """``_build_bot_message_request`` — loads history and appends the incoming turn."""

    async def test_appends_the_incoming_message_after_the_loaded_history(self):
        body = BotChatRequest(message="new turn", platform="discord", platform_user_id="u1")
        with patch(
            "app.api.v1.endpoints.bot.BotService.load_conversation_history",
            new_callable=AsyncMock,
            return_value=[{"role": "user", "content": "old turn"}],
        ) as mock_load:
            result = await _build_bot_message_request(body, "conv-1", "user-1")

        mock_load.assert_awaited_once_with("conv-1", "user-1")
        assert result.message == "new turn"
        assert result.conversation_id == "conv-1"
        assert [m["role"] for m in result.messages] == ["user", "user"]
        assert [m["content"] for m in result.messages] == ["old turn", "new turn"]
        assert result.fileIds == []
        assert result.fileData == []

    async def test_defaults_file_ids_and_file_data_to_empty_lists_when_none(self):
        body = BotChatRequest(
            message="hi", platform="discord", platform_user_id="u1", file_ids=None, file_data=None
        )
        with patch(
            "app.api.v1.endpoints.bot.BotService.load_conversation_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _build_bot_message_request(body, "conv-2", "user-1")
        assert result.fileIds == []
        assert result.fileData == []
        assert len(result.messages) == 1

    async def test_passes_through_provided_file_ids(self):
        body = BotChatRequest(
            message="hi", platform="discord", platform_user_id="u1", file_ids=["f1", "f2"]
        )
        with patch(
            "app.api.v1.endpoints.bot.BotService.load_conversation_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _build_bot_message_request(body, "conv-3", "user-1")
        assert result.fileIds == ["f1", "f2"]

    async def test_passes_through_provided_file_data(self):
        file_data = [FileData(fileId="f1", url="https://x/f1", filename="a.txt")]
        body = BotChatRequest(
            message="hi", platform="discord", platform_user_id="u1", file_data=file_data
        )
        with patch(
            "app.api.v1.endpoints.bot.BotService.load_conversation_history",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _build_bot_message_request(body, "conv-4", "user-1")
        assert result.fileData == file_data


class TestBotStreamFailureLogger:
    """``_bot_stream_failure_logger`` — the ``on_done`` callback for the background stream task."""

    async def test_logs_the_exception_when_the_task_failed(self):
        async def _boom():
            raise ValueError("kaboom")

        task = asyncio.ensure_future(_boom())
        with contextlib.suppress(ValueError):
            await task

        with patch("app.api.v1.endpoints.bot.log") as mock_log:
            _bot_stream_failure_logger("stream-1", "conv-1")(task)

        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs == {
            "stream_id": "stream-1",
            "conversation_id": "conv-1",
            "error_type": "ValueError",
            "error": "kaboom",
        }

    async def test_does_not_log_when_the_task_succeeded(self):
        async def _ok():
            return "fine"

        task = asyncio.ensure_future(_ok())
        await task

        with patch("app.api.v1.endpoints.bot.log") as mock_log:
            _bot_stream_failure_logger("stream-2", "conv-2")(task)

        mock_log.error.assert_not_called()

    async def test_does_not_log_when_the_task_was_cancelled(self):
        task = asyncio.ensure_future(asyncio.sleep(10))
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert task.cancelled()

        with patch("app.api.v1.endpoints.bot.log") as mock_log:
            _bot_stream_failure_logger("stream-3", "conv-3")(task)

        mock_log.error.assert_not_called()


class TestPaywallNotice:
    """``_paywall_notice`` — the free-user refusal message text."""

    def test_without_discount_code_names_only_the_checkout_link(self):
        with patch("app.api.v1.endpoints.bot.settings.PAYWALL_DISCOUNT_CODE", None):
            notice = _paywall_notice("https://pay.example/checkout")
        assert (
            notice == "GAIA is a paid product. Subscribe to Pro to keep chatting: "
            "https://pay.example/checkout"
        )

    def test_with_discount_code_appends_the_exact_code(self):
        with patch("app.api.v1.endpoints.bot.settings.PAYWALL_DISCOUNT_CODE", "SAVE10"):
            notice = _paywall_notice("https://pay.example/checkout")
        assert notice == (
            "GAIA is a paid product. Subscribe to Pro to keep chatting: "
            "https://pay.example/checkout Use code SAVE10 for a discount."
        )


class TestPaywallNoticeStream:
    """``_paywall_notice_stream`` — notice + done, no text frame."""

    async def test_yields_exactly_a_notice_frame_then_a_done_frame(self):
        response = _paywall_notice_stream("subscribe please")
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == [
            'data: {"notice": {"text": "subscribe please"}}\n\n',
            'data: {"done": true, "conversation_id": ""}\n\n',
        ]
        assert response.media_type == "text/event-stream"


class TestBotStreamEntitlementGate:
    """``_bot_stream_entitlement_gate`` — plan-required and subscription gates."""

    async def test_plan_required_refuses_before_the_subscription_check(self):
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.api.v1.endpoints.bot.is_subscription_active", new_callable=AsyncMock
            ) as mock_sub_active,
            patch("app.api.v1.endpoints.bot._capture_bot_turn_refused") as mock_capture,
        ):
            result = await _bot_stream_entitlement_gate("user-1", "imessage")

        assert result is not None
        chunks = [chunk async for chunk in result.body_iterator]
        payload = json.loads(chunks[0][len("data: ") : -2])
        assert payload == {"error": BOT_STREAM_ERROR_PLAN_REQUIRED}
        mock_capture.assert_called_once_with("user-1", "imessage", "plan_required")
        mock_sub_active.assert_not_called()

    async def test_subscription_required_returns_the_paywall_notice_stream(self):
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.v1.endpoints.bot.is_subscription_active",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.v1.endpoints.bot._bot_upgrade_url",
                new_callable=AsyncMock,
                return_value="https://pay.example/checkout",
            ),
            patch("app.api.v1.endpoints.bot._capture_bot_turn_refused") as mock_capture,
            patch("app.api.v1.endpoints.bot.settings.PAYWALL_DISCOUNT_CODE", None),
        ):
            result = await _bot_stream_entitlement_gate("user-1", "discord")

        assert result is not None
        chunks = [chunk async for chunk in result.body_iterator]
        notice_payload = json.loads(chunks[0][len("data: ") : -2])
        assert notice_payload["notice"]["text"] == (
            "GAIA is a paid product. Subscribe to Pro to keep chatting: "
            "https://pay.example/checkout"
        )
        mock_capture.assert_called_once_with("user-1", "discord", "subscription_required")

    async def test_entitled_user_passes_through_with_no_refusal(self):
        with (
            patch(
                "app.api.v1.endpoints.bot.platform_requires_upgrade",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.api.v1.endpoints.bot.is_subscription_active",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await _bot_stream_entitlement_gate("user-1", "discord")
        assert result is None
