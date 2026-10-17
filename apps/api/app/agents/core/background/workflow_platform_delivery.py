"""Deliver a proactively-produced result into the user's linked messaging platforms.

A result GAIA produces with no user watching — a finished workflow run, a fired
reminder — is pushed by deliver_result_to_platforms into the user's real
Telegram/WhatsApp/Discord/Slack chats as natural GAIA messages (GAIA's voice, no
notification chrome) so the thread can be continued there, AND recorded into that
conversation's langgraph thread so a later turn remembers it (both done by
post_to_platform_chat). This is deliberately separate from the in-app badge
each producer also raises: the badge is a web heads-up, this is the actual
conversational delivery, and they target different surfaces.

Everything here is best-effort: a single platform failing never blocks the others
or propagates to the caller — the result is already persisted to the conversation.
"""

from app.agents.core.background.platform_chat import post_to_platform_chat
from app.constants.log_tags import LogTag
from app.constants.notifications import ProactiveMessageClass
from app.models.chat_models import ConversationSource
from app.models.user_models import AuthenticatedUser
from app.services.delivery.chat_channel import resolve_chat_channel
from app.services.outbound_delivery import OutboundResult
from shared.py.wide_events import log


async def deliver_result_to_platforms(
    *,
    user: AuthenticatedUser,
    user_id: str,
    notification_text: str,
    origin: str,
    message_class: ProactiveMessageClass,
    exclude_source: ConversationSource | None = None,
) -> ConversationSource | None:
    """Deliver a proactive result to the user's ONE preferred messaging platform.

    The platform is the first in their chat-channel order that is linked and
    enabled; exclude_source skips one that already received the result.
    Best-effort: returns the platform that has it (posted, or scheduled for the
    end of the user's quiet hours), or None when nothing was sent.
    """
    if not notification_text.strip():
        return None

    try:
        channel = await resolve_chat_channel(user_id)
    except Exception as e:  # proactive side channel, never fatal
        log.error(f"{LogTag.AGENT} workflow platform delivery: channel lookup failed", error=str(e))
        return None
    if channel is None or channel.source == exclude_source:
        return None

    try:
        result = await post_to_platform_chat(
            user=user,
            channel=channel,
            text=notification_text,
            origin=f"result of {origin}",
            message_class=message_class,
        )
    except Exception as e:  # best-effort: the result is already in its own conversation
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=channel.source.value,
            error=str(e),
        )
        return None
    accepted = result in (OutboundResult.PUBLISHED, OutboundResult.DEFERRED)
    return channel.source if accepted else None
