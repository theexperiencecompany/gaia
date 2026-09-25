"""Deliver a proactively-produced result into the user's linked messaging platforms.

A result GAIA produces with no user watching — a finished workflow run, a fired
reminder — is pushed by :func:deliver_result_to_platforms into the user's real
Telegram/WhatsApp/Discord/Slack chats as natural GAIA messages (GAIA's voice, no
notification chrome) so the thread can be continued there, AND recorded into that
conversation's langgraph thread so a later turn remembers it. This is deliberately
separate from the in-app badge each producer also raises: the badge is a web
heads-up, this is the actual conversational delivery, and they target different
surfaces.

Everything here is best-effort: a single platform failing never blocks the others
or propagates to the caller — the result is already persisted to the conversation.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.agents.core.background.comms_narrator import record_platform_delivery
from app.constants.log_tags import LogTag
from app.models.chat_models import (
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.delivery.chat_channel import ChatChannel, resolve_chat_channel
from app.services.outbound_delivery import (
    PLATFORM_DISPLAY_NAMES,
    OutboundResult,
    publish_outbound_message,
)
from app.utils.message_breaks import split_message_bubbles
from shared.py.wide_events import log


async def deliver_result_to_platforms(
    *,
    user: AuthenticatedUser,
    user_id: str,
    notification_text: str,
    origin: str,
    exclude_source: ConversationSource | None = None,
) -> ConversationSource | None:
    """Deliver a proactive result to the user's ONE preferred messaging platform.

    The platform is the first in their chat-channel order that is linked and
    enabled; exclude_source skips one that already received the result.
    Best-effort: returns the platform that got it, or None when nothing was sent.
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

    return await _post_workflow_message(
        user=user,
        user_id=user_id,
        channel=channel,
        response=notification_text,
        origin=origin,
    )


async def _post_workflow_message(
    *,
    user: AuthenticatedUser,
    user_id: str,
    channel: ChatChannel,
    response: str,
    origin: str,
) -> ConversationSource | None:
    """Persist the result into the platform's session conversation and deliver it.

    Sent as ordered bubbles, then recorded in that conversation's langgraph
    thread. Best-effort: logs and swallows a failure. Returns the platform that
    received the message, or None when it was skipped or failed.
    """
    source, platform_user_id = channel.source, channel.platform_user_id
    # Comms splits its reply into bubbles with the break sentinel; the outbound
    # publish and the provenance record below both need the split, not the raw
    # text with its control tokens.
    bubbles = split_message_bubbles(response)
    try:
        conversation_id = await BotService.get_or_create_session(
            platform=source.value,
            platform_user_id=platform_user_id,
            # No channel: this delivery goes to the user's DM, the only destination
            # publish_outbound_message can resolve from the platform link. See
            # BotService.build_session_key for how a DM keys.
            channel_id=None,
            user=user,
            is_dm=True,
        )
        bot_message = MessageModel(
            type="bot",
            response=response,
            date=datetime.now(UTC).isoformat(),
        )
        bot_message.message_id = str(uuid4())
        await update_messages(
            UpdateMessagesRequest(conversation_id=conversation_id, messages=[bot_message]),
            user=user,
        )
        # The channel already carries the account id; a second read of the user
        # document to recompute it is what destination_override exists to skip.
        result = await publish_outbound_message(
            source, user_id, bubbles, destination_override=platform_user_id
        )
        if result is OutboundResult.FAILED:
            log.error(
                f"{LogTag.AGENT} workflow platform publish failed",
                platform=source.value,
                conversation_id=conversation_id,
                message_id=bot_message.message_id,
                bubbles=len(bubbles),
            )
            return None
        if result is OutboundResult.PUBLISHED:
            # The Mongo save above never reaches the langgraph thread; record
            # the nonblank bubbles (outbound path strips sentinel/blanks)
            # rather than the raw response, which still has control tokens.
            delivered_text = "\n\n".join(b.strip() for b in bubbles if b.strip())
            display = PLATFORM_DISPLAY_NAMES.get(source, source.value.capitalize())
            await record_platform_delivery(
                conversation_id,
                f"[Delivered to the user on {display} (result of {origin})]: {delivered_text}",
            )
        log.info(
            f"{LogTag.AGENT} workflow result delivered to platform",
            platform=source.value,
            conversation_id=conversation_id,
            message_id=bot_message.message_id,
            bubbles=len(bubbles),
            result=result.value,
        )
        return source if result is OutboundResult.PUBLISHED else None
    except Exception as e:  # best-effort per platform
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=source.value,
            error=str(e),
        )
        return None
