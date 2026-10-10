"""Constants for the RabbitMQ outbound-message delivery pipeline.

Backend-originated messages for the messaging-platform bots (WhatsApp, Slack,
Telegram, Discord) are published to these per-platform queues; the bot
processes consume them, render the platform-native markdown, and send.

These queue names and dead-letter arguments are the single source of truth and
MUST stay byte-identical to libs/shared/ts/src/bots/consumer/topology.ts —
RabbitMQ rejects a redeclare whose arguments differ from the existing queue.
"""

from __future__ import annotations

from typing import Any

from app.constants.chat import BOT_CONVERSATION_SOURCES, ConversationSource

# Dead-letter exchange every outbound work queue routes failed messages to.
OUTBOUND_DLX = "outbound.dlx"

#: Per-message expiry on the outbound work queues (seconds): a bot back after
#: hours must not fire every stale ping — expired messages dead-letter instead.
OUTBOUND_TTL_SECONDS_DEFAULT = 24 * 60 * 60
OUTBOUND_TTL_SECONDS_GREETING = 60 * 60

# Per-platform durable work queues, derived from BOT_CONVERSATION_SOURCES so the
# queue set can never drift from it. The ``outbound.<source>`` names MUST stay
# byte-identical to ``libs/shared/ts/src/bots/consumer/topology.ts``.
OUTBOUND_QUEUE_PREFIX = "outbound."
OUTBOUND_QUEUES: dict[ConversationSource, str] = {
    src: f"{OUTBOUND_QUEUE_PREFIX}{src.value}" for src in BOT_CONVERSATION_SOURCES
}


def dlq_name(queue_name: str) -> str:
    """Dead-letter queue name for a given work queue."""
    return f"{queue_name}.dlq"


def work_queue_arguments(queue_name: str) -> dict[str, Any]:
    """Return declaration arguments for a work queue: dead-letter to the shared DLX.

    Typed dict[str, Any] to satisfy aio-pika's FieldTable argument.
    """
    return {
        "x-dead-letter-exchange": OUTBOUND_DLX,
        "x-dead-letter-routing-key": dlq_name(queue_name),
    }


# Every aio-pika await MUST be bounded: chat-stream is exempt from the
# request-timeout middleware, so an unbounded await against a stalled broker
# hangs forever (observed: a 35-minute hang in dev).

# Deadline for establishing the TCP/AMQP connection + handshake.
RABBITMQ_CONNECT_TIMEOUT_SECONDS = 10.0

# AMQP heartbeat interval. The broker drops the connection after two missed
# heartbeats, so a half-open socket surfaces as a real error instead of a hang.
RABBITMQ_HEARTBEAT_SECONDS = 30

# Deadline for one publish attempt (connect + optional declare + publish).
# ``_publish_with_retry`` makes at most two attempts, so worst case is 2x this.
RABBITMQ_PUBLISH_TIMEOUT_SECONDS = 10.0

# Deadline for declaring the whole outbound topology (DLX + per-platform work
# queue and DLQ). Larger than a publish because it is many round trips.
RABBITMQ_TOPOLOGY_TIMEOUT_SECONDS = 15.0
