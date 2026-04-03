"""Tests for WebSocketManager and WebSocketEventConsumer.

Covers:
- WebSocketManager: singleton pattern, add/remove connections, broadcast
  to user, RabbitMQ fallback for non-main-app workers, disconnected socket
  cleanup.
- WebSocketEventConsumer: start/stop lifecycle, message handling for valid
  broadcasts, unknown types, missing fields, JSON decode errors, disconnected
  sockets during broadcast, and the module-level start/stop helpers.
"""

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.websocket_manager import WebSocketManager, get_websocket_manager


# ---------------------------------------------------------------------------
# WebSocketManager — Singleton
# ---------------------------------------------------------------------------


class TestWebSocketManagerSingleton:
    def setup_method(self) -> None:
        # Reset singleton between tests so each test is isolated
        WebSocketManager._instance = None

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    def test_singleton_returns_same_instance(self) -> None:
        mgr1 = WebSocketManager()
        mgr2 = WebSocketManager()
        assert mgr1 is mgr2

    def test_connections_initialized_once(self) -> None:
        mgr = WebSocketManager()
        mgr.connections["test"] = set()
        mgr2 = WebSocketManager()
        # Same instance, connections dict preserved
        assert "test" in mgr2.connections

    def test_get_websocket_manager_returns_singleton(self) -> None:
        # get_websocket_manager uses the module-level instance, but after reset
        # we need to verify the function itself works
        mgr = get_websocket_manager()
        assert isinstance(mgr, WebSocketManager)


# ---------------------------------------------------------------------------
# WebSocketManager — add / remove connections
# ---------------------------------------------------------------------------


class TestAddRemoveConnections:
    def setup_method(self) -> None:
        WebSocketManager._instance = None
        self.mgr = WebSocketManager()

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    def test_add_connection_creates_user_set(self) -> None:
        ws = MagicMock()
        self.mgr.add_connection("user1", ws)

        assert "user1" in self.mgr.connections
        assert ws in self.mgr.connections["user1"]

    def test_add_multiple_connections_same_user(self) -> None:
        ws1, ws2 = MagicMock(), MagicMock()
        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        assert len(self.mgr.connections["user1"]) == 2

    def test_remove_connection(self) -> None:
        ws = MagicMock()
        self.mgr.add_connection("user1", ws)
        self.mgr.remove_connection("user1", ws)

        # User key should be cleaned up when last connection is removed
        assert "user1" not in self.mgr.connections

    def test_remove_connection_keeps_other_connections(self) -> None:
        ws1, ws2 = MagicMock(), MagicMock()
        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        self.mgr.remove_connection("user1", ws1)

        assert "user1" in self.mgr.connections
        assert ws2 in self.mgr.connections["user1"]
        assert ws1 not in self.mgr.connections["user1"]

    def test_remove_nonexistent_user_no_error(self) -> None:
        ws = MagicMock()
        # Should not raise
        self.mgr.remove_connection("nonexistent", ws)

    def test_remove_nonexistent_websocket_no_error(self) -> None:
        ws1, ws2 = MagicMock(), MagicMock()
        self.mgr.add_connection("user1", ws1)
        # ws2 was never added — discard is safe
        self.mgr.remove_connection("user1", ws2)
        assert ws1 in self.mgr.connections["user1"]


# ---------------------------------------------------------------------------
# WebSocketManager — broadcast_to_user (main app path)
# ---------------------------------------------------------------------------


