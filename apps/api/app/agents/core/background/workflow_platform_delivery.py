"""Deliver a finished workflow's result into the user's linked messaging platforms.

When a workflow run completes, ``deliver_result`` saves the bot message and then
(for non-silent, successful runs) calls :func:`deliver_workflow_result_to_platforms`
to push that same result into the user's real Telegram/WhatsApp/Discord/Slack chats
as natural GAIA messages — GAIA's voice, no notification chrome — so the thread can
be continued there. This is deliberately separate from the in-app completion badge
(``app.services.workflow.notifications``): the badge is a web heads-up, this is the
actual conversational delivery, and they target different surfaces.

Everything here is best-effort: a single platform failing never blocks the others
or propagates to the caller — the result is already persisted to the conversation.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.constants.general import NEW_MESSAGE_BREAKER
from app.constants.log_tags import LogTag
from app.models.chat_models import (
    BOT_CONVERSATION_SOURCES,
    ConversationSource,
    MessageModel,
    UpdateMessagesRequest,
)
from app.services.bot_service import BotService
from app.services.conversation_service import update_messages
from app.services.outbound_delivery import OutboundResult, publish_outbound_message
from app.services.platform_link_service import PlatformLinkService
from app.utils.notification.channel_preferences import fetch_channel_preferences
from shared.py.wide_events import log


async def deliver_workflow_result_to_platforms(
    *,
    user: dict,
    user_id: str,
    notification_text: str,
) -> None:
    """Deliver a finished workflow's result into the user's preferred messaging
    platforms as real, persisted bot messages, split into natural bubbles.

    Only platforms the user has linked AND left enabled in their notification
    channel preferences receive it. This is what makes a workflow result appear
    inline in the user's actual Telegram/WhatsApp/etc. chat (GAIA's voice, no
    notification chrome) so the thread can be continued there, alongside the
    workflow's own conversation. Best-effort: a single platform failing never
    blocks the others or propagates to the caller.
    """
    if not notification_text.strip():
        return

    targets = await _preferred_bot_platforms(user_id)
    if not targets:
        return

    # Comms splits its reply into bubbles with the break sentinel;
    # publish_outbound_message strips blanks and sends them as one ordered message.
    bubbles = notification_text.split(NEW_MESSAGE_BREAKER)
    for source, platform_user_id in targets:
        await _post_workflow_message(
            user=user,
            user_id=user_id,
            source=source,
            platform_user_id=platform_user_id,
            response=notification_text,
            bubbles=bubbles,
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
        platform_user_id = info.get("platformUserId")
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
    user: dict,
    user_id: str,
    source: ConversationSource,
    platform_user_id: str,
    response: str,
    bubbles: list[str],
) -> None:
    """Persist the result into the platform's session conversation and deliver it
    as ordered bubbles. Best-effort: logs and swallows any single-platform failure."""
    try:
        conversation_id = await BotService.get_or_create_session(
            platform=source.value,
            platform_user_id=platform_user_id,
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
                bubbles=len([b for b in bubbles if b.strip()]),
            )
            return
        log.info(
            f"{LogTag.AGENT} workflow result delivered to platform",
            platform=source.value,
            conversation_id=conversation_id,
            message_id=bot_message.message_id,
            bubbles=len([b for b in bubbles if b.strip()]),
            result=result.value,
        )
    except Exception as e:  # best-effort per platform
        log.error(
            f"{LogTag.AGENT} workflow platform delivery failed",
            platform=source.value,
            error=str(e),
        )
