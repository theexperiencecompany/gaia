"""Publish backend-originated messages to the per-platform RabbitMQ queues that
the bot processes consume.

This replaces direct platform HTTP sends from Python: the backend resolves the
recipient's platform id, wraps the raw CommonMark text in an envelope, and
enqueues it. Each bot renders the platform-native markdown and sends. All
formatting and sending now live in the bots — there is no Python copy.
"""

from __future__ import annotations

from app.constants.outbound import OUTBOUND_QUEUES
from app.db.rabbitmq import get_rabbitmq_publisher
from app.models.chat_models import ConversationSource
from app.schemas.outbound import OutboundMessageEnvelope
from app.services.platform_link_service import PlatformLinkService
from shared.py.wide_events import log


async def publish_outbound_message(
    platform: ConversationSource, user_id: str, text_parts: list[str]
) -> bool:
    """Resolve ``user_id`` to its ``platform`` id and enqueue one envelope per
    non-empty text part.

    Returns True only if every part was published. A partial send returns
    False so the orchestrator does not record a half-delivered notification as
    DELIVERED. Best-effort: unknown platforms, unlinked accounts, an unavailable
    broker, and publish errors all return False and never raise into the
    caller's flow.
    """
    queue_name = OUTBOUND_QUEUES.get(platform)
    if queue_name is None:
        return False

    parts = [p for p in (s.strip() for s in text_parts) if p]
    if not parts:
        return False

    linked = await PlatformLinkService.get_linked_platforms(user_id)
    info = linked.get(platform.value)
    destination_id = info.get("platformUserId") if info else None
    if not destination_id:
        log.warning("publish_outbound_message: account not linked", platform=platform.value)
        return False

    try:
        publisher = await get_rabbitmq_publisher()
    except RuntimeError:
        log.warning("publish_outbound_message: RabbitMQ unavailable", platform=platform.value)
        return False

    published = 0
    for part in parts:
        envelope = OutboundMessageEnvelope(
            platform=platform.value,
            destination_id=str(destination_id),
            text=part,
        )
        try:
            await publisher.publish_outbound(queue_name, envelope.model_dump_json().encode())
            published += 1
        except Exception as e:
            # Stop on the first failure: a downed broker will reject the rest
            # too. Already-published parts can't be unsent, but the caller does
            # NOT retry on a False result (the notification orchestrator records
            # the status once and never re-enqueues), so reporting failure can't
            # duplicate them — it just keeps a partial send from being recorded
            # as a fully delivered notification (see the `== len(parts)` return).
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
    return published == len(parts)
