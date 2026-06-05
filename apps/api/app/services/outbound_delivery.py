"""Publish backend-originated messages to the per-platform RabbitMQ queues that
the bot processes consume.

This replaces direct platform HTTP sends from Python: the backend resolves the
recipient's platform id, wraps the raw CommonMark text in an envelope, and
enqueues it. Each bot renders the platform-native markdown and sends. All
formatting and sending now live in the bots — there is no Python copy.
"""

from __future__ import annotations

from enum import StrEnum

from app.constants.outbound import OUTBOUND_QUEUES
from app.db.rabbitmq import RabbitMQPublisher, get_rabbitmq_publisher
from app.models.chat_models import ConversationSource
from app.schemas.outbound import OutboundAttachment, OutboundMessageEnvelope
from app.services.platform_link_service import PlatformLinkService
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
    """Resolve a GAIA ``user_id`` to its platform-native destination id, or None."""
    linked = await PlatformLinkService.get_linked_platforms(user_id)
    info = linked.get(platform.value)
    return info.get("platformUserId") if info else None


async def _prepare(
    platform: ConversationSource, user_id: str, log_label: str
) -> tuple[str, str, RabbitMQPublisher] | OutboundResult:
    """Resolve the queue, destination, and publisher shared by every outbound
    publish.

    Returns ``(queue_name, destination_id, publisher)`` on success, or the
    :class:`OutboundResult` to report when the message can't be enqueued
    (``SKIPPED`` for unsupported/unlinked, ``FAILED`` for an unavailable broker).
    """
    queue_name = OUTBOUND_QUEUES.get(platform)
    if queue_name is None:
        return OutboundResult.SKIPPED

    destination_id = await _resolve_destination(platform, user_id)
    if not destination_id:
        log.warning(f"{log_label}: account not linked", platform=platform.value)
        return OutboundResult.SKIPPED

    try:
        publisher = await get_rabbitmq_publisher()
    except RuntimeError:
        log.warning(f"{log_label}: RabbitMQ unavailable", platform=platform.value)
        return OutboundResult.FAILED

    return queue_name, str(destination_id), publisher


async def publish_outbound_message(
    platform: ConversationSource, user_id: str, text_parts: list[str]
) -> OutboundResult:
    """Resolve ``user_id`` to its ``platform`` id and enqueue the ordered text
    parts as a SINGLE envelope.

    The parts of one logical message (e.g. a workflow completion's header,
    result bubbles, and footer) are published together so the consumer delivers
    them in order. Publishing one envelope per part instead lets a concurrent
    consumer (prefetch > 1) reorder the bubbles — the bug this avoids.

    Returns ``PUBLISHED`` when the envelope was enqueued. ``SKIPPED`` when the
    platform is unsupported, the account is unlinked, or there is nothing to
    send. ``FAILED`` when the broker is unavailable or the publish errored.
    Best-effort: never raises into the caller's flow.
    """
    parts = [p for p in (s.strip() for s in text_parts) if p]
    if not parts:
        return OutboundResult.SKIPPED

    prep = await _prepare(platform, user_id, "publish_outbound_message")
    if isinstance(prep, OutboundResult):
        return prep
    queue_name, destination_id, publisher = prep

    # A single part is sent as a plain ``text`` envelope (the common executor-reply
    # case); multiple parts travel together in ``text_parts`` so ordering is the
    # consumer's responsibility within one message, not the broker's across many.
    if len(parts) == 1:
        envelope = OutboundMessageEnvelope(
            platform=platform.value, destination_id=destination_id, text=parts[0]
        )
    else:
        envelope = OutboundMessageEnvelope(
            platform=platform.value, destination_id=destination_id, text_parts=parts
        )

    try:
        await publisher.publish_outbound(queue_name, envelope.model_dump_json().encode())
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


async def publish_outbound_file(
    platform: ConversationSource,
    user_id: str,
    conversation_id: str,
    path: str,
    filename: str,
    content_type: str | None = None,
    caption: str | None = None,
) -> bool:
    """Enqueue a file (artifact) for the bot to deliver to ``user_id``.

    The bytes are not enqueued — the envelope references the artifact by
    ``(conversation_id, path)`` and the bot fetches + uploads it. Best-effort:
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
        await publisher.publish_outbound(queue_name, envelope.model_dump_json().encode())
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
