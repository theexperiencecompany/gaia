"""post_to_platform_chat: log one proactive message as a Notice in the user's DM, or hold it for quiet hours."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from unittest.mock import AsyncMock, MagicMock, patch

import time_machine

from app.agents.core.background import platform_chat
from app.constants.notifications import (
    DEFERRED_CHAT_MESSAGE_JOB_PREFIX,
    DEFERRED_CHAT_MESSAGE_TASK,
    ProactiveMessageClass,
)
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.models.quiet_hours_models import QuietHours
from app.models.user_models import AuthenticatedUser, UserDocument
from app.services.bot_service import BotService
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.utils.redis_utils import RedisPoolManager
from shared.py.conversation_wire import NEW_MESSAGE_BREAKER

USER = AuthenticatedUser(user_id="user-1", email="u@gaia.local")
CHANNEL = ChatChannel(source=ConversationSource.TELEGRAM, platform_user_id="tg-7", basis="priority")
TEXT = f"Invoice overdue.{NEW_MESSAGE_BREAKER}Chase them?"
NOON_UTC = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
NIGHT_UTC = datetime(2026, 10, 14, 23, 30, tzinfo=UTC)
AWAKE_USER = UserDocument(timezone="UTC")
POOL = MagicMock(name="arq-pool")
IMAGE_URL = "https://cdn.test/brief.png"


@dataclass
class _Posted:
    """Every seam one post touched, and what it returned."""

    session: AsyncMock
    accept: AsyncMock
    ports: MagicMock
    returned: OutboundResult

    @property
    def notice(self) -> Notice:
        conversation_id, user_id, entry = self.accept.await_args.args[1:]
        assert (conversation_id, user_id) == ("dm-conv", "user-1")
        assert isinstance(entry, Notice)
        return entry


async def _post(text: str = TEXT, image_url: str | None = None) -> _Posted:
    session = AsyncMock(return_value="dm-conv")
    accept = AsyncMock()
    ports = MagicMock()
    with (
        patch.object(BotService, "get_or_create_session", session),
        patch.object(platform_chat, "accept", accept),
        patch.object(platform_chat, "runtime_ports", ports),
        # Noon on a UTC clock: outside the default 22-8 quiet hours.
        patch.object(user_repository, "get", AsyncMock(return_value=AWAKE_USER)),
        time_machine.travel(NOON_UTC, tick=False),
    ):
        returned = await platform_chat.post_to_platform_chat(
            user=USER,
            channel=CHANNEL,
            message=platform_chat.ProactiveMessage(
                notice_id="notice:n-1",
                text=text,
                origin="notification from ai_agent",
                message_class=ProactiveMessageClass.ROUTINE,
                image_url=image_url,
            ),
        )
    return _Posted(session, accept, ports, returned)


async def test_the_message_goes_to_the_users_dm_session() -> None:
    posted = await _post()

    assert posted.session.await_args.kwargs == {
        "platform": "telegram",
        "platform_user_id": "tg-7",
        "channel_id": None,
        "user": USER,
        "is_dm": True,
    }


async def test_it_is_logged_as_one_notice_keyed_by_the_callers_id() -> None:
    posted = await _post()

    assert posted.returned is OutboundResult.PUBLISHED
    posted.accept.assert_awaited_once()
    assert posted.accept.await_args.args[0] is posted.ports.return_value
    assert posted.notice == Notice(
        id="notice:n-1", text=TEXT, origin="notification from ai_agent", image_url=None
    )


async def test_nothing_to_send_is_skipped_and_logs_nothing() -> None:
    posted = await _post(text="  ")

    assert posted.returned is OutboundResult.SKIPPED
    posted.accept.assert_not_awaited()
    posted.session.assert_not_awaited()


async def test_an_image_rides_on_the_notice_with_the_text_as_its_caption() -> None:
    posted = await _post(text="Two replies need you.", image_url=IMAGE_URL)

    assert (posted.notice.text, posted.notice.image_url) == ("Two replies need you.", IMAGE_URL)


async def test_an_overlong_first_bubble_is_split_so_the_caption_fits_before_the_later_bubbles() -> (
    None
):
    posted = await _post(
        text="\n\n".join(["a" * 700, "b" * 700]) + f"{NEW_MESSAGE_BREAKER}After.",
        image_url=IMAGE_URL,
    )

    assert posted.notice.text.split(NEW_MESSAGE_BREAKER) == ["a" * 700, "b" * 700, "After."]


async def test_without_an_image_a_long_first_bubble_is_left_whole() -> None:
    long_text = "\n\n".join(["a" * 700, "b" * 700])

    posted = await _post(text=long_text)

    assert posted.notice.text == long_text


class TestQuietHours:
    """The chokepoint holds a message inside the user's window for a job at its end."""

    async def _post_at(
        self,
        now: datetime,
        message_class: ProactiveMessageClass,
        user: UserDocument | None = AWAKE_USER,
        text: str = TEXT,
        image_url: str | None = None,
    ) -> tuple[OutboundResult, AsyncMock, AsyncMock]:
        enqueue = AsyncMock()
        publish = AsyncMock()
        get_user = AsyncMock(side_effect=lambda user_id: user if user_id == USER.user_id else None)
        with (
            patch.object(user_repository, "get", get_user),
            patch.object(platform_chat, "enqueue_worker_job", enqueue),
            patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=POOL)),
            patch.object(BotService, "get_or_create_session", AsyncMock(return_value="dm")),
            patch.object(platform_chat, "accept", publish),
            patch.object(platform_chat, "runtime_ports", MagicMock()),
            time_machine.travel(now, tick=False),
        ):
            result = await platform_chat.post_to_platform_chat(
                user=USER,
                channel=CHANNEL,
                message=platform_chat.ProactiveMessage(
                    notice_id="notice:n-1",
                    text=text,
                    origin="origin",
                    message_class=message_class,
                    image_url=image_url,
                ),
            )
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
            basis="priority",
            message=platform_chat.ProactiveMessage(
                notice_id="notice:n-1",
                text=TEXT,
                origin="origin",
                message_class=ProactiveMessageClass.ROUTINE,
            ),
        )
        assert enqueue.await_args.kwargs["_defer_until"] == datetime(2026, 10, 15, 8, tzinfo=UTC)
        assert re.fullmatch(
            f"{DEFERRED_CHAT_MESSAGE_JOB_PREFIX}[0-9a-f]{{32}}",
            enqueue.await_args.kwargs["_job_id"],
        )

    async def test_a_held_message_keeps_its_image_for_the_morning(self) -> None:
        _, enqueue, _ = await self._post_at(
            NIGHT_UTC, ProactiveMessageClass.ROUTINE, image_url=IMAGE_URL
        )

        assert enqueue.await_args.args[2].message.image_url == IMAGE_URL

    async def test_the_users_own_window_and_clock_decide(self) -> None:
        # 12:00 UTC is 17:30 in Kolkata, inside a 17-19 window that ends 13:30 UTC.
        user = UserDocument(
            timezone="Asia/Kolkata",
            quiet_hours=QuietHours(enabled=True, start_hour=17, end_hour=19),
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

    async def test_the_result_of_a_run_let_through_as_urgent_is_sent_inside_the_window(
        self,
    ) -> None:
        result, enqueue, publish = await self._post_at(NIGHT_UTC, ProactiveMessageClass.URGENT)

        assert result is OutboundResult.PUBLISHED
        publish.assert_awaited_once()
        enqueue.assert_not_awaited()

    async def test_switched_off_quiet_hours_hold_nothing(self) -> None:
        user = UserDocument(
            timezone="UTC", quiet_hours=QuietHours(enabled=False, start_hour=22, end_hour=8)
        )
        result, enqueue, _ = await self._post_at(NIGHT_UTC, ProactiveMessageClass.ROUTINE, user)

        assert result is OutboundResult.PUBLISHED
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
            timezone="UTC", quiet_hours=QuietHours(enabled=True, start_hour=22, end_hour=9)
        )
        _, other_release, _ = await self._post_at(
            NIGHT_UTC, ProactiveMessageClass.ROUTINE, moved_window
        )

        job_ids = {
            enqueue.await_args.kwargs["_job_id"] for enqueue in (first, other_text, other_release)
        }
        assert len(job_ids) == 3
