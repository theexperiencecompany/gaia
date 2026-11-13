"""Unit tests for the WebSocket speech transport: the one outbox.message event and its two kinds."""

from unittest.mock import AsyncMock, MagicMock, patch

from app.constants.log_tags import LogTag
from app.constants.websocket import ReportSettledOutcome
from app.services.outbox.transport import ws_speech
from tests.helpers import captured_wide_event

USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"


def _manager(**kwargs: object) -> MagicMock:
    manager = MagicMock()
    manager.broadcast_to_user = AsyncMock(**kwargs)
    return manager


class TestPublishReportSettled:
    async def test_frame_shape(self) -> None:
        manager = _manager()

        with patch.object(ws_speech, "websocket_manager", manager):
            await ws_speech.publish_report_settled(
                USER_ID, CONVERSATION_ID, "bot-1", ReportSettledOutcome.RECORDED
            )

        manager.broadcast_to_user.assert_awaited_once_with(
            USER_ID,
            {
                "type": "outbox.message",
                "kind": "report_settled",
                "conversation_id": CONVERSATION_ID,
                "message_id": "bot-1",
                "outcome": "recorded",
            },
        )


class TestPublishConversationMessage:
    async def test_frame_shape(self) -> None:
        manager = _manager()
        message = {"type": "bot", "response": "hi", "message_id": "m1"}

        with patch.object(ws_speech, "websocket_manager", manager):
            await ws_speech.publish_conversation_message(USER_ID, CONVERSATION_ID, message)

        manager.broadcast_to_user.assert_awaited_once_with(
            USER_ID,
            {
                "type": "outbox.message",
                "kind": "conversation_message",
                "conversation_id": CONVERSATION_ID,
                "message": message,
            },
        )

    async def test_a_failed_push_is_retried_once_and_logged(self) -> None:
        manager = _manager(side_effect=[RuntimeError("socket gone"), None])

        async with captured_wide_event() as event:
            with (
                patch.object(ws_speech, "websocket_manager", manager),
                patch.object(ws_speech, "WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS", 0),
            ):
                await ws_speech.publish_conversation_message(USER_ID, CONVERSATION_ID, {})

        assert manager.broadcast_to_user.await_count == 2
        assert event["warnings"] == [
            {
                "msg": f"{LogTag.AGENT} outbox broadcast attempt failed",
                "attempt": 1,
                "user_id": USER_ID,
                "error": "socket gone",
            }
        ]

    async def test_two_failures_are_logged_and_not_raised(self) -> None:
        manager = _manager(side_effect=RuntimeError("socket gone"))

        async with captured_wide_event() as event:
            with (
                patch.object(ws_speech, "websocket_manager", manager),
                patch.object(ws_speech, "WEBSOCKET_BROADCAST_RETRY_DELAY_SECONDS", 0),
            ):
                await ws_speech.publish_conversation_message(USER_ID, CONVERSATION_ID, {})

        assert manager.broadcast_to_user.await_count == 2
        assert [w["attempt"] for w in event["warnings"]] == [1, 2]
