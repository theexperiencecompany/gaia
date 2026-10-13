"""post_to_platform_chat: save, send, and remember one proactive message in the user's DM."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.agents.core.background import platform_chat
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.chat_models import ConversationSource
from app.models.user_models import AuthenticatedUser
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult

USER = AuthenticatedUser(user_id="user-1", email="u@gaia.local")
CHANNEL = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-7")
TEXT = f"Invoice overdue.{NEW_MESSAGE_BREAKER}Chase them?"


@dataclass
class _Posted:
    """Every seam one post touched, and what it returned."""

    session: AsyncMock
    save: AsyncMock
    publish: AsyncMock
    record: AsyncMock
    log: MagicMock
    returned: OutboundResult


async def _post(result: OutboundResult) -> _Posted:
    session = AsyncMock(return_value="dm-conv")
    save = AsyncMock()
    publish = AsyncMock(return_value=result)
    record = AsyncMock()
    with (
        patch.object(platform_chat.BotService, "get_or_create_session", session),
        patch.object(platform_chat, "update_messages", save),
        patch.object(platform_chat, "publish_outbound_message", publish),
        patch.object(platform_chat, "record_platform_delivery", record),
        patch.object(platform_chat, "log") as log,
    ):
        returned = await platform_chat.post_to_platform_chat(
            user=USER, channel=CHANNEL, text=TEXT, origin="notification from ai_agent"
        )
    return _Posted(session, save, publish, record, log, returned)


async def test_the_message_goes_to_the_users_dm_session() -> None:
    posted = await _post(OutboundResult.PUBLISHED)

    assert posted.session.await_args.kwargs == {
        "platform": "telegram",
        "platform_user_id": "tg-7",
        "channel_id": None,
        "user": USER,
        "is_dm": True,
    }


async def test_the_dm_conversation_saves_the_whole_message_as_the_bot() -> None:
    posted = await _post(OutboundResult.PUBLISHED)

    request = posted.save.await_args.args[0]
    assert posted.save.await_args.kwargs == {"user": USER}
    assert request.conversation_id == "dm-conv"
    (message,) = request.messages
    assert (message.type, message.response) == ("bot", TEXT)
    assert datetime.fromisoformat(message.date).utcoffset() == timedelta(0)
    assert UUID(message.message_id)


async def test_it_publishes_the_bubbles_to_the_known_account() -> None:
    posted = await _post(OutboundResult.PUBLISHED)

    assert posted.publish.await_args.args == (
        ConversationSource.TELEGRAM,
        "user-1",
        ["Invoice overdue.", "Chase them?"],
    )
    assert posted.publish.await_args.kwargs == {"destination_override": "tg-7"}
    assert posted.returned is OutboundResult.PUBLISHED


async def test_a_published_message_is_recorded_in_the_dm_thread() -> None:
    posted = await _post(OutboundResult.PUBLISHED)

    posted.record.assert_awaited_once_with(
        "dm-conv",
        "[Delivered to the user on Telegram (notification from ai_agent)]: "
        "Invoice overdue.\n\nChase them?",
    )
    posted.log.info.assert_called_once()
    assert posted.log.info.call_args.kwargs == {
        "result": "published",
        "platform": "telegram",
        "conversation_id": "dm-conv",
        "message_id": posted.save.await_args.args[0].messages[0].message_id,
        "bubbles": 2,
    }


@pytest.mark.parametrize("result", [OutboundResult.SKIPPED, OutboundResult.FAILED])
async def test_an_unpublished_message_is_not_recorded(result: OutboundResult) -> None:
    posted = await _post(result)

    posted.record.assert_not_awaited()
    assert posted.returned is result


async def test_a_failed_publish_is_logged_as_an_error() -> None:
    posted = await _post(OutboundResult.FAILED)

    posted.log.error.assert_called_once()
    assert posted.log.error.call_args.args == (f"{LogTag.AGENT} proactive platform publish failed",)
    assert posted.log.error.call_args.kwargs["bubbles"] == 2