class TestBroadcastToUser:
    def setup_method(self) -> None:
        WebSocketManager._instance = None
        self.mgr = WebSocketManager()

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broadcasts_to_all_user_connections(
        self, mock_is_main: MagicMock
    ) -> None:
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        message = {"type": "notification", "text": "hello"}
        await self.mgr.broadcast_to_user("user1", message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broadcast_to_user_with_no_connections(
        self, mock_is_main: MagicMock
    ) -> None:
        """Should silently return when user has no connections."""
        await self.mgr.broadcast_to_user("nobody", {"type": "test"})
        # No error raised

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_removes_disconnected_sockets_on_send_failure(
        self, mock_is_main: MagicMock
    ) -> None:
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("connection closed")

        self.mgr.add_connection("user1", ws_good)
        self.mgr.add_connection("user1", ws_bad)

        await self.mgr.broadcast_to_user("user1", {"type": "test"})

        # Good socket received message
        ws_good.send_json.assert_awaited_once()
        # Bad socket removed
        assert ws_bad not in self.mgr.connections.get("user1", set())
        # Good socket still present
        assert ws_good in self.mgr.connections["user1"]

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_all_sockets_fail_leaves_empty_set(
        self, mock_is_main: MagicMock
    ) -> None:
        ws1 = AsyncMock()
        ws1.send_json.side_effect = RuntimeError("closed")
        ws2 = AsyncMock()
        ws2.send_json.side_effect = RuntimeError("closed")

        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        await self.mgr.broadcast_to_user("user1", {"type": "test"})

        # Both removed; user key may still exist with empty set
        remaining = self.mgr.connections.get("user1", set())
        assert len(remaining) == 0


# ---------------------------------------------------------------------------
# WebSocketManager — RabbitMQ fallback (non-main-app worker)
# ---------------------------------------------------------------------------


class TestBroadcastViaRabbitMQ:
    def setup_method(self) -> None:
        WebSocketManager._instance = None
        self.mgr = WebSocketManager()

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    @patch("app.core.websocket_manager.is_main_app", return_value=False)
    @patch("app.core.websocket_manager.get_rabbitmq_publisher", new_callable=AsyncMock)
    async def test_publishes_to_rabbitmq_when_not_main_app(
        self,
        mock_get_publisher: AsyncMock,
        mock_is_main: MagicMock,
    ) -> None:
        mock_publisher = AsyncMock()
        mock_get_publisher.return_value = mock_publisher

        message: Dict[str, Any] = {"type": "notification", "text": "hello"}
        await self.mgr.broadcast_to_user("user1", message)

        mock_publisher.publish.assert_awaited_once()
        call_args = mock_publisher.publish.call_args
        queue_name = call_args[0][0]
        body = json.loads(call_args[0][1].decode("utf-8"))

        assert queue_name == "websocket-events"
        assert body["type"] == "websocket_broadcast"
        assert body["user_id"] == "user1"
        assert body["message"] == message

    @patch("app.core.websocket_manager.is_main_app", return_value=False)
    @patch("app.core.websocket_manager.get_rabbitmq_publisher", new_callable=AsyncMock)
    async def test_rabbitmq_publish_failure_is_logged_not_raised(
        self,
        mock_get_publisher: AsyncMock,
        mock_is_main: MagicMock,
    ) -> None:
        mock_get_publisher.side_effect = RuntimeError("RabbitMQ down")

        # Should not raise
        await self.mgr.broadcast_to_user("user1", {"type": "test"})


# ---------------------------------------------------------------------------
# WebSocketEventConsumer
# ---------------------------------------------------------------------------


class TestWebSocketEventConsumer:
    """Tests for the RabbitMQ consumer that forwards messages to WebSocket."""

    def setup_method(self) -> None:
        WebSocketManager._instance = None

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    def _make_consumer(self):
        from app.core.websocket_consumer import WebSocketEventConsumer

        return WebSocketEventConsumer()

    def _make_message(self, body: Dict[str, Any]) -> MagicMock:
        """Create a mock aio_pika message with an async context manager."""
        msg = MagicMock()
        msg.body = json.dumps(body).encode("utf-8")
        # process() returns an async context manager
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=None)
        msg.process.return_value = ctx
        return msg

    async def test_handles_valid_websocket_broadcast(self) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer
        from app.core.websocket_manager import websocket_manager

        consumer = WebSocketEventConsumer()
        ws = AsyncMock()
        websocket_manager.connections["user_x"] = {ws}

        body = {
            "type": "websocket_broadcast",
            "user_id": "user_x",
            "message": {"event": "new_todo"},
        }
        msg = self._make_message(body)

        await consumer._handle_websocket_message(msg)

        ws.send_json.assert_awaited_once_with({"event": "new_todo"})
        # Cleanup
        websocket_manager.connections.pop("user_x", None)

    async def test_ignores_unknown_message_type(self) -> None:
        consumer = self._make_consumer()

        body = {"type": "unknown_type", "data": "something"}
        msg = self._make_message(body)

        # Should not raise
        await consumer._handle_websocket_message(msg)

    async def test_ignores_missing_user_id(self) -> None:
        consumer = self._make_consumer()

        body = {
            "type": "websocket_broadcast",
            "user_id": None,
            "message": {"event": "test"},
        }
        msg = self._make_message(body)

        # Should not raise
        await consumer._handle_websocket_message(msg)

    async def test_ignores_missing_message(self) -> None:
        consumer = self._make_consumer()

        body = {
            "type": "websocket_broadcast",
            "user_id": "user1",
            "message": None,
        }
        msg = self._make_message(body)

        # Should not raise
        await consumer._handle_websocket_message(msg)

    async def test_no_connections_for_user_no_error(self) -> None:
        consumer = self._make_consumer()

        body = {
            "type": "websocket_broadcast",
            "user_id": "offline_user",
            "message": {"event": "test"},
        }
        msg = self._make_message(body)

        # Should not raise
        await consumer._handle_websocket_message(msg)

    async def test_removes_disconnected_sockets_during_broadcast(self) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer
        from app.core.websocket_manager import websocket_manager

        consumer = WebSocketEventConsumer()
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("closed")
        websocket_manager.connections["user_y"] = {ws_good, ws_bad}

        body = {
            "type": "websocket_broadcast",
            "user_id": "user_y",
            "message": {"event": "test"},
        }
        msg = self._make_message(body)

        await consumer._handle_websocket_message(msg)

        ws_good.send_json.assert_awaited_once()
        assert ws_bad not in websocket_manager.connections.get("user_y", set())
        # Cleanup
        websocket_manager.connections.pop("user_y", None)

    async def test_handles_invalid_json(self) -> None:
        consumer = self._make_consumer()

        msg = MagicMock()
        msg.body = b"not-json{{"
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=None)
        ctx.__aexit__ = AsyncMock(return_value=None)
        msg.process.return_value = ctx

        # Should not raise
        await consumer._handle_websocket_message(msg)

    async def test_handles_generic_exception(self) -> None:
        """An unexpected exception inside message processing should be caught."""
        from app.core.websocket_consumer import WebSocketEventConsumer
        from app.core.websocket_manager import websocket_manager

        consumer = WebSocketEventConsumer()

        body = {
            "type": "websocket_broadcast",
            "user_id": "user_err",
            "message": {"event": "test"},
        }
        msg = self._make_message(body)

        # Simulate an unexpected error by replacing connections with a dict-like
        # object whose __contains__ raises.
        original_connections = websocket_manager.connections
        bad_connections = MagicMock()
        bad_connections.__contains__ = MagicMock(side_effect=TypeError("boom"))
        websocket_manager.connections = bad_connections
        try:
            # Should not raise — exception is caught and logged
            await consumer._handle_websocket_message(msg)
        finally:
            websocket_manager.connections = original_connections


