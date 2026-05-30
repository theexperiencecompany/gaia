"""Constants for the RabbitMQ outbound-message delivery pipeline.

Backend-originated messages for the messaging-platform bots (WhatsApp, Slack,
Telegram, Discord) are published to these per-platform queues; the bot
processes consume them, render the platform-native markdown, and send.

These queue names and dead-letter arguments are the single source of truth and
MUST stay byte-identical to ``libs/shared/ts/src/bots/consumer/topology.ts`` —
RabbitMQ rejects a redeclare whose arguments differ from the existing queue.
"""

from __future__ import annotations

from typing import Any

from app.models.chat_models import ConversationSource

# Dead-letter exchange every outbound work queue routes failed messages to.
OUTBOUND_DLX = "outbound.dlx"

# Per-platform durable work queues, keyed by conversation source so routing
# never compares raw strings.
OUTBOUND_QUEUES: dict[ConversationSource, str] = {
    ConversationSource.WHATSAPP: "outbound.whatsapp",
    ConversationSource.SLACK: "outbound.slack",
    ConversationSource.TELEGRAM: "outbound.telegram",
    ConversationSource.DISCORD: "outbound.discord",
}


def dlq_name(queue_name: str) -> str:
    """Dead-letter queue name for a given work queue."""
    return f"{queue_name}.dlq"


def work_queue_arguments(queue_name: str) -> dict[str, Any]:
    """Declaration arguments for a work queue: dead-letter to the shared DLX.

    Typed ``dict[str, Any]`` to satisfy aio-pika's ``FieldTable`` argument
    (an invariant dict whose values are an AMQP field-value union).
    """
    return {
        "x-dead-letter-exchange": OUTBOUND_DLX,
        "x-dead-letter-routing-key": dlq_name(queue_name),
    }
