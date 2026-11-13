"""External messaging-platform notification adapter.

Renders the notification as CommonMark, publishes it to the platform's outbound
queue for the user's DM (the bot formats and sends it), then logs it in that DM's
conversation as a Notice so the next reply there knows what was already said.
Subclasses set only the platform.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

from app.config.settings import settings
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.conversation_log_models import Notice
from app.models.notification.notification_models import (
    ActionType,
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.bot_service import BotService
from app.services.conversation.log import accept
from app.services.conversation.runtime import runtime_ports
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.services.platform_link_service import linked_platforms_of
from app.utils.auth_utils import build_user_context
from app.utils.message_breaks import split_message_bubbles
from app.utils.notification.channels.base import ChannelAdapter


@dataclass(slots=True, frozen=True)
class ExternalPayload:
    """What this adapter hands the bot consumer, and what it logs once sent."""

    notification_id: str
    text: str
    origin: str


def _join_nonempty(*segments: str, sep: str = "\n") -> str:
    """Join only the non-empty segments with sep (no leading/trailing seps)."""
    return sep.join(s for s in segments if s)


def render_notification_text(notification: NotificationRequest) -> str:
    """Return what a chat reads: the producer's message, else the title, body and links."""
    if notification.message is not None:
        return notification.message
    content = notification.content
    app_url = settings.FRONTEND_URL.rstrip("/")
    title = content.title or ""
    text = _join_nonempty(f"**{title}**" if title else "", content.body or "")
    links = [
        f"[{action.label}]({app_url}{action.config.redirect.url})"
        for action in content.actions or []
        if action.type == ActionType.REDIRECT and action.config.redirect
    ]
    return _join_nonempty(text, " · ".join(links), sep="\n\n") if links else text


def notice_origin(notification: NotificationRequest) -> str:
    """Name what produced the notification, for the Notice a conversation logs."""
    return f'{notification.source.value} "{notification.content.title}" (id {notification.id})'


class ExternalPlatformAdapter(ChannelAdapter[ExternalPayload]):
    """Publishes notification content to a platform's outbound queue."""

    @property
    @abstractmethod
    def platform(self) -> ConversationSource:
        """Conversation source whose outbound queue this adapter publishes to."""
        ...

    @property
    def channel_type(self) -> str:
        # CHANNEL_TYPE_X and ConversationSource.X.value are the same string, so
        # derive the channel type from the platform instead of restating it.
        return self.platform.value

    def can_handle(self, notification: NotificationRequest) -> bool:  # noqa: ARG002 -- polymorphic interface; implementations keep the full signature
        """Return True: an unlinked platform is a skip, decided when sending."""
        return True

    async def transform(self, notification: NotificationRequest) -> ExternalPayload:
        """Render the text once; the bot converts it to the platform's formatting."""
        return ExternalPayload(
            notification_id=notification.id,
            text=render_notification_text(notification),
            origin=notice_origin(notification),
        )

    async def deliver(self, content: ExternalPayload, user_id: str) -> ChannelDeliveryStatus:
        """Publish to the user's DM on this platform, then log it in that DM's conversation.

        FAILED when the broker refused it (so alerting fires), skipped when the
        user has no account linked here or there is nothing to send.
        """
        user = await user_repository.get(user_id)
        entry = linked_platforms_of(user).get(self.platform.value) if user else None
        platform_user_id = entry.get("platformUserId") if entry else None
        if user is None or not platform_user_id:
            return self._skipped(f"{self.channel_type}: not linked")
        result = await publish_outbound_message(
            self.platform,
            user_id,
            [content.text],
            destination_override=str(platform_user_id),
            notification_id=content.notification_id,
        )
        if result is OutboundResult.FAILED:
            return self._error(f"{self.channel_type}: outbound publish failed")
        if result is OutboundResult.SKIPPED:
            return self._skipped(f"{self.channel_type}: nothing to publish")
        conversation_id = await BotService.get_or_create_session(
            platform=self.platform.value,
            platform_user_id=str(platform_user_id),
            channel_id=None,
            user=build_user_context(user, auth_provider=None),
            is_dm=True,
        )
        # The bubbles as sent: the outbound path strips control tokens and blanks.
        sent = "\n\n".join(b.strip() for b in split_message_bubbles(content.text) if b.strip())
        notice = Notice(id=f"notice:{content.notification_id}", text=sent, origin=content.origin)
        await accept(runtime_ports(), conversation_id, user_id, notice)
        return self._success()
