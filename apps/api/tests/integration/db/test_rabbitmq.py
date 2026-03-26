"""Integration tests for RabbitMQPublisher.

Patches `aio_pika.connect_robust` at the AMQP boundary so no real broker
connection is ever made.  All other code paths — idempotency guards, delivery
mode, auto-connect, auto-declare, retry logic — run through the real
RabbitMQPublisher implementation.

Design invariants (tests are written to enforce these):
- Removing the `if self.connection is None` guard  → test_connect_is_idempotent FAILS
- Removing `durable=True`                          → test_declare_queue_creates_queue FAILS
- Removing the `if queue_name not in …` guard      → test_declare_queue_is_idempotent FAILS
- Removing `delivery_mode=PERSISTENT`              → test_publish_message_is_persistent FAILS
"""

from unittest.mock import AsyncMock, call, patch

import aio_pika
import pytest

from app.db.rabbitmq import RabbitMQPublisher


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_mock_channel() -> AsyncMock:
    """Return a mock channel whose declare_queue returns a mock queue."""
    channel = AsyncMock()
    queue = AsyncMock()
    channel.declare_queue = AsyncMock(return_value=queue)
    # default_exchange.publish must be awaitable
    channel.default_exchange = AsyncMock()
    channel.default_exchange.publish = AsyncMock()
    channel.is_closed = False
    return channel


def _make_mock_connection(channel: AsyncMock) -> AsyncMock:
    """Return a mock AbstractRobustConnection backed by *channel*."""
    connection = AsyncMock()
    connection.channel = AsyncMock(return_value=channel)
    connection.close = AsyncMock()
    connection.is_closed = False
    return connection


@pytest.fixture
def mock_channel() -> AsyncMock:
    return _make_mock_channel()


@pytest.fixture
def mock_connection(mock_channel: AsyncMock) -> AsyncMock:
    return _make_mock_connection(mock_channel)


@pytest.fixture
def publisher() -> RabbitMQPublisher:
    """Fresh RabbitMQPublisher — not yet connected."""
    return RabbitMQPublisher(
        amqp_url="amqp://guest:guest@localhost/"  # pragma: allowlist secret
    )


# ---------------------------------------------------------------------------
# Shared context-manager helper
# ---------------------------------------------------------------------------


def _patch_connect_robust(mock_connection: AsyncMock):
    """Return a patcher for aio_pika.connect_robust → mock_connection."""
    return patch(
        "aio_pika.connect_robust",
        new=AsyncMock(return_value=mock_connection),
    )


