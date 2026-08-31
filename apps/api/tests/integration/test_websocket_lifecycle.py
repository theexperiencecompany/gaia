"""
TEST 8: WebSocket Connection Lifecycle

Integration tests for the WebSocketManager and the broadcast fan-out —
connection registration, removal, message routing, multi-user isolation,
concurrent connections, and error handling.

Tests exercise the real WebSocketManager and the real per-pod listener with
mock WebSocket objects at the I/O boundary.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.constants.websocket import WEBSOCKET_BROADCAST_CHANNEL
from app.core import websocket_broadcast_listener as listener
from app.core.websocket_manager import WebSocketManager
from app.db.redis import redis_cache

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


@pytest.fixture
async def fake_redis():
    """Point redis_cache at an in-process Redis with real pub/sub semantics."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis_cache.redis
    redis_cache.redis = client
    yield client
    redis_cache.redis = original
    await client.aclose()


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

    def test_remove_connection_deregisters_user(self, manager: WebSocketManager) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)
        manager.remove_connection(USER_A, ws)

        # User key should be cleaned up entirely when last connection is removed
        assert USER_A not in manager.connections

    def test_remove_nonexistent_connection_is_noop(self, manager: WebSocketManager) -> None:
        """Removing a connection that was never added must not raise."""
        ws = _make_ws()
        manager.remove_connection("ghost-user", ws)
        assert "ghost-user" not in manager.connections

    def test_add_multiple_connections_same_user(self, manager: WebSocketManager) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)

        assert len(manager.connections[USER_A]) == 2
        assert ws1 in manager.connections[USER_A]
        assert ws2 in manager.connections[USER_A]

    def test_remove_one_of_multiple_connections(self, manager: WebSocketManager) -> None:
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

    def test_connection_count_after_add_remove_cycles(self, manager: WebSocketManager) -> None:
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

    def test_multiple_users_tracked_independently(self, manager: WebSocketManager) -> None:
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

    async def test_broadcast_to_user_delivers_message(self, manager: WebSocketManager) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        message: dict[str, Any] = {"type": "notification", "body": "hello"}
        await manager.deliver_local(USER_A, message)

        ws.send_json.assert_awaited_once_with(message)

    async def test_broadcast_to_nonexistent_user_is_noop(self, manager: WebSocketManager) -> None:
        """Sending to a user with no connections must not raise."""
        await manager.deliver_local("nobody", {"type": "test"})
        # No assertion needed — just verifying no exception

    async def test_broadcast_delivers_to_all_connections_of_user(
        self, manager: WebSocketManager
    ) -> None:
        ws1 = _make_ws()
        ws2 = _make_ws()
        manager.add_connection(USER_A, ws1)
        manager.add_connection(USER_A, ws2)

        message = {"type": "update", "data": 42}
        await manager.deliver_local(USER_A, message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)


@pytest.mark.integration
class TestWebSocketMultiUserIsolation:
    """Messages for user A must never reach user B."""

    async def test_user_b_does_not_receive_user_a_message(self, manager: WebSocketManager) -> None:
        ws_a = _make_ws()
        ws_b = _make_ws()
        manager.add_connection(USER_A, ws_a)
        manager.add_connection(USER_B, ws_b)

        await manager.deliver_local(USER_A, {"type": "secret"})

        ws_a.send_json.assert_awaited_once()
        ws_b.send_json.assert_not_awaited()

    async def test_each_user_receives_own_messages_only(self, manager: WebSocketManager) -> None:
        ws_a = _make_ws()
        ws_b = _make_ws()
        manager.add_connection(USER_A, ws_a)
        manager.add_connection(USER_B, ws_b)

        msg_a = {"for": "a"}
        msg_b = {"for": "b"}
        await manager.deliver_local(USER_A, msg_a)
        await manager.deliver_local(USER_B, msg_b)

        ws_a.send_json.assert_awaited_once_with(msg_a)
        ws_b.send_json.assert_awaited_once_with(msg_b)


