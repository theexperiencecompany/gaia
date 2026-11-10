"""Consumes the delivery receipts the bots publish and files them in the receipts store."""

import asyncio
from collections.abc import MutableMapping

from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from pydantic import ValidationError

from app.constants.outbound import (
    OUTBOUND_RECEIPTS_CTX_KEY,
    OUTBOUND_RECEIPTS_PREFETCH,
    OUTBOUND_RECEIPTS_QUEUE,
    OUTBOUND_RECEIPTS_RECONNECT_MAX_SECONDS,
    OUTBOUND_RECEIPTS_REQUEUE_DELAY_SECONDS,
)
from app.db.repositories.outbound_receipts import outbound_receipts_repository
from app.schemas.outbound import OutboundReceipt
from app.services.rabbitmq_consumer import start_consumer, stop_consumer
from shared.py.wide_events import log, log_context


async def handle_receipt(message: AbstractIncomingMessage) -> None:
    """File one receipt; a redelivery is acked, an unreadable one dropped, a store outage retried."""
    async with log_context("outbound_receipt", component="outbox"):
        try:
            receipt = OutboundReceipt.model_validate_json(message.body)
        except ValidationError as e:
            # A malformed receipt never becomes readable, so requeueing would only spin on it.
            log.error(
                "outbound receipt could not be read",
                routing_key=message.routing_key,
                error=str(e),
                error_type=type(e).__name__,
            )
            await message.reject(requeue=False)
            return
        log.set(
            receipt={
                "platform": receipt.platform.value,
                "status": receipt.status.value,
                "part_index": receipt.part_index,
            }
        )
        try:
            filed = await outbound_receipts_repository.record(receipt)
        except Exception as e:
            log.warning(
                "outbound receipt could not be filed, requeueing",
                wait_s=OUTBOUND_RECEIPTS_REQUEUE_DELAY_SECONDS,
                error=str(e),
                error_type=type(e).__name__,
            )
            await asyncio.sleep(OUTBOUND_RECEIPTS_REQUEUE_DELAY_SECONDS)
            await message.nack(requeue=True)
            return
        log.set(receipt_duplicate=not filed)
        await message.ack()


async def _consume(connection: AbstractRobustConnection) -> None:
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=OUTBOUND_RECEIPTS_PREFETCH)
    queue = await channel.declare_queue(OUTBOUND_RECEIPTS_QUEUE, durable=True)
    await queue.consume(handle_receipt)


def start_receipt_consumer(ctx: MutableMapping[str, object]) -> None:
    """Start filing bot receipts in the background; a no-op without RabbitMQ."""
    start_consumer(
        ctx,
        OUTBOUND_RECEIPTS_CTX_KEY,
        _consume,
        name="outbound_receipt_consumer",
        queue=OUTBOUND_RECEIPTS_QUEUE,
        reconnect_max_seconds=OUTBOUND_RECEIPTS_RECONNECT_MAX_SECONDS,
    )


async def stop_receipt_consumer(ctx: MutableMapping[str, object]) -> None:
    """Stop connecting (if still trying) and close the consumer's connection."""
    await stop_consumer(ctx, OUTBOUND_RECEIPTS_CTX_KEY)
