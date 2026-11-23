"""External messaging-platform notification adapter.

Renders the notification as CommonMark and posts it into the user's DM conversation
on the platform through post_to_platform_chat, which holds it for quiet hours and logs
it there as a Notice the bot's follower sends. Subclasses set only the platform.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

from app.agents.core.background.platform_chat import ProactiveMessage, post_to_platform_chat
from app.config.settings import settings
from app.constants.notifications import ProactiveMessageClass
from app.db.repositories.users import user_repository
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    ActionType,
    ChannelDeliveryStatus,
    NotificationRequest,
    NotificationStatus,
)
from app.services.delivery.chat_channel import channel_for
from app.services.outbound_delivery import OutboundResult
from app.utils.auth_utils import build_user_context
from app.utils.notification.channels.base import ChannelAdapter


@dataclass(slots=True, frozen=True)
class ExternalPayload:
    """What this adapter posts: the rendered text, what produced it, and the notification that keys it."""

    notification_id: str
    text: str
    origin: str
    message_class: ProactiveMessageClass


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
    """Logs notification content in the user's DM conversation on a platform."""

    @property
    @abstractmethod
    def platform(self) -> ConversationSource:
        """Conversation source whose DM this adapter logs into."""
        ...

    @property
    def channel_type(self) -> str:
        # NotificationChannel.X and ConversationSource.X.value are the same string, so
        # derive the channel type from the platform instead of restating it.
        return self.platform.value

    def can_handle(self, notification: NotificationRequest) -> bool:  # noqa: ARG002 -- polymorphic interface; implementations keep the full signature
        """Return True: an unlinked platform is a skip, decided when sending."""
        return True

    async def transform(self, notification: NotificationRequest) -> ExternalPayload:
        """Render the text once; the bot's follower converts it to the platform's formatting."""
        return ExternalPayload(
            notification_id=notification.id,
            text=render_notification_text(notification),
            origin=notice_origin(notification),
            message_class=notification.message_class,
        )

    async def deliver(self, content: ExternalPayload, user_id: str) -> ChannelDeliveryStatus:
        """Post the text into the user's DM on this platform, keyed by the notification so a retry posts it once.

        PENDING when quiet hours hold it, an error when the post fails, and a skip when
        the user has no account linked here or there is nothing to send.
        """
        if not content.text.strip():
            return self._skipped(f"{self.channel_type}: nothing to send")
        user_doc = await user_repository.get(user_id)
        # The orchestrator already decided this channel should get the notification.
        channel = channel_for(user_doc, self.platform) if user_doc else None
        if user_doc is None or channel is None:
            return self._skipped(f"{self.channel_type}: not linked")
        result = await post_to_platform_chat(
            user=build_user_context(user_doc, auth_provider=None),
            channel=channel,
            message=ProactiveMessage(
                notice_id=f"notice:{content.notification_id}",
                text=content.text,
                origin=content.origin,
                message_class=content.message_class,
            ),
        )
        if result is OutboundResult.PUBLISHED:
            return self._success()
        if result is OutboundResult.DEFERRED:
            # Held for quiet hours; a scheduled job posts it when they end.
            return ChannelDeliveryStatus(
                channel_type=self.channel_type, status=NotificationStatus.PENDING
            )
        if result is OutboundResult.FAILED:
            return self._error(f"{self.channel_type}: outbound post failed")
        return self._skipped(f"{self.channel_type}: not linked or nothing to send")
