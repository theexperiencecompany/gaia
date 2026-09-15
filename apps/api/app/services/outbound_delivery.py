"""Publish backend-originated messages to the per-platform RabbitMQ queues the bot processes consume.

This replaces direct platform HTTP sends from Python: the backend resolves the
recipient's platform id, wraps the raw CommonMark text in an envelope, and
enqueues it. Each bot renders the platform-native markdown and sends. All
formatting and sending now live in the bots — there is no Python copy.
"""

from __future__ import annotations

from enum import StrEnum

from app.constants.outbound import (
    OUTBOUND_QUEUES,
    OUTBOUND_TTL_SECONDS_DEFAULT,
    OUTBOUND_TTL_SECONDS_GREETING,
)
from app.db.rabbitmq import RabbitMQPublisher, get_rabbitmq_publisher
from app.models.chat_models import ConversationSource
from app.schemas.outbound import OutboundAttachment, OutboundMessageEnvelope
from app.services.platform_link_service import PlatformLinkService
from app.utils.message_breaks import split_message_bubbles
from shared.py.wide_events import log


class OutboundResult(StrEnum):
    """Outcome of an outbound publish.

    Distinguishes a genuine *skip* (unsupported platform, unlinked account,
    nothing to send) from a real *failure* (broker unavailable, publish error)
    so callers can record the correct delivery status — a broker outage must
    not be recorded as "skipped".
    """

    PUBLISHED = "published"
    SKIPPED = "skipped"
    FAILED = "failed"


async def _resolve_destination(platform: ConversationSource, user_id: str) -> str | None:
    """Resolve a GAIA user_id to its platform-native destination id, or None."""
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    info = linked.get(platform.value)
    return info["platformUserId"] if info else None


async def _prepare(
    platform: ConversationSource,
    user_id: str,
    log_label: str,
    destination_override: str | None = None,
) -> tuple[str, str, RabbitMQPublisher] | OutboundResult:
    """Resolve the queue, destination, and publisher shared by every outbound publish.

    destination_override sends to an explicit platform-native id (a group's
    channel) instead of resolving the user's DM — for a proactive message back
    into the group it came from. Returns (queue_name, destination_id, publisher)
    on success, or an OutboundResult (SKIPPED/FAILED) otherwise.
    """
    queue_name = OUTBOUND_QUEUES.get(platform)
    if queue_name is None:
        return OutboundResult.SKIPPED

    destination_id = destination_override or await _resolve_destination(platform, user_id)
    if not destination_id:
        log.warning(
            ": account not linked", log_label=log_label, user_id=user_id, platform=platform.value
        )
        return OutboundResult.SKIPPED

    try:
        publisher = await get_rabbitmq_publisher()
    except RuntimeError:
        log.warning(
            ": RabbitMQ unavailable", log_label=log_label, user_id=user_id, platform=platform.value
        )
        return OutboundResult.FAILED

    return queue_name, str(destination_id), publisher


