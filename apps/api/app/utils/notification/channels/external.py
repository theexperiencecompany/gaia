"""External messaging-platform notification adapter.

Backend-originated messages for WhatsApp/Slack/Telegram/Discord are no longer
sent from Python. This adapter renders notification content to platform-agnostic
CommonMark text and publishes it to the per-platform RabbitMQ queue the bot
processes consume; the bots own all platform formatting and the actual send.

Subclasses set only ``channel_type`` and ``platform``.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

from app.config.settings import settings
from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import (
    ActionType,
    ChannelDeliveryStatus,
    NotificationRequest,
)
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.utils.notification.channels.base import ChannelAdapter


def _join_nonempty(*segments: str, sep: str = "\n") -> str:
    """Join only the non-empty segments with ``sep`` (no leading/trailing seps)."""
    return sep.join(s for s in segments if s)


class ExternalPlatformAdapter(ChannelAdapter):
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

    def can_handle(self, notification: NotificationRequest) -> bool:
        # External adapters are auto-injected by the orchestrator regardless of
        # the explicit channel list. The orchestrator's preference check and the
        # platform-link lookup in ``publish_outbound_message`` are the real guards.
        return True

    async def transform(self, notification: NotificationRequest) -> dict[str, Any]:
        """Render notification content to platform-agnostic CommonMark parts.

        The bot consumer converts each part to the platform's native formatting
        before sending — no platform-specific markdown is produced here.
        """
        content = notification.content
        rich = content.rich_content or {}
        app_url = settings.FRONTEND_URL.rstrip("/")
        title = content.title or ""
        body = content.body or ""
        header = _join_nonempty(f"**{title}**" if title else "", body)

        # Build clean parts here: drop blank/whitespace-only entries and guard
        # the untyped ``rich.messages`` against non-strings, so a workflow with
        # empty result messages never emits an empty bubble. ``publish_outbound_message``
        # also strips defensively for callers (e.g. deliver_message_to_platform)
        # that bypass ``transform``.
        if rich.get("type") == "workflow_execution":
            conversation_id = rich.get("conversation_id", "")
            footer = (
                f"[View full results]({app_url}/c/{conversation_id})" if conversation_id else ""
            )
            parts = [header, *rich.get("messages", []), footer]
            return {"parts": [p for p in parts if isinstance(p, str) and p.strip()]}

        text = header
        if content.actions:
            links = [
                f"[{action.label}]({app_url}{action.config.redirect.url})"
                for action in content.actions
                if action.type == ActionType.REDIRECT and action.config.redirect
            ]
            if links:
                text = _join_nonempty(text, " · ".join(links), sep="\n\n")

        return {"parts": [text]}

    async def deliver(self, content: dict[str, Any], user_id: str) -> ChannelDeliveryStatus:
        parts = content.get("parts", [])
        result = await publish_outbound_message(self.platform, user_id, parts)
        if result is OutboundResult.PUBLISHED:
            return self._success()
        if result is OutboundResult.FAILED:
            # Broker unavailable or a publish error — a real failure, not a skip,
            # so retries/alerting that key off FAILED still fire during an outage.
            return self._error(f"{self.channel_type}: outbound publish failed")
        return self._skipped(f"{self.channel_type}: not linked or nothing to publish")
