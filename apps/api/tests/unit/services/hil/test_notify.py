"""A pending approval in a chat a bot follows reaches the user's phones as one push keyed by the approval."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import NAMESPACE_URL, uuid5

import time_machine

from app.constants.chat import ConversationSource
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedApproval, GatedCall
from app.utils.artifact_utils import FILE_LINKS

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.notify"


@time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
async def test_a_pending_approval_is_pushed_once_with_what_it_asks() -> None:
    approval = GatedApproval(
        approval_id="ap_1",
        stream_id="stream-1",
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="call-1", args={"to": "bob@x.com"}),
        summary="Send the deck to Bob",
        question="OK to send the deck to Bob?",
        integration_name="Gmail",
    )
    with (
        patch(
            f"{MODULE}.conversation_repository.get_source",
            new=AsyncMock(return_value=ConversationSource.TELEGRAM),
        ),
        patch(f"{MODULE}.notification_service.notify", new=AsyncMock()) as notify,
    ):
        await notify_approval_pending(approval)

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
            message=(
                "**OK to send the deck to Bob?**\n\n"
                f"[Approve or decline it in GAIA]({FILE_LINKS.conversation_page(CONVERSATION_ID)})"
            ),
        )
    )
