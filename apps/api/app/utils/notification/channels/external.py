"""External messaging-platform notification adapter.

Backend-originated messages for WhatsApp/Slack/Telegram/Discord are no longer
sent from Python. This adapter renders notification content to platform-agnostic
CommonMark text and posts it into the user's DM conversation through
post_to_platform_chat: saved to that conversation, published to the platform's
RabbitMQ queue (the bots own formatting and the actual send), and recorded in the
conversation's checkpoint so the user's reply is answered with it in mind.

Subclasses set only channel_type and platform.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass

from app.agents.core.background.platform_chat import post_to_platform_chat
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
from app.services.delivery.chat_channel import pick_chat_channel
from app.services.outbound_delivery import OutboundResult
from app.services.platform_link_service import linked_platforms_of
from app.utils.auth_utils import build_user_context
from app.utils.notification.channels.base import ChannelAdapter


@dataclass(slots=True, frozen=True)
class ExternalPayload:
    """What this adapter posts: the rendered CommonMark text and what produced it."""

    text: str
    origin: str
    message_class: ProactiveMessageClass


def _join_nonempty(*segments: str, sep: str = "\n") -> str:
    """Join only the non-empty segments with sep (no leading/trailing seps)."""
    return sep.join(s for s in segments if s)


class ExternalPlatformAdapter(ChannelAdapter[ExternalPayload]):
    """Publishes notification content to a platform's outbound queue."""

    @property
    @abstractmethod
    def platform(self) -> ConversationSource:
        """Conversation source whose outbound queue this adapter publishes to."""
        ...

    @property
    def channel_type(self) -> str:
        # NotificationChannel.X and ConversationSource.X.value are the same string, so
        # derive the channel type from the platform instead of restating it.
        return self.platform.value

    def can_handle(self, notification: NotificationRequest) -> bool:  # noqa: ARG002 -- polymorphic interface; implementations keep the full signature
        """Return True unconditionally; the real guards live downstream.

        External adapters are auto-injected by the orchestrator regardless of
        the explicit channel list. The orchestrator's preference check and the
        platform-link lookup in publish_outbound_message decide whether the
        message is actually delivered.
        """
        return True

    async def transform(self, notification: NotificationRequest) -> ExternalPayload:
        """Render notification content to platform-agnostic CommonMark parts.

        The bot consumer converts each part to the platform's native formatting
        before sending — no platform-specific markdown is produced here.
        """
        content = notification.content
        app_url = settings.FRONTEND_URL.rstrip("/")
        title = content.title or ""
        body = content.body or ""
        text = _join_nonempty(f"**{title}**" if title else "", body)

        if content.actions:
            links = [
                f"[{action.label}]({app_url}{action.config.redirect.url})"
                for action in content.actions
                if action.type == ActionType.REDIRECT and action.config.redirect
            ]
            if links:
                text = _join_nonempty(text, " · ".join(links), sep="\n\n")

        return ExternalPayload(
            text=text,
            origin=f"notification from {notification.source.value}",
            message_class=notification.message_class,
        )

    async def deliver(self, content: ExternalPayload, user_id: str) -> ChannelDeliveryStatus:
        """Post the rendered text into the user's DM conversation on this platform.

        Returns a success status when the broker accepts the message, an error
        when the publish itself fails (so retries/alerting fire), and a skip when
        the user has no linked account here or there is nothing to send.
        """
        if not content.text.strip():
            return self._skipped(f"{self.channel_type}: nothing to publish")
        user_doc = await user_repository.get(user_id)
        # This adapter's platform only, ignoring preferences: the orchestrator
        # already decided this channel should get the notification.
        channel = (
            pick_chat_channel([self.platform.value], linked_platforms_of(user_doc), {})
            if user_doc
            else None
        )
        if user_doc is None or channel is None:
            return self._skipped(f"{self.channel_type}: not linked")
        result = await post_to_platform_chat(
            user=build_user_context(user_doc, auth_provider=None),
            channel=channel,
            text=content.text,
            origin=content.origin,
            message_class=content.message_class,
        )
        if result is OutboundResult.PUBLISHED:
            return self._success()
        if result is OutboundResult.DEFERRED:
            # Held for quiet hours; a scheduled job posts it when they end.
            return ChannelDeliveryStatus(
                channel_type=self.channel_type, status=NotificationStatus.PENDING
            )
        if result is OutboundResult.FAILED:
            # Broker unavailable or a publish error — a real failure, not a skip,
            # so retries/alerting that key off FAILED still fire during an outage.
            return self._error(f"{self.channel_type}: outbound publish failed")
        return self._skipped(f"{self.channel_type}: not linked or nothing to publish")
