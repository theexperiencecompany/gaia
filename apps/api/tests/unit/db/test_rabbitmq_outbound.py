"""Unit tests for the RabbitMQ outbound publish + topology logic.

Mocks only the aio-pika channel (the I/O boundary) and exercises the real
reconnect-retry, declare-or-not, and dead-letter topology code.
"""

from unittest.mock import AsyncMock, MagicMock

import aio_pika
import pytest

from app.constants.outbound import OUTBOUND_DLX, OUTBOUND_QUEUES, dlq_name
from app.db.rabbitmq import RabbitMQPublisher


@pytest.fixture
def connected_publisher() -> tuple[RabbitMQPublisher, MagicMock]:
    """A publisher whose connection/channel report healthy, so ``ensure_connected``
    is a no-op and tests drive the real publish/declare paths."""
    pub = RabbitMQPublisher("amqp://test")
    pub.connection = MagicMock(is_closed=False)
    channel = MagicMock(is_closed=False)
    channel.default_exchange.publish = AsyncMock()
    channel.declare_queue = AsyncMock()
    channel.declare_exchange = AsyncMock()
    pub.channel = channel
    # Simulate the startup topology declaration already having run, so the
    # publish tests isolate the publish path (self-heal is exercised separately).
    pub._outbound_topology_declared = True
    return pub, channel


@pytest.mark.unit
@pytest.mark.asyncio
class TestPublishWithRetry:
    async def test_publish_outbound_does_not_declare_the_queue(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        await pub.publish_outbound("outbound.whatsapp", b"{}")
        channel.default_exchange.publish.assert_awaited_once()
        channel.declare_queue.assert_not_awaited()  # topology is pre-declared

    async def test_publish_outbound_retries_once_then_succeeds(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        channel.default_exchange.publish.side_effect = [RuntimeError("boom"), None]
        await pub.publish_outbound("outbound.whatsapp", b"{}")
        # First attempt failed, reconnect path retried and succeeded.
        assert channel.default_exchange.publish.await_count == 2

    async def test_publish_outbound_raises_when_both_attempts_fail(
        self, connected_publisher
    ) -> None:
        pub, channel = connected_publisher
        channel.default_exchange.publish.side_effect = RuntimeError("down")
        with pytest.raises(RuntimeError):
            await pub.publish_outbound("outbound.whatsapp", b"{}")
        assert channel.default_exchange.publish.await_count == 2

    async def test_publish_declares_the_queue_on_demand(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        await pub.publish("ws-relay", b"{}")
        channel.declare_queue.assert_awaited_once()  # declare=True branch


@pytest.mark.unit
@pytest.mark.asyncio
class TestDeclareOutboundTopology:
    async def test_declares_dlx_work_queues_and_bound_dlqs(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        dlx = MagicMock()
        channel.declare_exchange = AsyncMock(return_value=dlx)
        queue_mock = MagicMock()
        queue_mock.bind = AsyncMock()
        channel.declare_queue = AsyncMock(return_value=queue_mock)

        await pub.declare_outbound_topology()

        channel.declare_exchange.assert_awaited_once_with(
            OUTBOUND_DLX, aio_pika.ExchangeType.DIRECT, durable=True
        )

        declared = [c.args[0] for c in channel.declare_queue.call_args_list]
        for queue in OUTBOUND_QUEUES.values():
            assert queue in declared  # work queue
            assert dlq_name(queue) in declared  # its dead-letter queue

        # Each work queue carries the exact dead-letter arguments the bot
        # consumer also declares — a divergence here is PRECONDITION_FAILED.
        wa = next(
            c for c in channel.declare_queue.call_args_list if c.args[0] == "outbound.whatsapp"
        )
        assert wa.kwargs["arguments"] == {
            "x-dead-letter-exchange": "outbound.dlx",
            "x-dead-letter-routing-key": "outbound.whatsapp.dlq",
        }

        # Every DLQ is bound to the DLX.
        assert queue_mock.bind.await_count == len(OUTBOUND_QUEUES)
