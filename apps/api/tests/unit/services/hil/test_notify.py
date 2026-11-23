"""A pending approval wakes its user: a push keyed by the approval, plus their chat app when no bot follows the chat."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import NAMESPACE_URL, uuid5

import time_machine

from app.constants.chat import ConversationSource
from app.constants.notifications import NotificationKind
from app.models.notification.details_models import ApprovalNotification
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
)
from app.services.delivery.chat_channel import ChatChannel, InApp, ProactiveTarget
from app.services.hil.notify import notify_approval_pending
from app.services.hil.utils import GatedApproval, GatedCall
from app.utils.artifact_utils import FILE_LINKS

from .conftest import CONVERSATION_ID, USER_ID

MODULE = "app.services.hil.notify"

APPROVAL = GatedApproval(
    approval_id="ap_1",
    stream_id="stream-1",
    user_id=USER_ID,
    conversation_id=CONVERSATION_ID,
    tool_call=GatedCall(name="GMAIL_SEND_EMAIL", id="call-1", args={"to": "bob@x.com"}),
    summary="Send the deck to Bob",
    question="OK to send the deck to Bob?",
    integration_name="Gmail",
)


def _request(channels: list[ChannelConfig]) -> NotificationRequest:
    return NotificationRequest(
        id=str(uuid5(NAMESPACE_URL, f"gaia-notification:{USER_ID}:approval:ap_1:")),
        user_id=USER_ID,
        source=NotificationSourceEnum.APPROVAL,
        channels=channels,
        content=NotificationContent(title="GAIA needs your approval", body="Send the deck to Bob"),
        details=ApprovalNotification(
            kind=NotificationKind.APPROVAL, conversation_id=CONVERSATION_ID, approval_id="ap_1"
        ),
        message=(
            "**OK to send the deck to Bob?**\n\n"
            f"[Approve or decline it in GAIA]({FILE_LINKS.conversation_page(CONVERSATION_ID)})"
        ),
    )


@contextmanager
def _user_whose_chat_app_is_telegram(source: ConversationSource) -> Iterator[AsyncMock]:
    """Only USER_ID's own conversation has a source, and only USER_ID reaches Telegram."""

    async def get_source(conversation_id: str, *, user_id: str) -> ConversationSource | None:
        return source if (conversation_id, user_id) == (CONVERSATION_ID, USER_ID) else None

    async def resolve_proactive_target(user_id: str) -> ProactiveTarget:
        if user_id == USER_ID:
            return ChatChannel(
                source=ConversationSource.TELEGRAM, platform_user_id="tg-1", basis="priority"
            )
        return InApp(reason="no_chat_app")

    with (
        patch(f"{MODULE}.conversation_repository.get_source", new=get_source),
        patch(f"{MODULE}.resolve_proactive_target", new=resolve_proactive_target),
        patch(f"{MODULE}.notification_service.notify", new=AsyncMock()) as notify,
    ):
        yield notify


@time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
async def test_an_approval_in_a_bot_followed_chat_is_only_pushed() -> None:
    with _user_whose_chat_app_is_telegram(ConversationSource.TELEGRAM) as notify:
        await notify_approval_pending(APPROVAL)

    notify.assert_awaited_once_with(_request([ChannelConfig(channel_type="push")]))


@time_machine.travel(datetime(2026, 11, 14, 12, 0, tzinfo=UTC), tick=False)
async def test_an_approval_in_background_work_also_goes_to_the_users_chat_app() -> None:
    with _user_whose_chat_app_is_telegram(ConversationSource.BACKGROUND) as notify:
        await notify_approval_pending(APPROVAL)

    notify.assert_awaited_once_with(
        _request([ChannelConfig(channel_type="push"), ChannelConfig(channel_type="telegram")])
    )
