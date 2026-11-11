"""Alerts on outbound messages the broker dead-lettered before any bot handled them.

A durable copy queue is bound to the outbound DLX with every DLQ's routing key, so
RabbitMQ delivers each dead-lettered message to both: the DLQ keeps it for manual
replay, the tap reads the copy. A bot's own nack (x-death reason "rejected") was
already reported by that bot with its cause, so only the broker's reasons (expired,
maxlen, delivery_limit) are reported here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection
from pydantic import BaseModel, Field, ValidationError

from app.config.settings import settings
from app.constants.chat import ConversationSource
from app.constants.delivery_alerts import (
    DEAD_LETTER_REASON_REJECTED,
    DEAD_LETTER_TAP_CTX_KEY,
    DEAD_LETTER_TAP_PREFETCH,
    DEAD_LETTER_TAP_QUEUE,
    DEAD_LETTER_TAP_RECONNECT_MAX_SECONDS,
    DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS,
    DeliveryFailureKind,
)
from app.constants.outbound import (
    OUTBOUND_DLX,
    OUTBOUND_QUEUE_PREFIX,
    OUTBOUND_QUEUES,
    RABBITMQ_CONNECT_TIMEOUT_SECONDS,
    RABBITMQ_HEARTBEAT_SECONDS,
    dlq_name,
)
from app.schemas.delivery_failures import DeliveryFailure
from app.services.delivery_alerts.reporting import queue_delivery_failure
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log, log_context

_REPORTER = "dead-letter-tap"


@dataclass
class _TapConnection:
    """Filled in by the tap's task once it connects, so shutdown can close it."""

    connection: AbstractRobustConnection | None = None


@dataclass(frozen=True)
class _RunningTap:
    task: asyncio.Task[None]
    holder: _TapConnection


class _Death(BaseModel):
    """One entry of RabbitMQ's x-death header."""

    reason: str
    queue: str
    time: datetime | None = None


class _DeadLetterHeaders(BaseModel):
    """The headers RabbitMQ adds when it dead-letters a message."""

    deaths: list[_Death] = Field(alias="x-death", min_length=1)


class _EnvelopeRouting(BaseModel):
    """Who an outbound envelope was for; the rest of the envelope is not needed here."""

    id: str | None = None
    destination_id: str | None = None
    is_channel: bool = False


def dead_letter_failure(headers: Mapping[str, object], body: bytes) -> DeliveryFailure | None:
    """Describe a dead-lettered outbound message, or None when a bot already reported it.

    A message without an x-death header fails validation; one dead-lettered from a queue
    that is not an outbound work queue raises ValueError.
    """
    death = _DeadLetterHeaders.model_validate(dict(headers)).deaths[0]  # most recent first
    if death.reason == DEAD_LETTER_REASON_REJECTED:
        return None

    platform = ConversationSource.coerce(death.queue.removeprefix(OUTBOUND_QUEUE_PREFIX))
    if platform is None or OUTBOUND_QUEUES.get(platform) != death.queue:
        raise ValueError(f"dead-lettered from {death.queue!r}, which is not an outbound work queue")

    envelope = _envelope_routing(body)
    return DeliveryFailure(
        platform=platform,
        kind=DeliveryFailureKind.EXPIRED,
        reason=death.reason,
        destination_id=envelope.destination_id,
        is_channel=envelope.is_channel,
        envelope_id=envelope.id,
        occurred_at=death.time.astimezone(UTC) if death.time else datetime.now(UTC),
        reporter=_REPORTER,
    )


def _envelope_routing(body: bytes) -> _EnvelopeRouting:
    """Read who the envelope was for; an unreadable body still alerts, just without it."""
    try:
        return _EnvelopeRouting.model_validate_json(body)
    except ValidationError:
        return _EnvelopeRouting()


async def _handle(message: AbstractIncomingMessage) -> None:
    async with log_context("dead_letter_tap", component="delivery_alerts"):
        try:
            failure = dead_letter_failure(message.headers, message.body)
        except (ValidationError, ValueError) as e:
            # Unreadable metadata never becomes readable: requeueing would spin on it.
            # The original stays in its DLQ, so dropping this copy loses only the alert.
            log.error(
                "dead-lettered message could not be read",
                routing_key=message.routing_key,
                error=str(e),
                error_type=type(e).__name__,
            )
            await message.reject(requeue=False)
            return
        if failure is None:
            await message.ack()
            return
        log.set(delivery_failure={"platform": failure.platform.value, "reason": failure.reason})
        try:
            await queue_delivery_failure(failure)
        except Exception as e:
            # Redis down is transient: keep the copy and retry after a pause, rather
            # than spinning on it or losing the alert.
            log.warning(
                "dead-letter alert could not be queued, requeueing",
                routing_key=message.routing_key,
                wait_s=DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS,
                error=str(e),
                error_type=type(e).__name__,
            )
            await asyncio.sleep(DEAD_LETTER_TAP_REQUEUE_DELAY_SECONDS)
            await message.nack(requeue=True)
            return
        await message.ack()


async def _consume(connection: AbstractRobustConnection) -> None:
    """Declare the tap queue, bind it to every DLQ's routing key, and start consuming."""
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=DEAD_LETTER_TAP_PREFETCH)
    dlx = await channel.declare_exchange(OUTBOUND_DLX, aio_pika.ExchangeType.DIRECT, durable=True)
    queue = await channel.declare_queue(DEAD_LETTER_TAP_QUEUE, durable=True)
    for work_queue in OUTBOUND_QUEUES.values():
        await queue.bind(dlx, routing_key=dlq_name(work_queue))
    await queue.consume(_handle)


async def _run(holder: _TapConnection) -> None:
    # connect_robust only restores a connection whose setup once succeeded, so the
    # first connect AND the setup on it are retried here until both go through.
    delay = 1.0
    while True:
        connection: AbstractRobustConnection | None = None
        try:
            connection = await aio_pika.connect_robust(
                settings.RABBITMQ_URL,
                timeout=RABBITMQ_CONNECT_TIMEOUT_SECONDS,
                heartbeat=RABBITMQ_HEARTBEAT_SECONDS,
            )
            holder.connection = connection
            await _consume(connection)
        except Exception as e:
            log.warning(
                "dead-letter tap could not start, retrying",
                wait_s=delay,
                error=str(e),
                error_type=type(e).__name__,
            )
            holder.connection = None
            if connection is not None:
                await connection.close()
            await asyncio.sleep(delay)
            delay = min(delay * 2, DEAD_LETTER_TAP_RECONNECT_MAX_SECONDS)
            continue
        log.info("dead-letter tap consuming", queue=DEAD_LETTER_TAP_QUEUE)
        return


def start_dead_letter_tap(ctx: MutableMapping[str, object]) -> None:
    """Start alerting on broker dead-letters in the background; a no-op without RabbitMQ."""
    if not settings.RABBITMQ_URL:
        log.warning("dead-letter tap not started: RABBITMQ_URL is not configured")
        return
    holder = _TapConnection()
    task = spawn_background_task(_run(holder), name="dead_letter_tap")
    ctx[DEAD_LETTER_TAP_CTX_KEY] = _RunningTap(task=task, holder=holder)


async def stop_dead_letter_tap(ctx: MutableMapping[str, object]) -> None:
    """Stop connecting (if still trying) and close the tap's connection."""
    running = ctx.pop(DEAD_LETTER_TAP_CTX_KEY, None)
    if not isinstance(running, _RunningTap):
        return
    running.task.cancel()
    await asyncio.wait({running.task})
    if running.holder.connection is not None:
        await running.holder.connection.close()