# ---------------------------------------------------------------------------
# WebSocketEventConsumer — start / stop lifecycle
# ---------------------------------------------------------------------------


class TestWebSocketEventConsumerLifecycle:
    @patch("app.core.websocket_consumer.connect_robust", new_callable=AsyncMock)
    async def test_start_creates_connection_and_queue(
        self, mock_connect: AsyncMock
    ) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer

        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue
        mock_connect.return_value = mock_connection

        consumer = WebSocketEventConsumer()
        await consumer.start()

        mock_connect.assert_awaited_once()
        mock_channel.set_qos.assert_awaited_once_with(prefetch_count=10)
        mock_channel.declare_queue.assert_awaited_once_with(
            "websocket-events", durable=True
        )
        mock_queue.consume.assert_awaited_once()

        assert consumer.connection is mock_connection
        assert consumer.channel is mock_channel
        assert consumer.queue is mock_queue

    @patch("app.core.websocket_consumer.connect_robust", new_callable=AsyncMock)
    async def test_start_raises_on_connection_failure(
        self, mock_connect: AsyncMock
    ) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer

        mock_connect.side_effect = RuntimeError("connection refused")

        consumer = WebSocketEventConsumer()
        with pytest.raises(RuntimeError, match="connection refused"):
            await consumer.start()

    async def test_stop_closes_channel_and_connection(self) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer

        consumer = WebSocketEventConsumer()
        consumer.connection = AsyncMock()
        consumer.channel = AsyncMock()
        consumer.queue = AsyncMock()
        consumer.consumer_tag = "tag-123"

        await consumer.stop()

        consumer.queue.cancel.assert_awaited_once_with("tag-123")
        consumer.channel.close.assert_awaited_once()
        consumer.connection.close.assert_awaited_once()

    async def test_stop_handles_missing_resources_gracefully(self) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer

        consumer = WebSocketEventConsumer()
        # All fields are None
        await consumer.stop()  # Should not raise

    async def test_stop_handles_close_errors(self) -> None:
        from app.core.websocket_consumer import WebSocketEventConsumer

        consumer = WebSocketEventConsumer()
        consumer.connection = AsyncMock()
        consumer.connection.close.side_effect = RuntimeError("close failed")
        consumer.channel = AsyncMock()

        # Should not raise
        await consumer.stop()


