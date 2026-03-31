"""
TEST 8: WebSocket Connection Lifecycle

Integration tests for the WebSocketManager — connection registration,
removal, message routing, multi-user isolation, broadcast, concurrent
connections, and error handling.

Tests exercise the real WebSocketManager class from
app.core.websocket_manager with mock WebSocket objects at the I/O boundary.
"""

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.websocket_consumer import WebSocketEventConsumer
from app.core.websocket_manager import WebSocketManager
from app.services.notification_service import NotificationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws(*, closed: bool = False) -> AsyncMock:
    """Create a mock WebSocket that records send_json calls."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    # Give each mock a unique id so set hashing works
    ws.__hash__ = MagicMock(return_value=id(ws))
    ws.__eq__ = lambda self, other: self is other
    return ws


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def manager() -> WebSocketManager:
    """Return a *fresh* WebSocketManager instance (bypass singleton)."""
    mgr = object.__new__(WebSocketManager)
    mgr.connections = {}
    mgr.initialized = True
    return mgr


USER_A = "user-aaa-111"
USER_B = "user-bbb-222"

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWebSocketConnectionManagement:
    """Connection registration and removal."""

    def test_add_connection_registers_user(self, manager: WebSocketManager) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        assert USER_A in manager.connections
        assert ws in manager.connections[USER_A]

    def test_remove_connection_deregisters_user(
        self, manager: WebSocketManager
    ) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)
        manager.remove_connection(USER_A, ws)

        # User key should be cleaned up entirely when last connection is removed
        assert USER_A not in manager.connections

    def test_remove_nonexistent_connection_is_noop(
        self, manager: WebSocketManager
    ) -> None:
        """Removing a connection that was never added must not raise."""
        ws = _make_ws()
        manager.remove_connection("ghost-user", ws)
        assert "ghost-user" not in manager.connections

    def test_add_multiple_connections_same_user(
        self, manager: WebSocketManager
    ) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)

        assert len(manager.connections[USER_A]) == 2
        assert ws1 in manager.connections[USER_A]
        assert ws2 in manager.connections[USER_A]

    def test_remove_one_of_multiple_connections(
        self, manager: WebSocketManager
    ) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)

        manager.remove_connection(USER_A, ws1)

        assert USER_A in manager.connections
        assert ws1 not in manager.connections[USER_A]
        assert ws2 in manager.connections[USER_A]


@pytest.mark.integration
class TestWebSocketConnectionCount:
    """Connection count tracking accuracy after connect/disconnect cycles."""

    def test_connection_count_after_add_remove_cycles(
        self, manager: WebSocketManager
    ) -> None:
        sockets = [_make_ws() for _ in range(5)]

        for ws in sockets:
            manager.add_connection(USER_A, ws)
        assert len(manager.connections[USER_A]) == 5

        # Remove three
        for ws in sockets[:3]:
            manager.remove_connection(USER_A, ws)
        assert len(manager.connections[USER_A]) == 2

        # Remove remaining two — user key should be cleaned up
        for ws in sockets[3:]:
            manager.remove_connection(USER_A, ws)
        assert USER_A not in manager.connections

    def test_multiple_users_tracked_independently(
        self, manager: WebSocketManager
    ) -> None:
        ws_a = _make_ws()
        ws_b = _make_ws()
        manager.add_connection(USER_A, ws_a)
        manager.add_connection(USER_B, ws_b)

        assert len(manager.connections) == 2

        manager.remove_connection(USER_A, ws_a)
        assert USER_A not in manager.connections
        assert USER_B in manager.connections


@pytest.mark.integration
class TestWebSocketMessageRouting:
    """Messages reach the correct user's connections."""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broadcast_to_user_delivers_message(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        message: Dict[str, Any] = {"type": "notification", "body": "hello"}
        await manager.broadcast_to_user(USER_A, message)

        ws.send_json.assert_awaited_once_with(message)

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broadcast_to_nonexistent_user_is_noop(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """Sending to a user with no connections must not raise."""
        await manager.broadcast_to_user("nobody", {"type": "test"})
        # No assertion needed — just verifying no exception

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broadcast_delivers_to_all_connections_of_user(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)

        message = {"type": "update", "data": 42}
        await manager.broadcast_to_user(USER_A, message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)


@pytest.mark.integration
class TestWebSocketMultiUserIsolation:
    """Messages for user A must never reach user B."""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_user_b_does_not_receive_user_a_message(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        ws_a = _make_ws()
        ws_b = _make_ws()
        manager.add_connection(USER_A, ws_a)
        manager.add_connection(USER_B, ws_b)

        await manager.broadcast_to_user(USER_A, {"type": "secret"})

        ws_a.send_json.assert_awaited_once()
        ws_b.send_json.assert_not_awaited()

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_each_user_receives_own_messages_only(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        ws_a = _make_ws()
        ws_b = _make_ws()
        manager.add_connection(USER_A, ws_a)
        manager.add_connection(USER_B, ws_b)

        msg_a = {"for": "a"}
        msg_b = {"for": "b"}
        await manager.broadcast_to_user(USER_A, msg_a)
        await manager.broadcast_to_user(USER_B, msg_b)

        ws_a.send_json.assert_awaited_once_with(msg_a)
        ws_b.send_json.assert_awaited_once_with(msg_b)


@pytest.mark.integration
class TestWebSocketDisconnectHandling:
    """Verify cleanup on failed sends (simulated broken connections)."""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_broken_connection_removed_on_broadcast(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        healthy_ws = _make_ws()
        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = RuntimeError("connection closed")

        manager.add_connection(USER_A, healthy_ws)
        manager.add_connection(USER_A, broken_ws)

        message = {"type": "ping"}
        await manager.broadcast_to_user(USER_A, message)

        # Healthy socket received the message
        healthy_ws.send_json.assert_awaited_once_with(message)

        # Broken socket was discarded from the connections set
        assert broken_ws not in manager.connections[USER_A]
        assert healthy_ws in manager.connections[USER_A]

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_all_connections_broken_cleans_up_set(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """When every connection for a user fails, the set should be empty
        (the user key remains with an empty set since broadcast_to_user
        only discards individual sockets, not the key itself)."""
        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = ConnectionError("gone")

        manager.add_connection(USER_A, broken_ws)
        await manager.broadcast_to_user(USER_A, {"type": "test"})

        # The broken socket was removed
        assert broken_ws not in manager.connections.get(USER_A, set())

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_disconnect_no_memory_leak(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """Connect and disconnect many sockets; verify nothing is retained."""
        for _ in range(100):
            ws = _make_ws()
            manager.add_connection(USER_A, ws)
            manager.remove_connection(USER_A, ws)

        assert USER_A not in manager.connections


@pytest.mark.integration
class TestWebSocketConcurrentConnections:
    """Same user with multiple simultaneous client connections."""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_multiple_clients_all_receive_message(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """When one user has N connections, all N must receive each broadcast."""
        sockets = [_make_ws() for _ in range(5)]
        for ws in sockets:
            manager.add_connection(USER_A, ws)

        message = {"type": "sync", "version": 3}
        await manager.broadcast_to_user(USER_A, message)

        for ws in sockets:
            ws.send_json.assert_awaited_once_with(message)

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_closing_one_client_does_not_affect_others(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        ws3 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)
        manager.add_connection(USER_A, ws3)

        # Client 2 disconnects
        manager.remove_connection(USER_A, ws2)

        message = {"type": "update"}
        await manager.broadcast_to_user(USER_A, message)

        ws1.send_json.assert_awaited_once_with(message)
        ws3.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_not_awaited()


@pytest.mark.integration
class TestWebSocketRabbitMQFallback:
    """When not running as the main app, messages are published to RabbitMQ."""

    @patch("app.core.websocket_manager.is_main_app", return_value=False)
    @patch("app.core.websocket_manager.get_rabbitmq_publisher")
    async def test_non_main_app_publishes_to_rabbitmq(
        self,
        mock_get_publisher: AsyncMock,
        _mock_main: MagicMock,
        manager: WebSocketManager,
    ) -> None:
        mock_publisher = AsyncMock()
        mock_get_publisher.return_value = mock_publisher

        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        message = {"type": "notify", "data": "hi"}
        await manager.broadcast_to_user(USER_A, message)

        # WebSocket should NOT have been called directly
        ws.send_json.assert_not_awaited()

        # RabbitMQ publisher should have been invoked
        mock_get_publisher.assert_awaited_once()
        mock_publisher.publish.assert_awaited_once()

        # Verify the published payload shape
        call_args = mock_publisher.publish.call_args
        assert call_args[0][0] == "websocket-events"

    @patch("app.core.websocket_manager.is_main_app", return_value=False)
    @patch("app.core.websocket_manager.get_rabbitmq_publisher")
    async def test_rabbitmq_publish_failure_does_not_raise(
        self,
        mock_get_publisher: AsyncMock,
        _mock_main: MagicMock,
        manager: WebSocketManager,
    ) -> None:
        """If RabbitMQ publish fails, the error is logged but not propagated."""
        mock_get_publisher.side_effect = ConnectionError("RabbitMQ down")

        # Must not raise
        await manager.broadcast_to_user(USER_A, {"type": "test"})


@pytest.mark.integration
class TestWebSocketConsumerMessageHandling:
    """Tests for the WebSocketEventConsumer._handle_websocket_message logic,
    verifying that RabbitMQ messages are correctly dispatched to local sockets."""

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_consumer_dispatches_to_connected_user(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """Simulate what the consumer does: parse a RabbitMQ message and
        broadcast it through the manager's connections dict."""

        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        # Build a fake incoming RabbitMQ message
        payload = {
            "type": "websocket_broadcast",
            "user_id": USER_A,
            "message": {"type": "new_notification", "id": "n-123"},
        }
        fake_message = AsyncMock()
        fake_message.body = json.dumps(payload).encode("utf-8")
        fake_message.process = MagicMock()
        fake_message.process.return_value.__aenter__ = AsyncMock(return_value=None)
        fake_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        consumer = WebSocketEventConsumer()

        # Patch the global websocket_manager used inside the consumer module
        # to point to our test instance
        with patch("app.core.websocket_consumer.websocket_manager", manager):
            await consumer._handle_websocket_message(fake_message)

        ws.send_json.assert_awaited_once_with(
            {"type": "new_notification", "id": "n-123"}
        )

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_consumer_ignores_unknown_message_type(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:

        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        payload = {
            "type": "unknown_type",
            "user_id": USER_A,
            "message": {"data": "should not arrive"},
        }
        fake_message = AsyncMock()
        fake_message.body = json.dumps(payload).encode("utf-8")
        fake_message.process = MagicMock()
        fake_message.process.return_value.__aenter__ = AsyncMock(return_value=None)
        fake_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        consumer = WebSocketEventConsumer()
        with patch("app.core.websocket_consumer.websocket_manager", manager):
            await consumer._handle_websocket_message(fake_message)

        ws.send_json.assert_not_awaited()

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_consumer_handles_malformed_json(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:

        fake_message = AsyncMock()
        fake_message.body = b"not valid json{{"
        fake_message.process = MagicMock()
        fake_message.process.return_value.__aenter__ = AsyncMock(return_value=None)
        fake_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        consumer = WebSocketEventConsumer()
        with patch("app.core.websocket_consumer.websocket_manager", manager):
            # Must not raise
            await consumer._handle_websocket_message(fake_message)

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_consumer_handles_missing_fields(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """A broadcast message missing user_id or message should not raise."""

        payload = {"type": "websocket_broadcast"}  # missing user_id and message
        fake_message = AsyncMock()
        fake_message.body = json.dumps(payload).encode("utf-8")
        fake_message.process = MagicMock()
        fake_message.process.return_value.__aenter__ = AsyncMock(return_value=None)
        fake_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        consumer = WebSocketEventConsumer()
        with patch("app.core.websocket_consumer.websocket_manager", manager):
            await consumer._handle_websocket_message(fake_message)

    @patch("app.core.websocket_manager.is_main_app", return_value=True)
    async def test_consumer_removes_broken_socket_during_dispatch(
        self, _mock_main: MagicMock, manager: WebSocketManager
    ) -> None:
        """If a socket fails during consumer dispatch, it should be discarded."""

        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = RuntimeError("pipe broken")
        manager.add_connection(USER_A, broken_ws)

        payload = {
            "type": "websocket_broadcast",
            "user_id": USER_A,
            "message": {"type": "ping"},
        }
        fake_message = AsyncMock()
        fake_message.body = json.dumps(payload).encode("utf-8")
        fake_message.process = MagicMock()
        fake_message.process.return_value.__aenter__ = AsyncMock(return_value=None)
        fake_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        consumer = WebSocketEventConsumer()
        with patch("app.core.websocket_consumer.websocket_manager", manager):
            await consumer._handle_websocket_message(fake_message)

        assert broken_ws not in manager.connections.get(USER_A, set())


@pytest.mark.integration
class TestNotificationServiceWebSocketBridge:
    """NotificationService thin wrappers delegate to WebSocketManager."""

    def test_add_websocket_connection_delegates(
        self, manager: WebSocketManager
    ) -> None:

        svc = NotificationService()
        ws = _make_ws()

        with patch("app.services.notification_service.websocket_manager", manager):
            svc.add_websocket_connection(USER_A, ws)

        assert ws in manager.connections[USER_A]

    def test_remove_websocket_connection_delegates(
        self, manager: WebSocketManager
    ) -> None:

        svc = NotificationService()
        ws = _make_ws()

        with patch("app.services.notification_service.websocket_manager", manager):
            svc.add_websocket_connection(USER_A, ws)
            svc.remove_websocket_connection(USER_A, ws)

        assert USER_A not in manager.connections