async def publish_outbound_message(
    platform: ConversationSource,
    user_id: str,
    text_parts: list[str],
    *,
    destination_override: str | None = None,
    is_channel: bool = False,
    ttl_seconds: int = OUTBOUND_TTL_SECONDS_DEFAULT,
) -> OutboundResult:
    """Enqueue text_parts as a single ordered envelope for user_id on platform.

    One envelope (not one-per-part) stops a concurrent consumer reordering
    bubbles; each part also splits on the bubble-break sentinel, so raw text
    with <NEW_MESSAGE_BREAK> delivers as separate bubbles. destination_override
    + is_channel target a channel/group instead of the DM; ttl_seconds caps the wait before dead-lettering.
    """
    parts = [bubble for part in text_parts for bubble in split_message_bubbles(part)]
    if not parts:
        return OutboundResult.SKIPPED

    prep = await _prepare(platform, user_id, "publish_outbound_message", destination_override)
    if isinstance(prep, OutboundResult):
        return prep
    queue_name, destination_id, publisher = prep

    # A single part is sent as a plain ``text`` envelope (the common executor-reply
    # case); multiple parts travel together in ``text_parts`` so ordering is the
    # consumer's responsibility within one message, not the broker's across many.
    if len(parts) == 1:
        envelope = OutboundMessageEnvelope(
            platform=platform.value,
            destination_id=destination_id,
            text=parts[0],
            is_channel=is_channel,
        )
    else:
        envelope = OutboundMessageEnvelope(
            platform=platform.value,
            destination_id=destination_id,
            text_parts=parts,
            is_channel=is_channel,
        )

    try:
        await publisher.publish_outbound(
            queue_name, envelope.model_dump_json().encode(), expiration=ttl_seconds
        )
    except Exception as e:
        log.error(
            "publish_outbound_message: publish failed",
            platform=platform.value,
            error=str(e),
            total=len(parts),
        )
        return OutboundResult.FAILED

    log.info(
        "outbound_message_published",
        platform=platform.value,
        queue=queue_name,
        parts=len(parts),
    )
    return OutboundResult.PUBLISHED


# Friendly platform names for user-facing copy (e.g. the link confirmation,
# delivery provenance frames). Single source — import, don't restate.
PLATFORM_DISPLAY_NAMES: dict[ConversationSource, str] = {
    ConversationSource.TELEGRAM: "Telegram",
    ConversationSource.DISCORD: "Discord",
    ConversationSource.SLACK: "Slack",
    ConversationSource.WHATSAPP: "WhatsApp",
    ConversationSource.IMESSAGE: "iMessage",
}


async def notify_account_linked(platform: str, user_id: str) -> OutboundResult:
    """Send a one-off "you're connected" confirmation to a freshly linked bot account.

    Resolves the bot platform, builds the confirmation copy as CommonMark (each
    bot renders its own platform-native markdown), and enqueues it. Non-bot
    sources (web OAuth links, etc.) and unsupported/unlinked platforms are
    skipped. Best-effort: never raises into the caller's linking flow.
    """
    source = ConversationSource.coerce(platform)
    if source is None or source not in OUTBOUND_QUEUES:
        return OutboundResult.SKIPPED

    display_name = PLATFORM_DISPLAY_NAMES.get(source, source.value.capitalize())
    text = (
        "✅ **You're connected!**\n\n"
        f"Your {display_name} account is now linked to GAIA. "
        "Send me a message or use `/help` to see everything I can do."
    )
    return await publish_outbound_message(
        source, user_id, [text], ttl_seconds=OUTBOUND_TTL_SECONDS_GREETING
    )


async def publish_outbound_file(
    platform: ConversationSource,
    user_id: str,
    conversation_id: str,
    path: str,
    filename: str,
    content_type: str | None = None,
    caption: str | None = None,
) -> bool:
    """Enqueue a file (artifact) for the bot to deliver to user_id.

    The bytes are not enqueued — the envelope references the artifact by
    (conversation_id, path) and the bot fetches + uploads it. Best-effort:
    unknown platform, unlinked account, unavailable broker, and publish errors
    all return False without raising.
    """
    prep = await _prepare(platform, user_id, "publish_outbound_file")
    if isinstance(prep, OutboundResult):
        return False
    queue_name, destination_id, publisher = prep

    envelope = OutboundMessageEnvelope(
        platform=platform.value,
        destination_id=destination_id,
        attachment=OutboundAttachment(
            conversation_id=conversation_id,
            path=path,
            filename=filename,
            content_type=content_type,
            caption=caption,
        ),
    )
    try:
        await publisher.publish_outbound(
            queue_name, envelope.model_dump_json().encode(), expiration=OUTBOUND_TTL_SECONDS_DEFAULT
        )
    except Exception as e:
        log.error("publish_outbound_file: publish failed", platform=platform.value, error=str(e))
        return False

    log.info(
        "outbound_file_published",
        platform=platform.value,
        queue=queue_name,
        filename=filename,
    )
    return True