# ---------------------------------------------------------------------------
# Module-level start/stop helpers
# ---------------------------------------------------------------------------


class TestModuleLevelHelpers:
    @patch("app.core.websocket_consumer.connect_robust", new_callable=AsyncMock)
    async def test_start_websocket_consumer_creates_and_starts(
        self, mock_connect: AsyncMock
    ) -> None:
        import app.core.websocket_consumer as mod

        # Reset module state
        mod.websocket_consumer = None

        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue
        mock_connect.return_value = mock_connection

        await mod.start_websocket_consumer()

        assert mod.websocket_consumer is not None
        mock_connect.assert_awaited_once()

        # Cleanup
        mod.websocket_consumer = None

    async def test_stop_websocket_consumer_stops_and_clears(self) -> None:
        import app.core.websocket_consumer as mod

        mock_consumer = AsyncMock()
        mod.websocket_consumer = mock_consumer

        await mod.stop_websocket_consumer()

        mock_consumer.stop.assert_awaited_once()
        assert mod.websocket_consumer is None

    async def test_stop_websocket_consumer_noop_when_none(self) -> None:
        import app.core.websocket_consumer as mod

        mod.websocket_consumer = None
        await mod.stop_websocket_consumer()  # Should not raise
        assert mod.websocket_consumer is None

    @patch("app.core.websocket_consumer.connect_robust", new_callable=AsyncMock)
    async def test_start_is_idempotent(self, mock_connect: AsyncMock) -> None:
        import app.core.websocket_consumer as mod

        mock_channel = AsyncMock()
        mock_queue = AsyncMock()
        mock_connection = AsyncMock()
        mock_connection.channel.return_value = mock_channel
        mock_channel.declare_queue.return_value = mock_queue
        mock_connect.return_value = mock_connection

        mod.websocket_consumer = None
        await mod.start_websocket_consumer()
        first_consumer = mod.websocket_consumer

        # Calling again should not create a second consumer
        await mod.start_websocket_consumer()
        assert mod.websocket_consumer is first_consumer
        assert mock_connect.await_count == 1

        # Cleanup
        mod.websocket_consumer = None
