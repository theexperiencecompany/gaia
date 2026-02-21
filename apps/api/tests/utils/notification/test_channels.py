import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
)
from app.utils.notification.channels import TelegramChannelAdapter


def _make_notification_request() -> NotificationRequest:
    return NotificationRequest(
        user_id="user-123",
        source=NotificationSourceEnum.AI_REMINDER,
        channels=[ChannelConfig(channel_type="telegram")],
        content=NotificationContent(title="Test Title", body="Test body text"),
    )


@pytest.mark.asyncio
async def test_telegram_adapter_delivers_when_linked():
    adapter = TelegramChannelAdapter()
    notification = _make_notification_request()

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    linked_platforms = {"telegram": {"id": "9876543", "username": "testuser"}}

    with (
        patch(
            "app.utils.notification.channels.PlatformLinkService.get_linked_platforms",
            new=AsyncMock(return_value=linked_platforms),
        ),
        patch("app.utils.notification.channels.settings") as mock_settings,
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        mock_settings.TELEGRAM_BOT_TOKEN = "test-token"
        content = await adapter.transform(notification)
        result = await adapter.deliver(content, "user-123")

    assert result.status == NotificationStatus.DELIVERED
    assert result.channel_type == "telegram"
    assert result.skipped is False


@pytest.mark.asyncio
async def test_telegram_adapter_skips_when_not_linked():
    adapter = TelegramChannelAdapter()
    notification = _make_notification_request()

    with patch(
        "app.utils.notification.channels.PlatformLinkService.get_linked_platforms",
        new=AsyncMock(return_value={}),
    ):
        content = await adapter.transform(notification)
        result = await adapter.deliver(content, "user-123")

    assert result.skipped is True
    assert result.channel_type == "telegram"
