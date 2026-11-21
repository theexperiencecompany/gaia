"""The job that posts a proactive chat message quiet hours held back."""

from unittest.mock import AsyncMock, patch

from app.agents.core.background.platform_chat import DeferredChatMessage, ProactiveMessage
from app.constants.notifications import ProactiveMessageClass
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.user_models import UserDocument
from app.services.delivery.chat_channel import ChatChannel
from app.services.outbound_delivery import OutboundResult
from app.workers.tasks import proactive_delivery_tasks
from tests.helpers import captured_wide_event

MESSAGE = DeferredChatMessage(
    user_id="user-1",
    source=ConversationSource.TELEGRAM,
    platform_user_id="tg-7",
    basis="priority",
    message=ProactiveMessage(
        notice_id="notice:n-1",
        text="Invoice overdue.",
        origin="notification from ai_agent",
        message_class=ProactiveMessageClass.ROUTINE,
    ),
)


class TestDeliverDeferredChatMessage:
    async def _deliver(self, user: UserDocument | None) -> tuple[str, AsyncMock, AsyncMock]:
        get_user = AsyncMock(return_value=user)
        post = AsyncMock(return_value=OutboundResult.PUBLISHED)
        with (
            patch.object(user_repository, "get", get_user),
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
            source=ConversationSource.TELEGRAM, platform_user_id="tg-7", basis="priority"
        )
        assert kwargs["message"] == MESSAGE.message
        assert event["platform"] == "telegram"
        assert event["message_class"] == ProactiveMessageClass.ROUTINE.value

    async def test_the_held_image_goes_out_with_the_message(self) -> None:
        held = MESSAGE.model_copy(
            update={
                "message": MESSAGE.message.model_copy(
                    update={"image_url": "https://cdn.test/brief.png"}
                )
            }
        )
        post = AsyncMock(return_value=OutboundResult.PUBLISHED)
        with (
            patch.object(user_repository, "get", AsyncMock(return_value=UserDocument(id="user-1"))),
            patch.object(proactive_delivery_tasks, "post_to_platform_chat", post),
        ):
            await proactive_delivery_tasks.deliver_deferred_chat_message({}, held)

        assert post.await_args.kwargs["message"].image_url == "https://cdn.test/brief.png"

    async def test_a_user_deleted_while_it_was_held_drops_it_with_a_warning(self) -> None:
        async with captured_wide_event() as event:
            outcome, _, post = await self._deliver(None)

        assert outcome == "user_missing"
        post.assert_not_awaited()
        (warning,) = event["warnings"]
        assert warning["msg"] == "deferred chat message dropped: user no longer exists"
        assert warning["user_id"] == "user-1"
