"""Reading and writing the user's chat-channel priority."""

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.notifications import DEFAULT_CHAT_CHANNEL_PRIORITY
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import (
    get_chat_channel_priority,
    set_chat_channel_priority,
)

USER_ID = "507f1f77bcf86cd799439011"


def _user(priority: list[str] | None) -> UserDocument:
    return UserDocument.model_validate(
        {"_id": USER_ID, "email": "a@b.c", "chat_channel_priority": priority}
    )


@pytest.mark.unit
class TestGetChatChannelPriority:
    async def test_returns_the_stored_order(self):
        with patch(
            "app.services.delivery.chat_channel.user_repository.get",
            new_callable=AsyncMock,
            return_value=_user(["slack", "telegram"]),
        ) as read:
            assert await get_chat_channel_priority(USER_ID) == ["slack", "telegram"]
        read.assert_awaited_once_with(USER_ID)

    async def test_falls_back_to_the_default_when_unset(self):
        with patch(
            "app.services.delivery.chat_channel.user_repository.get",
            new_callable=AsyncMock,
            return_value=_user(None),
        ):
            assert await get_chat_channel_priority(USER_ID) == list(DEFAULT_CHAT_CHANNEL_PRIORITY)

    async def test_falls_back_to_the_default_for_an_unknown_user(self):
        with patch(
            "app.services.delivery.chat_channel.user_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            assert await get_chat_channel_priority(USER_ID) == list(DEFAULT_CHAT_CHANNEL_PRIORITY)


@pytest.mark.unit
class TestSetChatChannelPriority:
    async def test_persists_and_reports_the_change(self):
        with (
            patch(
                "app.services.delivery.chat_channel.user_repository.set_chat_channel_priority",
                new_callable=AsyncMock,
            ) as save,
            patch("app.services.delivery.chat_channel.capture_event") as capture,
        ):
            await set_chat_channel_priority(USER_ID, ["discord", "slack"])

        save.assert_awaited_once_with(USER_ID, ["discord", "slack"])
        assert capture.call_args.args[0] == USER_ID
        event = capture.call_args.args[1]
        properties = capture.call_args.args[2]
        assert event == "settings:chat_channel_priority_updated"
        assert properties == {"first": "discord", "count": 2}
