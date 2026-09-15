"""Deliver agent-generated chat messages to a user's linked bot platform.

The web UI receives background/proactive bot messages over a WebSocket
(conversation.new_message). Bot users have no such socket — their only
inbound path is a request/response SSE turn that has already closed by the
time a background executor finishes. This service is the bot-side equivalent
of that push: it publishes the message to the originating platform's outbound
RabbitMQ queue, which the bot process consumes and sends to the user's stored
platform_links identity. All platform formatting and sending live in the
bots — there is no Python copy.
"""

from dataclasses import dataclass

from app.db.repositories.bot_sessions import bot_session_repository
from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.services.outbound_delivery import OutboundResult, publish_outbound_message


def is_bot_platform(source: ConversationSource | str | None) -> bool:
    """Whether source is a messaging-platform bot we can deliver to."""
    return ConversationSource.coerce(source) in BOT_CONVERSATION_SOURCES


@dataclass(frozen=True)
class _ChannelTarget:
    """The exact channel a proactive message must land in (a group/channel id)."""

    destination_id: str
    is_channel: bool = True


async def _resolve_channel_target(conversation_id: str | None) -> _ChannelTarget | None:
    """Return the channel a bot conversation lives in, or None to fall back to the DM.

    A group conversation's bot_sessions row stores its channel_id; a DM
    stores None. A message created in the group must be delivered back into
    the group, not the user's DM — the bug this resolves.
    """
    if not conversation_id:
        return None
    session = await bot_session_repository.get_by_conversation_id(conversation_id)
    if session is None or session.channel_id is None:
        return None
    return _ChannelTarget(destination_id=session.channel_id)


async def deliver_message_to_platform(
    source: ConversationSource | str | None,
    user_id: str,
    text: str,
    *,
    conversation_id: str | None = None,
) -> bool:
    """Deliver text to user_id on source via the platform's outbound queue.

    conversation_id naming a group/channel conversation delivers there instead
    of the user's DM. Returns True if enqueued; non-bot sources, unlinked
    accounts, and publish failures return False — best-effort, never raises.
    """
    platform = ConversationSource.coerce(source)
    if platform is None or platform not in BOT_CONVERSATION_SOURCES:
        return False
    if not text.strip():
        return False
    target = await _resolve_channel_target(conversation_id)
    result = await publish_outbound_message(
        platform,
        user_id,
        [text],
        destination_override=target.destination_id if target else None,
        is_channel=target.is_channel if target else False,
    )
    return result is OutboundResult.PUBLISHED
