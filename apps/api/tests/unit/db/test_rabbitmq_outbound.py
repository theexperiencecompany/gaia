"""Unit tests for the RabbitMQ outbound publish + topology logic.

Mocks only the aio-pika channel (the I/O boundary) and exercises the real
reconnect-retry, declare-or-not, and dead-letter topology code.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aio_pika
from aio_pika.exceptions import ChannelPreconditionFailed
import pytest

from app.constants.log_tags import LogTag
from app.constants.outbound import OUTBOUND_DLX, OUTBOUND_QUEUES, dlq_name, work_queue_arguments
from app.db import rabbitmq
from app.db.rabbitmq import RabbitMQPublisher
from tests.helpers import captured_wide_event


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


@pytest.mark.asyncio
class TestPublishWithRetry:
    async def test_publish_outbound_does_not_declare_the_queue(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        await pub.publish_outbound("outbound.whatsapp", b"{}")
        channel.default_exchange.publish.assert_awaited_once()
        channel.declare_queue.assert_not_awaited()  # topology is pre-declared

    async def test_publish_outbound_asks_for_no_declare_explicitly(
        self, connected_publisher
    ) -> None:
        """``declare`` must be False, not merely falsy.

        Watching ``declare_queue`` cannot tell False from None: ``_publish_with_retry``
        branches on ``if declare:`` and both values skip the declare, so the test
        above passes either way. The hole is real rather than pedantic — ``declare``
        is a required keyword-only ``bool``, so a None arriving there means a caller
        dropped the flag while the behaviour stays accidentally right, and it stops
        being right the moment that branch is tightened to an identity check: the
        outbound path would redeclare a pre-declared queue and take
        PRECONDITION_FAILED against the consumer's own declaration. Asserting the
        argument pins the contract the docstring already states.
        """
        pub, _ = connected_publisher
        with patch.object(pub, "_publish_with_retry", new=AsyncMock()) as publish_with_retry:
            await pub.publish_outbound("outbound.whatsapp", b"{}")

        assert publish_with_retry.await_args.kwargs["declare"] is False

    async def test_publish_outbound_routes_to_the_queue_it_was_given(
        self, connected_publisher
    ) -> None:
        """The routing key IS the queue name on the default exchange. Publishing
        under any other key drops the message on the floor: the default exchange
        has no binding to fall back on, so the bot never sees it."""
        pub, channel = connected_publisher
        await pub.publish_outbound("outbound.whatsapp", b"{}")
        assert (
            channel.default_exchange.publish.await_args.kwargs["routing_key"] == "outbound.whatsapp"
        )

    async def test_publish_outbound_stamps_the_broker_ttl(self, connected_publisher) -> None:
        """A durable queue outlives a bot outage; the message must not. The TTL
        rides on the AMQP message so the broker expires it with no consumer."""
        pub, channel = connected_publisher
        await pub.publish_outbound("outbound.whatsapp", b"{}", expiration=3600)
        message = channel.default_exchange.publish.await_args.args[0]
        assert message.expiration == 3600

    async def test_every_published_message_is_persistent(self, connected_publisher) -> None:
        """The outbound queues are durable so a broker restart keeps them, but a
        durable queue only keeps PERSISTENT messages. Published transient, a
        queued bot reply is lost on restart while the queue survives — the
        failure looks like the broker worked."""
        pub, channel = connected_publisher
        await pub.publish_outbound("outbound.whatsapp", b"{}")
        message = channel.default_exchange.publish.await_args.args[0]
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT

    async def test_publish_outbound_retries_once_then_succeeds(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        channel.default_exchange.publish.side_effect = [RuntimeError("boom"), None]

        async with captured_wide_event() as wide:
            await pub.publish_outbound("outbound.whatsapp", b"{}")

        # First attempt failed, reconnect path retried and succeeded.
        assert channel.default_exchange.publish.await_count == 2
        # A recovered publish is invisible except for this line, and the queue
        # is the only part of it that says WHICH traffic is flapping. Asserted
        # whole: blanking any field left a warning that reads fine and names
        # nothing.
        assert wide["warnings"] == [
            {
                "msg": f"{LogTag.STARTUP} Failed to publish to RabbitMQ, attempting recovery",
                "queue_name": "outbound.whatsapp",
                "error": "boom",
                "error_type": "RuntimeError",
            }
        ]

    async def test_publish_outbound_raises_when_both_attempts_fail(
        self, connected_publisher
    ) -> None:
        pub, channel = connected_publisher
        channel.default_exchange.publish.side_effect = RuntimeError("down")

        async with captured_wide_event() as wide:
            with pytest.raises(RuntimeError):
                await pub.publish_outbound("outbound.whatsapp", b"{}")

        assert channel.default_exchange.publish.await_count == 2
        # This is where a bot reply is actually lost. The exception that
        # propagates does not carry the queue, so this entry is the only record
        # of which conversation went silent — every field of it earns its place.
        assert wide["errors"] == [
            {
                "msg": (
                    f"{LogTag.STARTUP} Publish to RabbitMQ failed after retry — message dropped"
                ),
                "queue_name": "outbound.whatsapp",
                "error": "down",
                "error_type": "RuntimeError",
            }
        ]

    async def test_publish_declares_the_queue_on_demand(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        await pub.publish("ws-relay", b"{}")
        channel.declare_queue.assert_awaited_once()  # declare=True branch


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


@pytest.mark.asyncio
class TestLazyOutboundTopologyDeclare:
    """The first publish_outbound declares the topology lazily so a message
    never outruns the declaration; a divergent-args redeclare must not wedge
    delivery forever."""

    async def test_first_publish_declares_topology_then_publishes(
        self, connected_publisher
    ) -> None:
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False  # nothing declared yet
        channel.declare_exchange = AsyncMock(return_value=MagicMock())
        queue_mock = MagicMock(bind=AsyncMock())
        channel.declare_queue = AsyncMock(return_value=queue_mock)

        await pub.publish_outbound("outbound.whatsapp", b"{}")

        channel.declare_exchange.assert_awaited_once()  # topology declared lazily
        channel.default_exchange.publish.assert_awaited_once()  # then the message
        assert pub._outbound_topology_declared is True

    async def test_precondition_failed_marks_declared_and_still_publishes(
        self, connected_publisher
    ) -> None:
        # A queue already exists with divergent arguments: the redeclare is
        # rejected, but the queue IS present, so the publish must still go
        # through. The flag is set so we stop re-attempting the failing declare
        # on every publish (the wedge this guards against).
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False
        channel.declare_exchange = AsyncMock(
            side_effect=ChannelPreconditionFailed("inequivalent arg 'x-dead-letter-exchange'")
        )

        await pub.publish_outbound("outbound.whatsapp", b"{}")

        assert pub._outbound_topology_declared is True  # no infinite re-declare
        channel.default_exchange.publish.assert_awaited_once()  # message still sent

    async def test_precondition_failed_does_not_redeclare_on_next_publish(
        self, connected_publisher
    ) -> None:
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False
        channel.declare_exchange = AsyncMock(
            side_effect=ChannelPreconditionFailed("inequivalent arg")
        )

        await pub.publish_outbound("outbound.whatsapp", b"{}")
        await pub.publish_outbound("outbound.whatsapp", b"{}")

        # Declared-attempt happened once; the second publish skips it entirely.
        channel.declare_exchange.assert_awaited_once()
        assert channel.default_exchange.publish.await_count == 2

    async def test_non_precondition_declare_error_propagates_and_leaves_flag_false(
        self, connected_publisher
    ) -> None:
        # Only PRECONDITION_FAILED is self-healed. A transient declare failure
        # (broker blip, connection error) must NOT be swallowed: it propagates,
        # nothing is published, and the flag stays False so the NEXT publish
        # retries the declare instead of assuming a broken topology is fine.
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False
        channel.declare_exchange = AsyncMock(side_effect=RuntimeError("broker blip"))

        with pytest.raises(RuntimeError, match="broker blip"):
            await pub.publish_outbound("outbound.whatsapp", b"{}")

        assert pub._outbound_topology_declared is False  # will retry next time
        channel.default_exchange.publish.assert_not_awaited()  # never published

    async def test_precondition_self_heal_still_surfaces_a_publish_failure(
        self, connected_publisher
    ) -> None:
        # Self-healing the declare must not mask a genuine publish failure: after
        # marking the topology declared, a failing publish (both attempts) still
        # raises so the caller records it as FAILED rather than delivered.
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False
        channel.declare_exchange = AsyncMock(
            side_effect=ChannelPreconditionFailed("inequivalent arg")
        )
        channel.default_exchange.publish = AsyncMock(side_effect=RuntimeError("down"))

        with pytest.raises(RuntimeError, match="down"):
            await pub.publish_outbound("outbound.whatsapp", b"{}")

        assert pub._outbound_topology_declared is True  # declare won't be retried
        assert channel.default_exchange.publish.await_count == 2  # tried + retried


@pytest.mark.asyncio
class TestAmqpAwaitsAreBounded:
    """Every AMQP await has a deadline, so a stalled broker cannot hang a request.

    Chat-stream is exempt from the request-timeout middleware, so an un-bounded
    publish there hangs the request (and a graceful uvicorn reload) forever.
    """

    async def test_hanging_publish_times_out_instead_of_hanging(
        self, connected_publisher, monkeypatch
    ) -> None:
        pub, channel = connected_publisher
        monkeypatch.setattr(rabbitmq, "RABBITMQ_PUBLISH_TIMEOUT_SECONDS", 0.05)

        async def _never_returns(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(3600)

        channel.default_exchange.publish = AsyncMock(side_effect=_never_returns)

        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await pub.publish_outbound("outbound.whatsapp", b"{}")
        # Both attempts bounded: well under the 3600s hang, not the wall clock.
        assert time.monotonic() - started < 1.0
        assert channel.default_exchange.publish.await_count == 2

    async def test_hanging_publish_ends_in_the_failed_outcome(
        self, connected_publisher, monkeypatch
    ) -> None:
        """The caller contract in outbound_delivery still holds: FAILED, not a hang."""
        pub, channel = connected_publisher
        monkeypatch.setattr(rabbitmq, "RABBITMQ_PUBLISH_TIMEOUT_SECONDS", 0.05)

        async def _never_returns(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(3600)

        channel.default_exchange.publish = AsyncMock(side_effect=_never_returns)

        # Mirrors outbound_delivery's ``except Exception -> OutboundResult.FAILED``.
        try:
            await pub.publish_outbound("outbound.whatsapp", b"{}")
            outcome = "published"
        except Exception:
            outcome = "failed"
        assert outcome == "failed"

    async def test_connect_passes_explicit_timeout_and_heartbeat(self, monkeypatch) -> None:
        pub = RabbitMQPublisher("amqp://test")
        connection = MagicMock(is_closed=False)
        connection.channel = AsyncMock(return_value=MagicMock(is_closed=False))
        connect_robust = AsyncMock(return_value=connection)
        monkeypatch.setattr(aio_pika, "connect_robust", connect_robust)

        await pub.connect()

        kwargs = connect_robust.await_args.kwargs
        assert kwargs["timeout"] == rabbitmq.RABBITMQ_CONNECT_TIMEOUT_SECONDS
        assert kwargs["heartbeat"] == rabbitmq.RABBITMQ_HEARTBEAT_SECONDS

    async def test_concurrent_ensure_connected_creates_one_connection(self, monkeypatch) -> None:
        pub = RabbitMQPublisher("amqp://test")

        async def _slow_connect(*args: object, **kwargs: object) -> MagicMock:
            await asyncio.sleep(0.05)
            connection = MagicMock(is_closed=False)
            connection.channel = AsyncMock(return_value=MagicMock(is_closed=False))
            return connection

        connect_robust = AsyncMock(side_effect=_slow_connect)
        monkeypatch.setattr(aio_pika, "connect_robust", connect_robust)

        await asyncio.gather(*(pub.ensure_connected() for _ in range(5)))

        assert connect_robust.await_count == 1

    async def test_topology_declare_is_bounded(self, connected_publisher, monkeypatch) -> None:
        pub, channel = connected_publisher
        pub._outbound_topology_declared = False
        monkeypatch.setattr(rabbitmq, "RABBITMQ_TOPOLOGY_TIMEOUT_SECONDS", 0.05)

        async def _never_returns(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(3600)

        channel.declare_exchange = AsyncMock(side_effect=_never_returns)

        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await pub.declare_outbound_topology()
        assert time.monotonic() - started < 1.0
        # A timed-out declare must not be recorded as done.
        assert pub._outbound_topology_declared is False


@pytest.mark.asyncio
class TestTopologyArgumentsMatchTheConsumer:
    """Every declaration argument is a contract with the bot consumer: a durable
    flag or a routing key that drifts is PRECONDITION_FAILED at startup."""

    async def test_each_queue_and_binding_is_declared_exactly(self, connected_publisher) -> None:
        pub, channel = connected_publisher
        dlx = MagicMock()
        channel.declare_exchange = AsyncMock(return_value=dlx)
        queue_mock = MagicMock(bind=AsyncMock())
        channel.declare_queue = AsyncMock(return_value=queue_mock)

        await pub.declare_outbound_topology()

        for queue in OUTBOUND_QUEUES.values():
            channel.declare_queue.assert_any_await(dlq_name(queue), durable=True)
            channel.declare_queue.assert_any_await(
                queue, durable=True, arguments=work_queue_arguments(queue)
            )
            queue_mock.bind.assert_any_await(dlx, routing_key=dlq_name(queue))
        assert channel.declare_queue.await_count == 2 * len(OUTBOUND_QUEUES)
        assert pub._outbound_topology_declared is True

    async def test_no_channel_after_connecting_is_a_named_failure(self) -> None:
        pub = RabbitMQPublisher("amqp://test")
        pub.ensure_connected = AsyncMock()  # type: ignore[method-assign] -- the seam under test is what follows it

        with pytest.raises(RuntimeError, match="^Failed to establish RabbitMQ connection$"):
            await pub.declare_outbound_topology()

        assert pub._outbound_topology_declared is False

    async def test_a_half_open_connection_is_closed_before_reconnecting(self, monkeypatch) -> None:
        """A connect() that timed out between the connection and the channel
        leaves an open socket with no channel; the reconnect must close it,
        not just forget it."""
        pub = RabbitMQPublisher("amqp://test")
        stale = MagicMock(is_closed=False)
        stale.close = AsyncMock()
        pub.connection = stale
        pub.channel = None
        fresh = MagicMock(is_closed=False)
        fresh.channel = AsyncMock(return_value=MagicMock(is_closed=False))
        monkeypatch.setattr(aio_pika, "connect_robust", AsyncMock(return_value=fresh))

        await pub.ensure_connected()

        stale.close.assert_awaited_once()
        assert pub.connection is fresh

    async def test_a_stale_connection_that_will_not_close_does_not_block_the_reconnect(
        self, monkeypatch
    ) -> None:
        pub = RabbitMQPublisher("amqp://test")
        stale = MagicMock(is_closed=False)
        stale.close = AsyncMock(side_effect=RuntimeError("socket gone"))
        pub.connection = stale
        pub.channel = None
        fresh = MagicMock(is_closed=False)
        fresh.channel = AsyncMock(return_value=MagicMock(is_closed=False))
        monkeypatch.setattr(aio_pika, "connect_robust", AsyncMock(return_value=fresh))

        await pub.ensure_connected()

        assert pub.connection is fresh

    async def test_connect_dials_the_configured_url(self, monkeypatch) -> None:
        pub = RabbitMQPublisher("amqp://broker.example/vhost")
        connection = MagicMock(is_closed=False)
        connection.channel = AsyncMock(return_value=MagicMock(is_closed=False))
        connect_robust = AsyncMock(return_value=connection)
        monkeypatch.setattr(aio_pika, "connect_robust", connect_robust)

        await pub.connect()

        assert connect_robust.await_args.args == ("amqp://broker.example/vhost",)
