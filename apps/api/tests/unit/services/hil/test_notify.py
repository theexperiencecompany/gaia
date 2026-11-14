"""A pending approval reaches the user's phones as one push keyed by the approval."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import NAMESPACE_URL, uuid5

import time_machine

from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.hil.notify import notify_approval_pending

from .conftest import CONVERSATION_ID, USER_ID


@time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
async def test_a_pending_approval_is_pushed_once_with_what_it_asks() -> None:
    with patch("app.services.hil.notify.notification_service.notify", new=AsyncMock()) as notify:
        await notify_approval_pending(USER_ID, CONVERSATION_ID, "ap_1", "Send the deck to Bob")

    notify.assert_awaited_once_with(
        NotificationRequest(
            id=str(uuid5(NAMESPACE_URL, f"gaia-notification:{USER_ID}:approval:ap_1:")),
            user_id=USER_ID,
            source=NotificationSourceEnum.APPROVAL,
            channels=[ChannelConfig(channel_type="push")],
            content=NotificationContent(
                title="GAIA needs your approval", body="Send the deck to Bob"
            ),
            metadata={
                "type": "hil_approval",
                "conversation_id": CONVERSATION_ID,
                "approval_id": "ap_1",
            },
        )
    )
