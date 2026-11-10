"""Unit tests for the WebSocket speech transport: the one outbox.message event and its two kinds."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.services.outbox.transport import ws_speech
from tests.helpers import captured_wide_event

USER_ID = "507f1f77bcf86cd799439011"
CONVERSATION_ID = "conv-1"


def _manager(**kwargs: object) -> MagicMock:
    manager = MagicMock()
    manager.broadcast_to_user = AsyncMock(**kwargs)
    return manager


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
                "msg": f"{LogTag.AGENT} publish_conversation_message: broadcast attempt failed",
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


class TestPublishNotification:
    async def test_frame_shape(self) -> None:
        manager = _manager()
        notification = {"id": "n1", "content": {"title": "Done"}}

        with patch.object(ws_speech, "websocket_manager", manager):
            await ws_speech.publish_notification(USER_ID, notification)

        manager.broadcast_to_user.assert_awaited_once_with(
            USER_ID,
            {"type": "outbox.message", "kind": "notification", "notification": notification},
        )

    async def test_a_failed_publish_raises(self) -> None:
        manager = _manager(side_effect=RuntimeError("redis down"))

        with patch.object(ws_speech, "websocket_manager", manager):
            with pytest.raises(RuntimeError, match="redis down"):
                await ws_speech.publish_notification(USER_ID, {})
