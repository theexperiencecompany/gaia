"""The jobs that finish a proactive chat message's delivery after it was sent."""

from unittest.mock import AsyncMock, patch

from arq.worker import Retry
import pytest

from app.constants.notifications import PROACTIVE_RECORD_RETRY_DELAY, ProactiveMessageClass
from app.models.chat_models import ConversationSource
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.workers.tasks import proactive_delivery_tasks
from tests.helpers import captured_wide_event

MESSAGE = proactive_delivery_tasks.DeferredChatMessage(
    user_id="user-1",
    source=ConversationSource.TELEGRAM,
    platform_user_id="tg-7",
    text="Invoice overdue.",
    origin="notification from ai_agent",
    message_class=ProactiveMessageClass.ROUTINE,
)


class TestDeliverDeferredChatMessage:
    async def _deliver(self, user: UserDocument | None) -> tuple[str, AsyncMock, AsyncMock]:
        get_user = AsyncMock(return_value=user)
        post = AsyncMock(return_value=OutboundResult.PUBLISHED)
        with (
            patch.object(proactive_delivery_tasks.user_repository, "get", get_user),
            patch.object(proactive_delivery_tasks, "post_to_platform_chat", post),
        ):
            outcome = await proactive_delivery_tasks.deliver_deferred_chat_message({}, MESSAGE)
        return outcome, get_user, post

    async def test_the_held_message_is_posted_to_its_chat_through_the_policy(self) -> None:
        async with captured_wide_event() as event:
            outcome, get_user, post = await self._deliver(
                UserDocument(id="user-1", email="u@gaia.local", timezone="UTC")
            )

        assert outcome == "published"
        get_user.assert_awaited_once_with("user-1")
        kwargs = post.await_args.kwargs
        assert kwargs["user"].user_id == "user-1"
        assert kwargs["user"].email == "u@gaia.local"
        assert kwargs["user"].auth_provider is None
        assert kwargs["channel"] == ChatChannel(
            source=ConversationSource.TELEGRAM, platform_user_id="tg-7"
        )
        assert kwargs["text"] == "Invoice overdue."
        assert kwargs["origin"] == "notification from ai_agent"
        assert kwargs["message_class"] is ProactiveMessageClass.ROUTINE
        assert event["platform"] == "telegram"
        assert event["message_class"] == ProactiveMessageClass.ROUTINE.value

    async def test_a_user_deleted_while_it_was_held_drops_it_with_a_warning(self) -> None:
        async with captured_wide_event() as event:
            outcome, _, post = await self._deliver(None)

        assert outcome == "user_missing"
        post.assert_not_awaited()
        (warning,) = event["warnings"]
        assert warning["msg"] == "deferred chat message dropped: user no longer exists"
        assert warning["user_id"] == "user-1"


class TestRecordProactiveDelivery:
    async def test_a_free_thread_records_the_message(self) -> None:
        try_record = AsyncMock(return_value=True)
        with patch.object(proactive_delivery_tasks, "try_record_platform_delivery", try_record):
            async with captured_wide_event() as event:
                outcome = await proactive_delivery_tasks.record_proactive_delivery(
                    {}, "conv-1", "Digest is ready."
                )

        assert outcome == "recorded"
        try_record.assert_awaited_once_with("conv-1", "Digest is ready.")
        assert event["conversation_id"] == "conv-1"

    async def test_a_held_thread_retries_after_the_record_delay(self) -> None:
        held = AsyncMock(return_value=False)
        with (
            patch.object(proactive_delivery_tasks, "try_record_platform_delivery", held),
            pytest.raises(Retry) as retry,
        ):
            await proactive_delivery_tasks.record_proactive_delivery({}, "conv-1", "Digest.")

        assert retry.value.defer_score == PROACTIVE_RECORD_RETRY_DELAY.total_seconds() * 1000
