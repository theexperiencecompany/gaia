"""Publish backend-originated messages to the per-platform RabbitMQ queues the bot processes consume.

This replaces direct platform HTTP sends from Python: the backend resolves the
recipient's platform id, wraps the raw CommonMark text in an envelope, and
enqueues it. Each bot renders the platform-native markdown and sends. All
formatting and sending now live in the bots — there is no Python copy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from app.constants.delivery_alerts import DeliveryFailureKind
from app.constants.outbound import (
    OUTBOUND_QUEUES,
    OUTBOUND_TTL_SECONDS_DEFAULT,
    OUTBOUND_TTL_SECONDS_GREETING,
)
from app.db.rabbitmq import RabbitMQPublisher, get_rabbitmq_publisher
from app.models.bot_models import BotSessionDocument
from app.models.chat_models import ConversationSource
from app.models.conversation_send_models import ActiveBotConversation
from app.models.platform_models import PlatformLinkEntry
from app.schemas.delivery_failures import DeliveryFailure
from app.schemas.outbound import OutboundMessageEnvelope
from app.services.delivery_alerts.reporting import report_delivery_failure
from app.services.platform_link_service import PlatformLinkService
from app.utils.log_identifiers import hash_platform_user_id
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


def _envelope_fields(
    envelope: OutboundMessageEnvelope, user_id: str | None
) -> dict[str, str | None]:
    """Who and where an outbound log line is about; envelope_id joins the bot's line."""
    return {
        "platform": envelope.platform,
        "user_id": user_id,
        "envelope_id": envelope.id,
        "destination_hash": hash_platform_user_id(envelope.destination_id),
    }


#: The reporter name every API-side delivery failure carries.
_REPORTER = "api"

#: Why a message never reached its bot's queue.
EnqueueFailureReason = Literal["broker_unavailable", "publish_failed"]


async def _report_enqueue_failure(
    platform: ConversationSource,
    user_id: str | None,
    reason: EnqueueFailureReason,
    error: Exception,
    *,
    destination_id: str | None,
    is_channel: bool = False,
    envelope_id: str | None = None,
) -> None:
    """Alert on a message the API could not hand to its bot's queue.

    Only the exception's type travels: broker errors can carry the connection URL.
    """
    await report_delivery_failure(
        DeliveryFailure(
            platform=platform,
            kind=DeliveryFailureKind.ENQUEUE_FAILED,
            reason=reason,
            error_message=type(error).__name__,
            destination_id=destination_id,
            is_channel=is_channel,
            envelope_id=envelope_id,
            user_id=user_id,
            reporter=_REPORTER,
        )
    )


async def _resolve_destination(platform: ConversationSource, user_id: str) -> str | None:
    """Resolve a GAIA user_id to its platform-native destination id, or None."""
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    info: PlatformLinkEntry | None = linked.get(platform.value)
    return info["platformUserId"] if info else None


async def _prepare(
    platform: ConversationSource,
    user_id: str,
    log_label: str,
    destination_override: str | None = None,
    *,
    is_channel: bool = False,
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
            "outbound publish skipped: account not linked",
            operation=log_label,
            user_id=user_id,
            platform=platform.value,
        )
        return OutboundResult.SKIPPED

    try:
        publisher = await get_rabbitmq_publisher()
    except RuntimeError as e:
        log.warning(
            "outbound publish failed: RabbitMQ unavailable",
            operation=log_label,
            user_id=user_id,
            platform=platform.value,
            error=str(e),
            error_type=type(e).__name__,
        )
        await _report_enqueue_failure(
            platform,
            user_id,
            "broker_unavailable",
            e,
            destination_id=str(destination_id),
            is_channel=is_channel,
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
    notification_id: str | None = None,
) -> OutboundResult:
    """Enqueue text_parts as a single ordered envelope for user_id on platform.

    One envelope stops a concurrent consumer reordering bubbles; each part is split into its
    bubbles here, and the bot sends each as one message. destination_override + is_channel target a channel
    instead of the DM; ttl_seconds caps the wait before dead-lettering. Returns PUBLISHED,
    SKIPPED (unsupported/unlinked/empty) or FAILED; never raises into the caller.
    """
    parts = [bubble for part in text_parts for bubble in split_message_bubbles(part)]
    if not parts:
        return OutboundResult.SKIPPED

    prep = await _prepare(
        platform, user_id, "publish_outbound_message", destination_override, is_channel=is_channel
    )
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
            notification_id=notification_id,
        )
    else:
        envelope = OutboundMessageEnvelope(
            platform=platform.value,
            destination_id=destination_id,
            text_parts=parts,
            is_channel=is_channel,
            notification_id=notification_id,
        )

    try:
        await publisher.publish_outbound(
            queue_name, envelope.model_dump_json().encode(), expiration=ttl_seconds
        )
    except Exception as e:
        log.error(
            "publish_outbound_message: publish failed",
            **_envelope_fields(envelope, user_id),
            error=str(e),
            error_type=type(e).__name__,
            total=len(parts),
        )
        await _report_enqueue_failure(
            platform,
            user_id,
            "publish_failed",
            e,
            destination_id=destination_id,
            is_channel=is_channel,
            envelope_id=envelope.id,
        )
        return OutboundResult.FAILED

    log.info(
        "outbound_message_published",
        **_envelope_fields(envelope, user_id),
        queue=queue_name,
        parts=len(parts),
    )
    return OutboundResult.PUBLISHED


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

    display_name = source.display_name
    text = (
        "✅ **You're connected**\n\n"
        f"Your {display_name} account is linked. "
        "Message me anytime, or send `/help` to see what I can do."
    )
    return await publish_outbound_message(
        source, user_id, [text], ttl_seconds=OUTBOUND_TTL_SECONDS_GREETING
    )


async def publish_conversation_wake(session: BotSessionDocument) -> OutboundResult:
    """Tell the session's bot to follow its conversation from its delivered-through cursor.

    The wake carries no content: the bot reads the entries off the conversation's events stream.
    """
    if session.delivery is None:
        raise ValueError("a wake follows the session's delivery cursor, and it has none")
    platform = ConversationSource.coerce(session.platform)
    queue_name = OUTBOUND_QUEUES.get(platform) if platform is not None else None
    if platform is None or queue_name is None:
        return OutboundResult.SKIPPED
    is_channel = session.channel_id is not None
    follow = ActiveBotConversation.of(session, session.delivery)
    envelope = OutboundMessageEnvelope(
        platform=platform.value,
        destination_id=session.channel_id or session.platform_user_id,
        is_channel=is_channel,
        follow=follow,
    )
    try:
        publisher = await get_rabbitmq_publisher()
        await publisher.publish_outbound(
            queue_name, envelope.model_dump_json().encode(), expiration=OUTBOUND_TTL_SECONDS_DEFAULT
        )
    except Exception as e:  # the entry is logged and on web either way; the bot just was not told
        log.error(
            "conversation wake publish failed",
            **_envelope_fields(envelope, None),
            conversation_id=session.conversation_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        await _report_enqueue_failure(
            platform,
            None,
            "publish_failed",
            e,
            destination_id=envelope.destination_id,
            is_channel=is_channel,
            envelope_id=envelope.id,
        )
        return OutboundResult.FAILED
    log.info(
        "conversation_wake_published",
        **_envelope_fields(envelope, None),
        conversation_id=session.conversation_id,
        after_seq=follow.after_seq,
    )
    return OutboundResult.PUBLISHED
