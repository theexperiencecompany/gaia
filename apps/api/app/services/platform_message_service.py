"""Deliver agent-generated chat messages to a user's linked bot platform.

The web UI receives background/proactive bot messages over a WebSocket
(``conversation.new_message``). Bot users have no such socket — their only
inbound path is a request/response SSE turn that has already closed by the
time a background executor finishes. This service is the bot-side equivalent
of that push: it publishes the message to the originating platform's outbound
RabbitMQ queue, which the bot process consumes and sends to the user's stored
``platform_links`` identity. All platform formatting and sending live in the
bots — there is no Python copy.
"""

from app.models.chat_models import BOT_CONVERSATION_SOURCES, ConversationSource
from app.services.outbound_delivery import publish_outbound_message


def is_bot_platform(source: ConversationSource | str | None) -> bool:
    """Whether ``source`` is a messaging-platform bot we can deliver to."""
    return ConversationSource.coerce(source) in BOT_CONVERSATION_SOURCES


async def deliver_message_to_platform(
    source: ConversationSource | str | None, user_id: str, text: str
) -> bool:
    """Deliver ``text`` to ``user_id``'s linked account on ``source`` by
    publishing to the platform's outbound queue (the bot process sends it).

    Returns True if the message was enqueued. Non-bot sources, unlinked
    accounts, and publish failures all return False — this is a best-effort
    side channel, never raising into the caller's flow.
    """
    platform = ConversationSource.coerce(source)
    if platform is None or platform not in BOT_CONVERSATION_SOURCES:
        return False
    if not text.strip():
        return False
    return await publish_outbound_message(platform, user_id, [text])
