"""Deliver agent-generated chat messages to a user's linked bot platform.

The web UI receives background/proactive bot messages over a WebSocket
(``conversation.new_message``). Bot users have no such socket — their only
inbound path is a request/response SSE turn that has already closed by the
time a background executor finishes. This service is the bot-side equivalent
of that push: it routes the message to the originating platform (WhatsApp,
Telegram, Discord, Slack) using the same channel adapters the notification
system uses, which DM the user via their stored ``platform_links`` identity.
"""

from app.models.chat_models import ConversationSource
from app.models.notification.notification_models import NotificationStatus
from app.utils.notification.channels import (
    ChannelAdapter,
    DiscordChannelAdapter,
    SlackChannelAdapter,
    TelegramChannelAdapter,
    WhatsAppChannelAdapter,
)
from shared.py.wide_events import log

# Conversation sources that map to a messaging-platform bot, and the adapter
# that delivers to each. Keyed by the ConversationSource enum so routing never
# compares raw strings.
_PLATFORM_ADAPTERS: dict[ConversationSource, type[ChannelAdapter]] = {
    ConversationSource.WHATSAPP: WhatsAppChannelAdapter,
    ConversationSource.TELEGRAM: TelegramChannelAdapter,
    ConversationSource.DISCORD: DiscordChannelAdapter,
    ConversationSource.SLACK: SlackChannelAdapter,
}


def is_bot_platform(source: ConversationSource | str | None) -> bool:
    """Whether ``source`` is a messaging-platform bot we can deliver to."""
    return ConversationSource.coerce(source) in _PLATFORM_ADAPTERS


async def deliver_message_to_platform(
    source: ConversationSource | str | None, user_id: str, text: str
) -> bool:
    """Deliver ``text`` to ``user_id``'s linked account on ``source``.

    Returns True only if the platform accepted the message. Non-bot sources,
    unlinked accounts, and send failures all return False — this is a
    best-effort side channel, never raising into the caller's flow.
    """
    platform = ConversationSource.coerce(source)
    adapter_cls = _PLATFORM_ADAPTERS.get(platform) if platform else None
    if adapter_cls is None:
        return False
    if not text.strip():
        return False

    try:
        result = await adapter_cls().deliver_text(text, user_id)
    except Exception as e:
        log.error("deliver_message_to_platform: delivery raised", source=str(source), error=str(e))
        return False

    delivered = result.status == NotificationStatus.DELIVERED and not result.skipped
    if not delivered:
        log.warning(
            "deliver_message_to_platform: not delivered",
            source=platform.value,
            skipped=result.skipped,
            error=result.error_message,
        )
    return delivered
