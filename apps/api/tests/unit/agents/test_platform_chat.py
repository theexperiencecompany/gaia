"""post_to_platform_chat: save, send, and remember one proactive message in the user's DM."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
import time_machine

from app.agents.core.background import platform_chat
from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.constants.notifications import (
    DEFERRED_CHAT_MESSAGE_JOB_PREFIX,
    DEFERRED_CHAT_MESSAGE_TASK,
    ProactiveMessageClass,
)
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import QuietHours
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult

USER = AuthenticatedUser(user_id="user-1", email="u@gaia.local")
CHANNEL = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-7")
TEXT = f"Invoice overdue.{NEW_MESSAGE_BREAKER}Chase them?"
NOON_UTC = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
NIGHT_UTC = datetime(2026, 10, 14, 23, 30, tzinfo=UTC)
AWAKE_USER = UserDocument(timezone="UTC")
POOL = MagicMock(name="arq-pool")


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
        # Noon on a UTC clock: outside the default 22-8 quiet hours.
        patch.object(platform_chat.user_repository, "get", AsyncMock(return_value=AWAKE_USER)),
        time_machine.travel(NOON_UTC, tick=False),
    ):
        returned = await platform_chat.post_to_platform_chat(
            user=USER,
            channel=CHANNEL,
            text=TEXT,
            origin="notification from ai_agent",
            message_class=ProactiveMessageClass.ROUTINE,
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


IMAGE = platform_chat.PlatformImage(url="https://cdn.test/brief.png", filename="brief.png")


async def _post_with_image(text: str, photo: OutboundResult) -> tuple[_Posted, AsyncMock]:
    session = AsyncMock(return_value="dm-conv")
    save = AsyncMock()
    publish = AsyncMock(return_value=OutboundResult.PUBLISHED)
    send_photo = AsyncMock(return_value=photo)
    record = AsyncMock()
    with (
        patch.object(platform_chat.BotService, "get_or_create_session", session),
        patch.object(platform_chat, "update_messages", save),
        patch.object(platform_chat, "publish_outbound_message", publish),
        patch.object(platform_chat, "publish_outbound_photo", send_photo),
        patch.object(platform_chat, "record_platform_delivery", record),
        patch.object(platform_chat, "log") as log,
        patch.object(platform_chat.user_repository, "get", AsyncMock(return_value=AWAKE_USER)),
        time_machine.travel(NOON_UTC, tick=False),
    ):
        returned = await platform_chat.post_to_platform_chat(
            user=USER,
            channel=CHANNEL,
            text=text,
            origin="daily brief",
            message_class=ProactiveMessageClass.ROUTINE,
            image=IMAGE,
        )
    return _Posted(session, save, publish, record, log, returned), send_photo


async def test_an_image_goes_out_as_one_photo_with_the_text_as_its_caption() -> None:
    posted, send_photo = await _post_with_image("Two replies need you.", OutboundResult.PUBLISHED)

    send_photo.assert_awaited_once_with(
        ConversationSource.TELEGRAM,
        "user-1",
        "https://cdn.test/brief.png",
        "brief.png",
        caption="Two replies need you.",
        destination_override="tg-7",
    )
    posted.publish.assert_not_awaited()
    assert posted.returned is OutboundResult.PUBLISHED
    posted.record.assert_awaited_once_with(
        "dm-conv", "[Delivered to the user on Telegram (daily brief)]: Two replies need you."
    )


async def test_the_first_bubble_captions_the_image_and_the_rest_follow_as_messages() -> None:
    posted, send_photo = await _post_with_image(
        f"Two replies need you.{NEW_MESSAGE_BREAKER}Priya first.{NEW_MESSAGE_BREAKER}Then Dhruv.",
        OutboundResult.PUBLISHED,
    )

    assert send_photo.await_args.kwargs["caption"] == "Two replies need you."
    assert posted.publish.await_args.args == (
        ConversationSource.TELEGRAM,
        "user-1",
        ["Priya first.", "Then Dhruv."],
    )


async def test_an_overlong_first_bubble_continues_before_the_later_bubbles() -> None:
    posted, send_photo = await _post_with_image(
        "\n\n".join(["a" * 700, "b" * 700]) + f"{NEW_MESSAGE_BREAKER}After.",
        OutboundResult.PUBLISHED,
    )

    assert send_photo.await_args.kwargs["caption"] == "a" * 700
    assert posted.publish.await_args.args[2] == ["b" * 700, "After."]


async def test_a_caption_past_the_platform_limit_continues_as_follow_up_text() -> None:
    long_text = "\n\n".join(["a" * 700, "b" * 700])

    posted, send_photo = await _post_with_image(long_text, OutboundResult.PUBLISHED)

    assert send_photo.await_args.kwargs["caption"] == "a" * 700
    assert posted.publish.await_args.args == (ConversationSource.TELEGRAM, "user-1", ["b" * 700])
    assert posted.publish.await_args.kwargs == {"destination_override": "tg-7"}


async def test_a_failed_photo_is_a_failed_post_and_sends_no_follow_up() -> None:
    posted, _ = await _post_with_image("\n\n".join(["a" * 700, "b" * 700]), OutboundResult.FAILED)

    assert posted.returned is OutboundResult.FAILED
    posted.publish.assert_not_awaited()
    posted.record.assert_not_awaited()


async def test_the_dm_saves_the_text_the_image_carried() -> None:
    posted, _ = await _post_with_image("Two replies need you.", OutboundResult.PUBLISHED)

    (message,) = posted.save.await_args.args[0].messages
    assert message.response == "Two replies need you."


class TestQuietHours:
    """The chokepoint holds a message inside the user's window for a job at its end."""

    async def _post_at(
        self,
        now: datetime,
        message_class: ProactiveMessageClass,
        user: UserDocument | None = AWAKE_USER,
        text: str = TEXT,
    ) -> tuple[OutboundResult, AsyncMock, AsyncMock]:
        enqueue = AsyncMock()
        publish = AsyncMock(return_value=OutboundResult.PUBLISHED)
        get_user = AsyncMock(return_value=user)
        with (
            patch.object(platform_chat.user_repository, "get", get_user),
            patch.object(platform_chat, "enqueue_worker_job", enqueue),
            patch.object(platform_chat.RedisPoolManager, "get_pool", AsyncMock(return_value=POOL)),
            patch.object(
                platform_chat.BotService, "get_or_create_session", AsyncMock(return_value="dm")
            ),
            patch.object(platform_chat, "update_messages", AsyncMock()),
            patch.object(platform_chat, "publish_outbound_message", publish),
            patch.object(platform_chat, "record_platform_delivery", AsyncMock()),
            time_machine.travel(now, tick=False),
        ):
            result = await platform_chat.post_to_platform_chat(
                user=USER, channel=CHANNEL, text=text, origin="origin", message_class=message_class
            )
        get_user.assert_awaited_once_with("user-1")
        return result, enqueue, publish

    async def test_a_routine_message_in_the_window_is_scheduled_for_its_end(self) -> None:
        result, enqueue, publish = await self._post_at(NIGHT_UTC, ProactiveMessageClass.ROUTINE)

        assert result is OutboundResult.DEFERRED
        publish.assert_not_awaited()
        (pool, task, message) = enqueue.await_args.args
        assert pool is POOL
        assert task == DEFERRED_CHAT_MESSAGE_TASK
        assert message == platform_chat.DeferredChatMessage(
            user_id="user-1",
            source=ConversationSource.TELEGRAM,
            platform_user_id="tg-7",
            text=TEXT,
            origin="origin",
            message_class=ProactiveMessageClass.ROUTINE,
        )
        assert enqueue.await_args.kwargs["_defer_until"] == datetime(2026, 10, 15, 8, tzinfo=UTC)
        assert re.fullmatch(
            f"{DEFERRED_CHAT_MESSAGE_JOB_PREFIX}[0-9a-f]{{32}}",
            enqueue.await_args.kwargs["_job_id"],
        )

    async def test_the_users_own_window_and_clock_decide(self) -> None:
        # 12:00 UTC is 17:30 in Kolkata, inside a 17-19 window that ends 13:30 UTC.
        user = UserDocument(
            timezone="Asia/Kolkata", quiet_hours=QuietHours(start_hour=17, end_hour=19)
        )
        result, enqueue, _ = await self._post_at(NOON_UTC, ProactiveMessageClass.ROUTINE, user)

        assert result is OutboundResult.DEFERRED
        assert enqueue.await_args.kwargs["_defer_until"] == datetime(
            2026, 10, 14, 13, 30, tzinfo=UTC
        )

    async def test_a_user_timed_reminder_is_sent_inside_the_window(self) -> None:
        result, enqueue, publish = await self._post_at(NIGHT_UTC, ProactiveMessageClass.USER_TIMED)

        assert result is OutboundResult.PUBLISHED
        publish.assert_awaited_once()
        enqueue.assert_not_awaited()

    async def test_outside_the_window_it_is_sent_now(self) -> None:
        result, enqueue, publish = await self._post_at(NOON_UTC, ProactiveMessageClass.ROUTINE)

        assert result is OutboundResult.PUBLISHED
        publish.assert_awaited_once()
        enqueue.assert_not_awaited()

    async def test_the_same_message_twice_in_one_window_is_one_job(self) -> None:
        _, first, _ = await self._post_at(NIGHT_UTC, ProactiveMessageClass.ROUTINE)
        _, second, _ = await self._post_at(
            NIGHT_UTC + timedelta(minutes=20), ProactiveMessageClass.ROUTINE
        )

        assert first.await_args.kwargs["_job_id"] == second.await_args.kwargs["_job_id"]

    async def test_another_message_or_release_time_is_another_job(self) -> None:
        _, first, _ = await self._post_at(NIGHT_UTC, ProactiveMessageClass.ROUTINE)
        _, other_text, _ = await self._post_at(
            NIGHT_UTC, ProactiveMessageClass.ROUTINE, text="Rent is due."
        )
        moved_window = UserDocument(
            timezone="UTC", quiet_hours=QuietHours(start_hour=22, end_hour=9)
        )
        _, other_release, _ = await self._post_at(
            NIGHT_UTC, ProactiveMessageClass.ROUTINE, moved_window
        )

        job_ids = {
            enqueue.await_args.kwargs["_job_id"] for enqueue in (first, other_text, other_release)
        }
        assert len(job_ids) == 3

    async def test_an_unknown_user_fails_loudly(self) -> None:
        with pytest.raises(LookupError, match="^proactive message for unknown user user-1$"):
            await self._post_at(NIGHT_UTC, ProactiveMessageClass.ROUTINE, user=None)
