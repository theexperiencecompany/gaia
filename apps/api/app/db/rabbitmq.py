import asyncio
import contextlib

import aio_pika
from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from aio_pika.exceptions import ChannelPreconditionFailed

from app.config.settings import settings
from app.constants.log_tags import LogTag
from app.constants.outbound import (
    OUTBOUND_DLX,
    OUTBOUND_QUEUES,
    RABBITMQ_CONNECT_TIMEOUT_SECONDS,
    RABBITMQ_HEARTBEAT_SECONDS,
    RABBITMQ_PUBLISH_TIMEOUT_SECONDS,
    RABBITMQ_TOPOLOGY_TIMEOUT_SECONDS,
    dlq_name,
    work_queue_arguments,
)
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers
from shared.py.wide_events import log


class RabbitMQPublisher:
    def __init__(self, amqp_url: str):
        self.amqp_url = amqp_url
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractChannel | None = None
        self.declared_queues: set[str] = set()
        self._outbound_topology_declared: bool = False
        # Serializes reconnects so concurrent publishers cannot each open a
        # connection (and leak all but the last one).
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Connect to RabbitMQ and create channel."""
        if self.connection is None:
            log.debug(f"{LogTag.STARTUP} Establishing RabbitMQ connection")
            self.connection = await aio_pika.connect_robust(
                self.amqp_url,
                timeout=RABBITMQ_CONNECT_TIMEOUT_SECONDS,
                heartbeat=RABBITMQ_HEARTBEAT_SECONDS,
            )
            self.channel = await self.connection.channel()
            log.set(db={"connection_status": "connected", "backend": "rabbitmq"})
            log.info(f"{LogTag.STARTUP} RabbitMQ connection established")

    async def declare_queue(self, queue_name: str) -> None:
        """Declare a queue if not already declared."""
        if queue_name not in self.declared_queues and self.channel:
            await self.channel.declare_queue(queue_name, durable=True)
            self.declared_queues.add(queue_name)
            log.debug(f"{LogTag.STARTUP} RabbitMQ queue declared", queue_name=queue_name)

    async def is_connected(self) -> bool:
        """Check if the RabbitMQ connection is still active."""
        try:
            return (
                self.connection is not None
                and not self.connection.is_closed
                and self.channel is not None
                and not self.channel.is_closed
            )
        except Exception:
            return False

    async def ensure_connected(self) -> None:
        """Ensure connection is active, reconnect if necessary.

        This is critical for ARQ workers where connections can timeout
        during long-running tasks. FastAPI main app stays connected via
        the WebSocket consumer, but ARQ workers only publish sporadically.
        """
        if await self.is_connected():
            return
        async with self._connect_lock:
            # Double-checked: another waiter may have reconnected while we
            # queued on the lock.
            if await self.is_connected():
                return
            log.info(f"{LogTag.STARTUP} RabbitMQ connection not active, reconnecting...")
            # A connection can be open with no channel (connect() timed out
            # between the two); forgetting it would leak the socket and its
            # heartbeat task, once per timeout.
            if self.connection is not None and not self.connection.is_closed:
                with contextlib.suppress(Exception):
                    await self.connection.close()
            # Reset connection state
            self.connection = None
            self.channel = None
            self.declared_queues.clear()
            self._outbound_topology_declared = False
            # Reconnect
            await self.connect()
            log.info(f"{LogTag.STARTUP} RabbitMQ reconnected successfully")

    async def _publish_with_retry(
        self, queue_name: str, body: bytes, *, declare: bool, expiration: int | None = None
    ) -> None:
        """Publish to the default exchange, reconnecting and retrying once.

        The reconnect path handles ARQ-worker idle timeouts (workers publish
        sporadically). declare controls whether the queue is declared first:
        the WebSocket relay queue is declared on demand, while outbound work
        queues are pre-declared by declare_outbound_topology and pass False.
        """
        message = Message(
            body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT, expiration=expiration
        )

        async def _attempt() -> None:
            await self.ensure_connected()
            if not self.channel:
                raise RuntimeError("Failed to establish RabbitMQ connection")
            if declare:
                await self.declare_queue(queue_name)
            await self.channel.default_exchange.publish(message, routing_key=queue_name)

        try:
            await asyncio.wait_for(_attempt(), timeout=RABBITMQ_PUBLISH_TIMEOUT_SECONDS)
        except Exception as e:
            log.warning(
                f"{LogTag.STARTUP} Failed to publish to RabbitMQ, attempting recovery",
                queue_name=queue_name,
                error=str(e),
                error_type=type(e).__name__,
            )
            try:
                await asyncio.wait_for(_attempt(), timeout=RABBITMQ_PUBLISH_TIMEOUT_SECONDS)
            except Exception as retry_error:
                # Where a bot reply is actually lost. One attempt failing is
                # routine and recovers; both failing is the incident, and the
                # propagating exception does not say which queue it was.
                log.error(
                    f"{LogTag.STARTUP} Publish to RabbitMQ failed after retry — message dropped",
                    queue_name=queue_name,
                    error=str(retry_error),
                    error_type=type(retry_error).__name__,
                )
                raise
            log.info(
                f"{LogTag.STARTUP} Successfully published after reconnection",
                queue_name=queue_name,
            )

    async def publish(self, queue_name: str, body: bytes) -> None:
        """Publish to queue_name (declared on demand) with one retry."""
        await self._publish_with_retry(queue_name, body, declare=True)

    async def declare_outbound_topology(self) -> None:
        """Idempotently declare the outbound DLX, work queues, and DLQs.

        Declaration arguments MUST match the bot consumer's (see
        libs/shared/ts/src/bots/consumer/topology.ts) or RabbitMQ rejects
        the redeclare with PRECONDITION_FAILED. Safe to call on every startup;
        the durable queues persist so messages survive while a bot is offline.
        """

        async def _declare() -> None:
            await self.ensure_connected()
            if not self.channel:
                raise RuntimeError("Failed to establish RabbitMQ connection")

            dlx = await self.channel.declare_exchange(
                OUTBOUND_DLX, aio_pika.ExchangeType.DIRECT, durable=True
            )
            for queue_name in OUTBOUND_QUEUES.values():
                dlq = await self.channel.declare_queue(dlq_name(queue_name), durable=True)
                await dlq.bind(dlx, routing_key=dlq_name(queue_name))
                await self.channel.declare_queue(
                    queue_name, durable=True, arguments=work_queue_arguments(queue_name)
                )

        await asyncio.wait_for(_declare(), timeout=RABBITMQ_TOPOLOGY_TIMEOUT_SECONDS)
        self._outbound_topology_declared = True

    async def publish_outbound(
        self, queue_name: str, body: bytes, *, expiration: int | None = None
    ) -> None:
        """Publish to an outbound work queue with one retry.

        expiration is the broker-side TTL in seconds; past it the message dead-letters. Topology
        is declared lazily before the first publish and re-declared after reconnect.
        """
        if not self._outbound_topology_declared:
            try:
                await self.declare_outbound_topology()
            except ChannelPreconditionFailed as e:
                # Queue exists with divergent arguments; redeclare closes the channel but the
                # queue still works via the default exchange. Mark declared, stop retrying, and
                # log the drift for an operator to reconcile.
                self._outbound_topology_declared = True
                log.error(
                    f"{LogTag.STARTUP} Outbound topology redeclare rejected (divergent queue arguments); "
                    "publishing to the existing queue. Delete or migrate it to reconcile.",
                    error=str(e),
                )
        await self._publish_with_retry(queue_name, body, declare=False, expiration=expiration)

    async def close(self) -> None:
        """Close RabbitMQ connection and channel."""
        if self.channel:
            await self.channel.close()
            log.debug(f"{LogTag.STARTUP} RabbitMQ channel closed")
        if self.connection:
            await self.connection.close()
            log.info(f"{LogTag.STARTUP} RabbitMQ connection closed")


@lazy_provider(
    name="rabbitmq_publisher",
    required_keys=[settings.RABBITMQ_URL],
    strategy=MissingKeyStrategy.WARN,
    auto_initialize=True,
    warning_message="RabbitMQ URL not configured. Message publishing features will be disabled.",
)
async def init_rabbitmq_publisher() -> RabbitMQPublisher:
    """
    Initialize RabbitMQ publisher with connection.

    Returns:
        RabbitMQPublisher: Connected RabbitMQ publisher instance
    """
    log.debug(f"{LogTag.STARTUP} Initializing RabbitMQ publisher")

    rabbitmq_url: str = settings.RABBITMQ_URL
    publisher = RabbitMQPublisher(rabbitmq_url)
    await publisher.connect()

    return publisher


async def get_rabbitmq_publisher() -> RabbitMQPublisher:
    """Get the RabbitMQ publisher from the lazy provider.

    Raises:
        RuntimeError: If the publisher is not available.
    """
    publisher_instance: RabbitMQPublisher | None = await providers.aget("rabbitmq_publisher")
    if publisher_instance is None:
        raise RuntimeError("RabbitMQ publisher not available")
    return publisher_instance


async def declare_outbound_topology_on_startup() -> None:
    """Declare the outbound bot-message queue topology at startup.

    No-op when RabbitMQ is unconfigured (e.g. local dev without a broker).
    """
    try:
        publisher = await get_rabbitmq_publisher()
        await publisher.declare_outbound_topology()
    except ChannelPreconditionFailed as e:
        # Queue exists with divergent arguments; unlike a missing broker this can't self-heal,
        # so surface it loudly instead of as a warning.
        log.error(
            f"{LogTag.STARTUP} Outbound topology rejected: a queue exists with divergent arguments. "
            "Delete or migrate it — outbound delivery will fail until resolved.",
            error=str(e),
        )
        return
    except Exception as e:
        # Best-effort: a missing/unreachable broker must not crash-loop startup —
        # the first publish reconnects and re-declares the topology.
        log.warning(f"{LogTag.STARTUP} Outbound topology not declared at startup", error=str(e))
        return
    log.info(f"{LogTag.STARTUP} Outbound message topology declared")
