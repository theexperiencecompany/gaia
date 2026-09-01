"""Deliver a proactively-produced result into the user's linked messaging platforms.

A result GAIA produces with no user watching — a finished workflow run, a fired
reminder — is pushed by :func:`deliver_result_to_platforms` into the user's real
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
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.models.user_models import AuthenticatedUser
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.outbound_delivery import (
    PLATFORM_DISPLAY_NAMES,
    OutboundResult,
    publish_outbound_message,
)
from app.services.platform_link_service import PlatformLinkService
from app.utils.message_breaks import split_message_bubbles
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log


async def deliver_result_to_platforms(
    *,
    user: AuthenticatedUser,
    user_id: str,
    notification_text: str,
    origin: str,
    exclude_source: ConversationSource | None = None,
) -> None:
    """Deliver a proactive result into the user's preferred messaging platforms as
    real, persisted bot messages, split into natural bubbles, and record each into
    the platform conversation's langgraph thread.

    Only platforms the user has linked AND left enabled in their notification
    channel preferences receive it. ``origin`` names what produced the result
    (workflow, reminder, …) so the langgraph record can backtrack to the source.
    ``exclude_source`` drops one platform from the fan-out — used when the result
    was already delivered into that platform's conversation directly, so the user
    isn't pinged twice on it. Best-effort: a single platform failing never blocks
    the others or propagates to the caller.
    """
    if not notification_text.strip():
        return

    targets = await _preferred_bot_platforms(user_id)
    if exclude_source is not None:
        targets = [t for t in targets if t[0] != exclude_source]
    if not targets:
        return

    for target in targets:
        await _post_workflow_message(
            user=user,
            user_id=user_id,
            target=target,
            response=notification_text,
            origin=origin,
        )


async def _preferred_bot_platforms(user_id: str) -> list[tuple[ConversationSource, str]]:
    """Resolve which messaging platforms a workflow result should reach: those the
    user has linked AND left enabled in their notification channel preferences."""
    try:
        linked = await PlatformLinkService.get_linked_platforms(user_id)
        prefs = await fetch_channel_preferences(user_id)
    except Exception as e:  # proactive side channel, never fatal
        log.error(f"{LogTag.AGENT} workflow platform delivery: target lookup failed", error=str(e))
        return []

    # Keep only linked platforms that are a known bot source, left enabled in the
    # user's notification preferences (default on), and carry a platform user id.
    # ``source in BOT_CONVERSATION_SOURCES`` is also False when coercion returns None.
    targets: list[tuple[ConversationSource, str]] = []
    for platform_value, info in linked.items():
        source = ConversationSource.coerce(platform_value)
        platform_user_id = info["platformUserId"]
        if (
            source is not None
            and source in BOT_CONVERSATION_SOURCES
            and prefs.get(platform_value, True)
            and platform_user_id
        ):
            targets.append((source, str(platform_user_id)))
    return targets


async def _post_workflow_message(
    *,
    user: AuthenticatedUser,
    user_id: str,
    target: tuple[ConversationSource, str],
    response: str,
    origin: str,
) -> None:
    """Persist the result into the platform's session conversation and deliver it
    as ordered bubbles, then record it in that conversation's langgraph thread —
    framed with the platform and origin so a later turn can backtrack to the
    source. Best-effort: logs and swallows any single-platform failure."""
    source, platform_user_id = target
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
        result = await publish_outbound_message(source, user_id, bubbles)
        if result is OutboundResult.FAILED:
            log.error(
                f"{LogTag.AGENT} workflow platform publish failed",
                platform=source.value,
                conversation_id=conversation_id,
                message_id=bot_message.message_id,
                bubbles=len(bubbles),
            )
            return
        if result is OutboundResult.PUBLISHED:
            # The Mongo save above never reaches the langgraph thread this
            # session's next turn reads its history from. Record what was
            # actually delivered — the outbound path strips the sentinel and
            # blank bubbles, so join the nonblank bubbles rather than the raw
            # response (which still contains control tokens).
            delivered_text = "\n\n".join(b.strip() for b in bubbles if b.strip())
            display = PLATFORM_DISPLAY_NAMES.get(source, source.value.capitalize())
            await record_platform_delivery(
                conversation_id,
                f"[Delivered to the user on {display} — result of {origin}]: {delivered_text}",
            )
        log.info(
            f"{LogTag.AGENT} workflow result delivered to platform",
            platform=source.value,
            conversation_id=conversation_id,
            message_id=bot_message.message_id,
            bubbles=len(bubbles),
            result=result.value,
        )
    except Exception as e:  # best-effort per platform
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=source.value,
            error=str(e),
        )
