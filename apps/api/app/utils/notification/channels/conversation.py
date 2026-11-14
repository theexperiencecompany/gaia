"""The conversation a fact belongs to: logged there as a Notice, which every device and bot reads off its events."""

from dataclasses import dataclass

from app.constants.notifications import CHANNEL_TYPE_CONVERSATION
from app.models.conversation_log_models import Notice
from app.models.notification.notification_models import ChannelDeliveryStatus, NotificationRequest
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.utils.errors import ConversationNotFoundError
from app.utils.notification.channels.base import ChannelAdapter
from app.utils.notification.channels.external import notice_origin, render_notification_text


@dataclass(slots=True, frozen=True)
class ConversationPayload:
    """The Notice the conversation logs, and the notification that keys it."""

    conversation_id: str
    notification_id: str
    text: str
    origin: str


class ConversationChannelAdapter(ChannelAdapter[ConversationPayload]):
    """Delivers into request.conversation_id; routing only picks it for a request that names one."""

    @property
    def channel_type(self) -> str:
        return CHANNEL_TYPE_CONVERSATION

    def can_handle(self, notification: NotificationRequest) -> bool:
        """Return whether the notification belongs to a conversation."""
        return notification.conversation_id is not None

    async def transform(self, notification: NotificationRequest) -> ConversationPayload:
        """Carry the text a chat reads and the conversation it goes to."""
        if notification.conversation_id is None:
            raise ValueError("a conversation notice needs the notification's conversation_id")
        return ConversationPayload(
            conversation_id=notification.conversation_id,
            notification_id=notification.id,
            text=render_notification_text(notification),
            origin=notice_origin(notification),
        )

    async def deliver(self, content: ConversationPayload, user_id: str) -> ChannelDeliveryStatus:
        """Log the Notice under the notification's id, so a retried notification logs it once."""
        if not content.text.strip():
            return self._skipped("conversation: nothing to say")
        notice = Notice(
            id=f"notice:{content.notification_id}", text=content.text, origin=content.origin
        )
        try:
            await accept(runtime_ports(), content.conversation_id, user_id, notice)
        except ConversationNotFoundError:
            return self._skipped("conversation: deleted")
        return self._success()
