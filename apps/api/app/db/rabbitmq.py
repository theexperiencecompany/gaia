import aio_pika
from aio_pika import Message
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from aio_pika.exceptions import ChannelPreconditionFailed

from app.config.settings import settings
from app.constants.outbound import (
    OUTBOUND_DLX,
    OUTBOUND_QUEUES,
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

    async def connect(self):
        """Connect to RabbitMQ and create channel."""
        if self.connection is None:
            log.debug("Establishing RabbitMQ connection")
            self.connection = await aio_pika.connect_robust(self.amqp_url)
            self.channel = await self.connection.channel()
            log.set(db={"connection_status": "connected", "backend": "rabbitmq"})
            log.info("RabbitMQ connection established")

    async def declare_queue(self, queue_name: str):
        """Declare a queue if not already declared."""
        if queue_name not in self.declared_queues and self.channel:
            await self.channel.declare_queue(queue_name, durable=True)
            self.declared_queues.add(queue_name)
            log.debug(f"RabbitMQ queue '{queue_name}' declared")

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
        if not await self.is_connected():
            log.info("RabbitMQ connection not active, reconnecting...")
            # Reset connection state
            self.connection = None
            self.channel = None
            self.declared_queues.clear()
            self._outbound_topology_declared = False
            # Reconnect
            await self.connect()
            log.info("RabbitMQ reconnected successfully")

    async def _publish_with_retry(self, queue_name: str, body: bytes, *, declare: bool) -> None:
        """Publish to the default exchange, reconnecting and retrying once.

        The reconnect path handles ARQ-worker idle timeouts (workers publish
        sporadically). ``declare`` controls whether the queue is declared first:
        the WebSocket relay queue is declared on demand, while outbound work
        queues are pre-declared by ``declare_outbound_topology`` and pass False.
        """
        message = Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)

        async def _attempt() -> None:
            await self.ensure_connected()
            if not self.channel:
                raise RuntimeError("Failed to establish RabbitMQ connection")
            if declare:
                await self.declare_queue(queue_name)
            await self.channel.default_exchange.publish(message, routing_key=queue_name)

        try:
            await _attempt()
        except Exception as e:
            log.error(f"Failed to publish to RabbitMQ: {e}. Attempting recovery...")
            await _attempt()
            log.info("Successfully published after reconnection")

    async def publish(self, queue_name: str, body: bytes) -> None:
        """Publish to ``queue_name`` (declared on demand) with one retry."""
        await self._publish_with_retry(queue_name, body, declare=True)

    async def declare_outbound_topology(self) -> None:
        """Idempotently declare the outbound DLX, work queues, and DLQs.

        Declaration arguments MUST match the bot consumer's (see
        ``libs/shared/ts/src/bots/consumer/topology.ts``) or RabbitMQ rejects
        the redeclare with PRECONDITION_FAILED. Safe to call on every startup;
        the durable queues persist so messages survive while a bot is offline.
        """
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
        self._outbound_topology_declared = True

    async def publish_outbound(self, queue_name: str, body: bytes) -> None:
        """Publish to an outbound work queue with one retry.

        Declares the outbound topology once (lazily) before the first publish so
        a message can never outrun the startup declaration and be silently
        dropped on the default exchange. The flag resets on reconnect so a fresh
        channel re-declares.
        """
        if not self._outbound_topology_declared:
            try:
                await self.declare_outbound_topology()
            except ChannelPreconditionFailed as e:
                # A queue already exists with divergent arguments. The redeclare
                # is rejected (and closes the channel), but the queue IS present,
                # so publishing to it via the default exchange still works.
                # Mark the topology declared so we stop re-attempting the failing
                # redeclare on every publish (which would otherwise wedge all
                # outbound delivery), and surface the drift loudly for an
                # operator to reconcile.
                #
                # Residual: declare_outbound_topology declares the exchange then
                # each queue in a loop, so if the FIRST declaration is the one
                # that diverges, later queues in the same call are skipped and the
                # flag still flips. That's acceptable here because
                # declare_outbound_topology_on_startup eagerly declares the full
                # topology at boot for both the API and the worker — this lazy
                # path only runs as a post-reconnect fallback, by which point the
                # durable queues already exist.
                self._outbound_topology_declared = True
                log.error(
                    "Outbound topology redeclare rejected (divergent queue arguments); "
                    "publishing to the existing queue. Delete or migrate it to reconcile.",
                    error=str(e),
                )
        await self._publish_with_retry(queue_name, body, declare=False)

    async def close(self):
        """Close RabbitMQ connection and channel."""
        if self.channel:
            await self.channel.close()
            log.debug("RabbitMQ channel closed")
        if self.connection:
            await self.connection.close()
            log.info("RabbitMQ connection closed")


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
    log.debug("Initializing RabbitMQ publisher")

    rabbitmq_url: str = settings.RABBITMQ_URL  # type: ignore
    publisher = RabbitMQPublisher(rabbitmq_url)
    await publisher.connect()

    return publisher


async def get_rabbitmq_publisher() -> RabbitMQPublisher:
    """
    Get the RabbitMQ publisher from lazy provider.

    Returns:
        RabbitMQPublisher: The RabbitMQ publisher instance

    Raises:
        RuntimeError: If RabbitMQ publisher is not available
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
        # A queue already exists with divergent arguments. Unlike a missing
        # broker, the lazy first-publish re-declare CANNOT self-heal this —
        # every outbound publish keeps failing until an operator deletes or
        # migrates the queue, so surface it loudly instead of as a warning.
        log.error(
            "Outbound topology rejected: a queue exists with divergent arguments. "
            "Delete or migrate it — outbound delivery will fail until resolved.",
            error=str(e),
        )
        return
    except Exception as e:
        # Best-effort: a missing/unreachable broker must not crash-loop startup —
        # the first publish reconnects and re-declares the topology.
        log.warning("Outbound topology not declared at startup", error=str(e))
        return
    log.info("Outbound message topology declared")