# ---------------------------------------------------------------------------
# 1. connect()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConnect:
    async def test_connect_establishes_connection_and_channel(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """After connect(), both .connection and .channel must be set."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()

        assert publisher.connection is mock_connection
        assert publisher.channel is mock_channel

    async def test_connect_is_idempotent(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
    ):
        """Calling connect() twice must only call connect_robust once.

        This test MUST fail if the `if self.connection is None` guard is
        removed from RabbitMQPublisher.connect().
        """
        with patch(
            "aio_pika.connect_robust",
            new=AsyncMock(return_value=mock_connection),
        ) as mock_robust:
            await publisher.connect()
            await publisher.connect()

        mock_robust.assert_called_once()


# ---------------------------------------------------------------------------
# 2. declare_queue()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeclareQueue:
    async def test_declare_queue_creates_queue(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """declare_queue() must call channel.declare_queue with the correct
        name and durable=True.

        This test MUST fail if `durable=True` is removed from the production
        declare_queue() call.
        """
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.declare_queue("test_queue")

        mock_channel.declare_queue.assert_called_once_with("test_queue", durable=True)

    async def test_declare_queue_is_idempotent(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """Declaring the same queue twice must call channel.declare_queue
        exactly once.

        This test MUST fail if the `if queue_name not in self.declared_queues`
        guard is removed from the production implementation.
        """
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.declare_queue("test_queue")
            await publisher.declare_queue("test_queue")

        mock_channel.declare_queue.assert_called_once()

    async def test_declare_queue_tracks_different_queues_independently(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """Each distinct queue name must be declared exactly once."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.declare_queue("queue_a")
            await publisher.declare_queue("queue_b")
            await publisher.declare_queue("queue_a")  # duplicate — skipped

        assert mock_channel.declare_queue.call_count == 2
        calls = mock_channel.declare_queue.call_args_list
        assert call("queue_a", durable=True) in calls
        assert call("queue_b", durable=True) in calls

    async def test_declare_queue_no_op_when_not_connected(
        self,
        publisher: RabbitMQPublisher,
    ):
        """declare_queue() when channel is None must not raise."""
        # publisher.channel is None here — no connect() called
        await publisher.declare_queue("orphan_queue")  # must not raise
        assert "orphan_queue" not in publisher.declared_queues


# ---------------------------------------------------------------------------
# 3. publish()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPublish:
    async def test_publish_sends_message_to_correct_queue(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """publish() must route the message to the correct queue via
        default_exchange.publish with routing_key matching the queue name.
        """
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.publish("test_queue", b"hello")

        mock_channel.default_exchange.publish.assert_called_once()
        _, kwargs = mock_channel.default_exchange.publish.call_args
        assert kwargs.get("routing_key") == "test_queue"

    async def test_publish_message_is_persistent(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """The Message passed to publish() must use PERSISTENT delivery mode.

        This test MUST fail if `delivery_mode=aio_pika.DeliveryMode.PERSISTENT`
        is removed from the production publish() implementation.
        """
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.publish("test_queue", b"durable payload")

        mock_channel.default_exchange.publish.assert_called_once()
        positional_args, _ = mock_channel.default_exchange.publish.call_args
        message = positional_args[0]
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT

    async def test_publish_auto_connects_if_not_connected(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
    ):
        """publish() on a fresh publisher must trigger auto-connect without
        requiring an explicit connect() call first.
        """
        with patch(
            "aio_pika.connect_robust",
            new=AsyncMock(return_value=mock_connection),
        ) as mock_robust:
            await publisher.publish("auto_connect_queue", b"payload")

        mock_robust.assert_called_once()
        assert publisher.connection is mock_connection

    async def test_publish_auto_declares_queue_if_not_declared(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """publish() to a queue that has never been declared must trigger an
        automatic declare_queue() call before publishing.
        """
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            assert "auto_declared" not in publisher.declared_queues

            await publisher.publish("auto_declared", b"data")

        mock_channel.declare_queue.assert_called_once_with(
            "auto_declared", durable=True
        )
        assert "auto_declared" in publisher.declared_queues

    async def test_publish_message_body_matches_input(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """The bytes passed to publish() must appear verbatim in the Message."""
        payload = b'{"event": "user.created", "id": 42}'
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.publish("events", payload)

        positional_args, _ = mock_channel.default_exchange.publish.call_args
        message = positional_args[0]
        assert message.body == payload

    async def test_retry_logic_on_publish_failure(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """If the first publish attempt raises, the implementation must retry
        once after reconnection and ultimately succeed.

        The production code catches any exception on the first attempt, calls
        ensure_connected(), then publishes again.  This test verifies that the
        second attempt is made and the message is eventually delivered.
        """
        # First publish call raises; second succeeds (default AsyncMock)
        first_call = True

        async def _publish_side_effect(message, *, routing_key):
            nonlocal first_call
            if first_call:
                first_call = False
                raise RuntimeError("simulated broker error")

        mock_channel.default_exchange.publish.side_effect = _publish_side_effect

        # is_connected() must return True so ensure_connected() doesn't
        # reset state between attempts; we only want the retry path tested.
        mock_connection.is_closed = False
        mock_channel.is_closed = False

        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            # Must not raise — retry path kicks in
            await publisher.publish("retry_queue", b"important")

        # publish was attempted twice: once (failed) + once (success)
        assert mock_channel.default_exchange.publish.call_count == 2


# ---------------------------------------------------------------------------
# 4. close()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClose:
    async def test_close_closes_connection(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """close() must call connection.close() on a connected publisher."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.close()

        mock_connection.close.assert_called_once()

    async def test_close_closes_channel(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """close() must also call channel.close() before closing the connection."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()
            await publisher.close()

        mock_channel.close.assert_called_once()

    async def test_close_when_not_connected_is_safe(
        self,
        publisher: RabbitMQPublisher,
    ):
        """close() on a publisher that was never connected must not raise.

        Both .connection and .channel are None at this point, so the guard
        clauses in close() must prevent any attribute access errors.
        """
        await publisher.close()  # must not raise


# ---------------------------------------------------------------------------
# 5. is_connected() / ensure_connected()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestIsConnected:
    async def test_is_connected_returns_false_before_connect(
        self,
        publisher: RabbitMQPublisher,
    ):
        result = await publisher.is_connected()
        assert result is False

    async def test_is_connected_returns_true_after_connect(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        with _patch_connect_robust(mock_connection):
            await publisher.connect()

        result = await publisher.is_connected()
        assert result is True

    async def test_is_connected_returns_false_when_connection_closed(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """A closed connection must be reported as not connected."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()

        mock_connection.is_closed = True
        result = await publisher.is_connected()
        assert result is False

    async def test_is_connected_returns_false_when_channel_closed(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """A closed channel must be reported as not connected."""
        with _patch_connect_robust(mock_connection):
            await publisher.connect()

        mock_channel.is_closed = True
        result = await publisher.is_connected()
        assert result is False

    async def test_ensure_connected_reconnects_when_connection_lost(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
        mock_channel: AsyncMock,
    ):
        """ensure_connected() must re-run connect() when is_connected() is False."""
        with patch(
            "aio_pika.connect_robust",
            new=AsyncMock(return_value=mock_connection),
        ) as mock_robust:
            await publisher.connect()
            assert mock_robust.call_count == 1

            # Simulate a dropped connection
            mock_connection.is_closed = True

            await publisher.ensure_connected()

        # connect_robust must have been called a second time for reconnection
        assert mock_robust.call_count == 2

    async def test_ensure_connected_does_not_reconnect_when_healthy(
        self,
        publisher: RabbitMQPublisher,
        mock_connection: AsyncMock,
    ):
        """ensure_connected() must be a no-op when the connection is healthy."""
        with patch(
            "aio_pika.connect_robust",
            new=AsyncMock(return_value=mock_connection),
        ) as mock_robust:
            await publisher.connect()
            assert mock_robust.call_count == 1

            await publisher.ensure_connected()

        # Still exactly one call — no redundant reconnection
        mock_robust.assert_called_once()
