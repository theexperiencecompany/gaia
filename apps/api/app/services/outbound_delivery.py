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
    """Resolve ``user_id`` to its ``platform`` id and enqueue one envelope per
    non-empty text part.

    Returns ``PUBLISHED`` only if every part was published. ``SKIPPED`` when the
    platform is unsupported, the account is unlinked, or there is nothing to
    send. ``FAILED`` when the broker is unavailable or a publish errored (a
    partial send is also ``FAILED`` so the orchestrator never records a
    half-delivered notification as delivered). Best-effort: never raises into
    the caller's flow.
    """
    parts = [p for p in (s.strip() for s in text_parts) if p]
    if not parts:
        return OutboundResult.SKIPPED

    prep = await _prepare(platform, user_id, "publish_outbound_message")
    if isinstance(prep, OutboundResult):
        return prep
    queue_name, destination_id, publisher = prep

    published = 0
    for part in parts:
        envelope = OutboundMessageEnvelope(
            platform=platform.value,
            destination_id=destination_id,
            text=part,
        )
        try:
            await publisher.publish_outbound(queue_name, envelope.model_dump_json().encode())
            published += 1
        except Exception as e:
            # Stop on the first failure: a downed broker will reject the rest
            # too. Already-published parts can't be unsent, but the caller does
            # NOT retry on a failure result (the notification orchestrator
            # records the status once and never re-enqueues), so reporting
            # failure can't duplicate them — it just keeps a partial send from
            # being recorded as a fully delivered notification.
            log.error(
                "publish_outbound_message: publish failed",
                platform=platform.value,
                error=str(e),
                published=published,
                total=len(parts),
            )
            break

    if published:
        log.info(
            "outbound_message_published",
            platform=platform.value,
            queue=queue_name,
            parts=published,
            total=len(parts),
        )
    return OutboundResult.PUBLISHED if published == len(parts) else OutboundResult.FAILED


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
