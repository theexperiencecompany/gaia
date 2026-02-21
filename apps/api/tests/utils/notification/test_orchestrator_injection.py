"""Tests for auto-injection of Telegram/Discord channels in the orchestrator."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.notification.notification_models import (
    ChannelConfig,
    ChannelDeliveryStatus,
    NotificationContent,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationStatus,
)
from app.utils.notification.orchestrator import NotificationOrchestrator


def _make_notification_record(channels: list[ChannelConfig]) -> NotificationRecord:
    request = NotificationRequest(
        user_id="user-abc",
        source=NotificationSourceEnum.AI_REMINDER,
        channels=channels,
        content=NotificationContent(title="Hello", body="World"),
    )
    return NotificationRecord(
        id=request.id,
        user_id=request.user_id,
        status=NotificationStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        original_request=request,
    )


def _delivered_status(channel_type: str) -> ChannelDeliveryStatus:
    return ChannelDeliveryStatus(
        channel_type=channel_type,
        status=NotificationStatus.DELIVERED,
        delivered_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_orchestrator_injects_telegram_channel():
    """Orchestrator auto-delivers via Telegram when only inapp is listed."""
    notification = _make_notification_record([ChannelConfig(channel_type="inapp")])

    storage_mock = MagicMock()
    storage_mock.save_notification = AsyncMock()
    storage_mock.update_notification = AsyncMock()

    orchestrator = NotificationOrchestrator(storage=storage_mock)

    inapp_status = _delivered_status("inapp")
    telegram_status = _delivered_status("telegram")

    telegram_deliver = AsyncMock(return_value=telegram_status)
    inapp_deliver = AsyncMock(return_value=inapp_status)

    orchestrator.channel_adapters["inapp"].deliver = inapp_deliver
    orchestrator.channel_adapters["telegram"].deliver = telegram_deliver

    with (
        patch.object(
            orchestrator,
            "_get_channel_prefs",
            new=AsyncMock(return_value={"telegram": True, "discord": True}),
        ),
        patch(
            "app.utils.notification.orchestrator.websocket_manager.broadcast_to_user",
            new=AsyncMock(),
        ),
    ):
        await orchestrator._deliver_notification(notification)

    telegram_deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_skips_telegram_when_disabled():
    """Orchestrator does NOT deliver via Telegram when preference is disabled."""
    notification = _make_notification_record([ChannelConfig(channel_type="inapp")])

    storage_mock = MagicMock()
    storage_mock.save_notification = AsyncMock()
    storage_mock.update_notification = AsyncMock()

    orchestrator = NotificationOrchestrator(storage=storage_mock)

    inapp_status = _delivered_status("inapp")
    inapp_deliver = AsyncMock(return_value=inapp_status)
    telegram_deliver = AsyncMock(return_value=_delivered_status("telegram"))

    orchestrator.channel_adapters["inapp"].deliver = inapp_deliver
    orchestrator.channel_adapters["telegram"].deliver = telegram_deliver

    with (
        patch.object(
            orchestrator,
            "_get_channel_prefs",
            new=AsyncMock(return_value={"telegram": False, "discord": False}),
        ),
        patch(
            "app.utils.notification.orchestrator.websocket_manager.broadcast_to_user",
            new=AsyncMock(),
        ),
    ):
        await orchestrator._deliver_notification(notification)

    telegram_deliver.assert_not_awaited()


@pytest.mark.asyncio
async def test_orchestrator_skips_telegram_when_already_explicitly_listed():
    """Orchestrator does not double-deliver Telegram if it is already in channels."""
    notification = _make_notification_record([ChannelConfig(channel_type="telegram")])

    storage_mock = MagicMock()
    storage_mock.save_notification = AsyncMock()
    storage_mock.update_notification = AsyncMock()

    orchestrator = NotificationOrchestrator(storage=storage_mock)

    telegram_status = _delivered_status("telegram")
    telegram_deliver = AsyncMock(return_value=telegram_status)
    orchestrator.channel_adapters["telegram"].deliver = telegram_deliver

    with (
        patch.object(
            orchestrator,
            "_get_channel_prefs",
            new=AsyncMock(return_value={"telegram": True, "discord": True}),
        ),
        patch(
            "app.utils.notification.orchestrator.websocket_manager.broadcast_to_user",
            new=AsyncMock(),
        ),
    ):
        await orchestrator._deliver_notification(notification)

    # Should be called exactly once (from the explicit channel list), not twice
    assert telegram_deliver.await_count == 1


@pytest.mark.asyncio
async def test_get_channel_prefs_returns_defaults_when_no_record():
    """_get_channel_prefs returns True for all channels when user doc is missing."""
    orchestrator = NotificationOrchestrator(storage=MagicMock())

    import app.utils.notification.orchestrator as orch_module

    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=None)

    with patch.object(orch_module, "users_collection", mock_collection):
        prefs = await orchestrator._get_channel_prefs("nonexistent-user")

    assert prefs == {"telegram": True, "discord": True}


@pytest.mark.asyncio
async def test_get_channel_prefs_reads_stored_values():
    """_get_channel_prefs correctly reads stored preferences from MongoDB."""
    orchestrator = NotificationOrchestrator(storage=MagicMock())

    fake_user = {
        "_id": "some-id",
        "notification_channel_prefs": {"telegram": False, "discord": True},
    }

    import app.utils.notification.orchestrator as orch_module

    mock_collection = MagicMock()
    mock_collection.find_one = AsyncMock(return_value=fake_user)

    # Use a valid 24-char hex ObjectId string
    valid_user_id = "507f1f77bcf86cd799439011"
    with patch.object(orch_module, "users_collection", mock_collection):
        prefs = await orchestrator._get_channel_prefs(valid_user_id)

    assert prefs == {"telegram": False, "discord": True}
