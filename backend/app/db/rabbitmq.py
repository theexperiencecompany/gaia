from typing import Optional

import aio_pika
from aio_pika import Message
from aio_pika.abc import AbstractRobustConnection, AbstractChannel
from app.config.loggers import app_logger as logger
from app.config.settings import settings
from app.core.lazy_loader import MissingKeyStrategy, lazy_provider, providers


class RabbitMQPublisher:
    def __init__(self, amqp_url: str):
        self.amqp_url = amqp_url
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[AbstractChannel] = None
        self.declared_queues: set[str] = set()

    async def connect(self):
        """Connect to RabbitMQ and create channel."""
        if self.connection is None:
            logger.debug("Establishing RabbitMQ connection")
            self.connection = await aio_pika.connect_robust(self.amqp_url)
            self.channel = await self.connection.channel()
            logger.info("RabbitMQ connection established")

    async def declare_queue(self, queue_name: str):
        """Declare a queue if not already declared."""
        if queue_name not in self.declared_queues and self.channel:
            await self.channel.declare_queue(queue_name, durable=True)
            self.declared_queues.add(queue_name)
            logger.debug(f"RabbitMQ queue '{queue_name}' declared")

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
            logger.info("RabbitMQ connection not active, reconnecting...")
            # Reset connection state
            self.connection = None
            self.channel = None
            self.declared_queues.clear()
            # Reconnect
            await self.connect()
            logger.info("RabbitMQ reconnected successfully")

    async def publish(self, queue_name: str, body: bytes):
        """Publish message to queue with automatic reconnection."""
        # Ensure we're connected (handles idle timeout in ARQ workers)
        await self.ensure_connected()

        if not self.channel:
            raise RuntimeError("Failed to establish RabbitMQ connection")

        try:
            await self.declare_queue(queue_name)
            message = Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
            await self.channel.default_exchange.publish(message, routing_key=queue_name)
        except Exception as e:
            logger.error(f"Failed to publish to RabbitMQ: {e}. Attempting recovery...")
            # One more attempt after reconnecting
            await self.ensure_connected()
            if not self.channel:
                raise RuntimeError("Failed to re-establish RabbitMQ connection")
            await self.declare_queue(queue_name)
            message = Message(body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT)
            await self.channel.default_exchange.publish(message, routing_key=queue_name)
            logger.info("Successfully published after reconnection")

    async def close(self):
        """Close RabbitMQ connection and channel."""
        if self.channel:
            await self.channel.close()
            logger.debug("RabbitMQ channel closed")
        if self.connection:
            await self.connection.close()
            logger.info("RabbitMQ connection closed")


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
    logger.debug("Initializing RabbitMQ publisher")

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
    publisher_instance: Optional[RabbitMQPublisher] = await providers.aget(
        "rabbitmq_publisher"
    )
    if publisher_instance is None:
        raise RuntimeError("RabbitMQ publisher not available")
    return publisher_instance