@pytest.mark.integration
class TestWebSocketDisconnectHandling:
    """Verify cleanup on failed sends (simulated broken connections)."""

    async def test_broken_connection_removed_on_broadcast(self, manager: WebSocketManager) -> None:
        healthy_ws = _make_ws()
        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = RuntimeError("connection closed")

        manager.add_connection(USER_A, healthy_ws)
        manager.add_connection(USER_A, broken_ws)

        message = {"type": "ping"}
        await manager.deliver_local(USER_A, message)

        # Healthy socket received the message
        healthy_ws.send_json.assert_awaited_once_with(message)

        # Broken socket was discarded from the connections set
        assert broken_ws not in manager.connections[USER_A]
        assert healthy_ws in manager.connections[USER_A]

    async def test_all_connections_broken_cleans_up_set(self, manager: WebSocketManager) -> None:
        """When every connection for a user fails, the user entry is dropped."""
        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = ConnectionError("gone")

        manager.add_connection(USER_A, broken_ws)
        await manager.deliver_local(USER_A, {"type": "test"})

        # The broken socket was removed
        assert broken_ws not in manager.connections.get(USER_A, set())

    async def test_disconnect_no_memory_leak(self, manager: WebSocketManager) -> None:
        """Connect and disconnect many sockets; verify nothing is retained."""
        for _ in range(100):
            ws = _make_ws()
            manager.add_connection(USER_A, ws)
            manager.remove_connection(USER_A, ws)

        assert USER_A not in manager.connections


@pytest.mark.integration
class TestWebSocketConcurrentConnections:
    """Same user with multiple simultaneous client connections."""

    async def test_multiple_clients_all_receive_message(self, manager: WebSocketManager) -> None:
        """When one user has N connections, all N must receive each broadcast."""
        sockets = [_make_ws() for _ in range(5)]
        for ws in sockets:
            manager.add_connection(USER_A, ws)

        message = {"type": "sync", "version": 3}
        await manager.deliver_local(USER_A, message)

        for ws in sockets:
            ws.send_json.assert_awaited_once_with(message)

    async def test_closing_one_client_does_not_affect_others(
        self, manager: WebSocketManager
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
        await manager.deliver_local(USER_A, message)

        ws1.send_json.assert_awaited_once_with(message)
        ws3.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_not_awaited()


@pytest.mark.integration
class TestWebSocketBroadcastFanout:
    """Publishing and delivery are separate steps, wired by the listener."""

    async def test_broadcast_publishes_and_does_not_write_locally(
        self, manager: WebSocketManager, fake_redis
    ) -> None:
        """Any process can broadcast; none of them writes to its own sockets."""
        ws = _make_ws()
        manager.add_connection(USER_A, ws)
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(WEBSOCKET_BROADCAST_CHANNEL)

        message = {"type": "notify", "data": "hi"}
        await manager.broadcast_to_user(USER_A, message)

        ws.send_json.assert_not_awaited()

        received = None
        for _ in range(5):
            frame = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if frame and frame.get("type") == "message":
                received = json.loads(frame["data"])
                break
        await pubsub.aclose()
        assert received == {"user_id": USER_A, "message": message}

    async def test_listener_delivers_a_published_broadcast(
        self, manager: WebSocketManager, fake_redis
    ) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)

        with patch.object(listener, "websocket_manager", manager):
            listener.start_websocket_broadcast_listener()
            await asyncio.sleep(0.3)
            try:
                await manager.broadcast_to_user(USER_A, {"type": "new_notification", "id": "n-123"})
                for _ in range(40):
                    if ws.send_json.await_count:
                        break
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.3)
            finally:
                await listener.stop_websocket_broadcast_listener()

        ws.send_json.assert_awaited_once_with({"type": "new_notification", "id": "n-123"})

    async def test_listener_ignores_malformed_and_incomplete_payloads(
        self, manager: WebSocketManager
    ) -> None:
        ws = _make_ws()
        manager.add_connection(USER_A, ws)
        with patch.object(listener, "websocket_manager", manager):
            await listener._dispatch("not-json{{")
            await listener._dispatch(json.dumps({"user_id": USER_A}))
            await listener._dispatch(json.dumps({"message": {"type": "x"}}))
        ws.send_json.assert_not_awaited()

    async def test_listener_drops_a_socket_that_breaks_mid_dispatch(
        self, manager: WebSocketManager
    ) -> None:
        healthy_ws = _make_ws()
        broken_ws = _make_ws()
        broken_ws.send_json.side_effect = RuntimeError("connection closed")
        manager.add_connection(USER_A, healthy_ws)
        manager.add_connection(USER_A, broken_ws)

        with patch.object(listener, "websocket_manager", manager):
            await listener._dispatch(json.dumps({"user_id": USER_A, "message": {"type": "ping"}}))

        healthy_ws.send_json.assert_awaited_once()
        assert broken_ws not in manager.connections.get(USER_A, set())
