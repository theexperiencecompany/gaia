"""Tests for WebSocketManager and the per-pod broadcast listener.

Covers:
- WebSocketManager: singleton, add/remove connections, publish-only broadcast,
  local delivery and dead-socket pruning.
- websocket_broadcast_listener: dispatch of valid payloads, malformed JSON,
  missing fields, users connected elsewhere, sockets that die mid-fan-out.
- The two multi-instance regressions, end to end over a real pub/sub round trip
  (fakeredis): exactly-once delivery on the publishing replica, and delivery of
  a broadcast this replica did not originate.
"""

import asyncio
from contextlib import asynccontextmanager
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.constants.log_tags import LogTag
from app.constants.websocket import (
    WEBSOCKET_BROADCAST_CHANNEL,
    WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS,
)
from app.core import websocket_broadcast_listener as listener
from app.core.websocket_manager import (
    WebSocketBroadcastError,
    WebSocketManager,
    get_websocket_manager,
    websocket_manager,
)
from app.db.redis import redis_cache


@pytest.fixture
async def fake_redis():
    """Point redis_cache at an in-process Redis with real pub/sub semantics."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    original = redis_cache.redis
    redis_cache.redis = client
    yield client
    redis_cache.redis = original
    await client.aclose()


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
# WebSocketManager — broadcast_to_user publishes, and only publishes
# ---------------------------------------------------------------------------


class TestBroadcastToUser:
    def setup_method(self) -> None:
        WebSocketManager._instance = None
        self.mgr = WebSocketManager()

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    async def test_publishes_payload_to_the_broadcast_channel(self, fake_redis) -> None:
        pubsub = fake_redis.pubsub()
        await pubsub.subscribe(WEBSOCKET_BROADCAST_CHANNEL)

        message: dict[str, Any] = {"type": "notification", "text": "hello"}
        await self.mgr.broadcast_to_user("user1", message)

        received = None
        for _ in range(5):
            frame = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if frame and frame.get("type") == "message":
                received = json.loads(frame["data"])
                break
        await pubsub.aclose()

        assert received == {"user_id": "user1", "message": message}

    async def test_does_not_write_to_local_sockets(self, fake_redis) -> None:
        """The listener owns delivery. A direct write here is the double-send bug."""
        ws = AsyncMock()
        self.mgr.add_connection("user1", ws)

        await self.mgr.broadcast_to_user("user1", {"type": "test"})

        ws.send_json.assert_not_awaited()

    async def test_raises_when_redis_is_unavailable(self) -> None:
        original = redis_cache.redis
        redis_cache.redis = None
        try:
            with pytest.raises(WebSocketBroadcastError) as exc:
                await self.mgr.broadcast_to_user("user1", {"type": "test"})
            assert str(exc.value) == (
                "Redis is not configured; WebSocket broadcasts cannot be delivered"
            )
        finally:
            redis_cache.redis = original


# ---------------------------------------------------------------------------
# WebSocketManager — deliver_local
# ---------------------------------------------------------------------------


class TestDeliverLocal:
    def setup_method(self) -> None:
        WebSocketManager._instance = None
        self.mgr = WebSocketManager()

    def teardown_method(self) -> None:
        WebSocketManager._instance = None

    async def test_delivers_to_all_user_connections(self) -> None:
        ws1, ws2 = AsyncMock(), AsyncMock()
        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        message = {"type": "notification", "text": "hello"}
        reached = await self.mgr.deliver_local("user1", message)

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)
        assert reached == 2

    async def test_user_not_connected_here_reaches_nobody(self) -> None:
        assert await self.mgr.deliver_local("nobody", {"type": "test"}) == 0

    async def test_removes_disconnected_sockets_on_send_failure(self) -> None:
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("connection closed")

        self.mgr.add_connection("user1", ws_good)
        self.mgr.add_connection("user1", ws_bad)

        reached = await self.mgr.deliver_local("user1", {"type": "test"})

        ws_good.send_json.assert_awaited_once()
        assert ws_bad not in self.mgr.connections.get("user1", set())
        assert ws_good in self.mgr.connections["user1"]
        assert reached == 1

    async def test_all_sockets_failing_drops_the_user_entry(self) -> None:
        ws1, ws2 = AsyncMock(), AsyncMock()
        ws1.send_json.side_effect = RuntimeError("closed")
        ws2.send_json.side_effect = RuntimeError("closed")

        self.mgr.add_connection("user1", ws1)
        self.mgr.add_connection("user1", ws2)

        assert await self.mgr.deliver_local("user1", {"type": "test"}) == 0
        assert "user1" not in self.mgr.connections


# ---------------------------------------------------------------------------
# Broadcast listener — dispatch
# ---------------------------------------------------------------------------


class TestBroadcastDispatch:
    def setup_method(self) -> None:
        websocket_manager.connections.clear()

    def teardown_method(self) -> None:
        websocket_manager.connections.clear()

    async def test_delivers_a_valid_payload(self) -> None:
        ws = AsyncMock()
        websocket_manager.add_connection("user_x", ws)

        await listener._dispatch(
            json.dumps({"user_id": "user_x", "message": {"event": "new_todo"}})
        )

        ws.send_json.assert_awaited_once_with({"event": "new_todo"})

    async def test_ignores_malformed_json(self) -> None:
        await listener._dispatch("not-json{{")

    async def test_ignores_missing_user_id(self) -> None:
        await listener._dispatch(json.dumps({"message": {"event": "test"}}))

    async def test_ignores_missing_message(self) -> None:
        await listener._dispatch(json.dumps({"user_id": "user1"}))

    async def test_user_connected_elsewhere_is_not_an_error(self) -> None:
        await listener._dispatch(
            json.dumps({"user_id": "offline_user", "message": {"event": "test"}})
        )

    async def test_removes_sockets_that_die_mid_fanout(self) -> None:
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError("closed")
        websocket_manager.add_connection("user_y", ws_good)
        websocket_manager.add_connection("user_y", ws_bad)

        await listener._dispatch(json.dumps({"user_id": "user_y", "message": {"event": "test"}}))

        ws_good.send_json.assert_awaited_once()
        assert ws_bad not in websocket_manager.connections.get("user_y", set())


# ---------------------------------------------------------------------------
# Broadcast listener — lifecycle
# ---------------------------------------------------------------------------


class TestBroadcastListenerLifecycle:
    async def test_start_is_idempotent_and_stop_cancels(self, fake_redis) -> None:
        listener.start_websocket_broadcast_listener()
        first = listener._listener_task
        listener.start_websocket_broadcast_listener()
        assert listener._listener_task is first

        await listener.stop_websocket_broadcast_listener()
        assert listener._listener_task is None
        assert first is not None and first.cancelled()

    async def test_stop_without_start_is_a_noop(self) -> None:
        await listener.stop_websocket_broadcast_listener()
        assert listener._listener_task is None

    async def test_listener_exits_when_redis_is_unavailable(self) -> None:
        original = redis_cache.redis
        redis_cache.redis = None
        try:
            await asyncio.wait_for(listener._listener_loop(), timeout=1.0)
        finally:
            redis_cache.redis = original


# ---------------------------------------------------------------------------
# Multi-instance regressions — real publish/subscribe round trip
# ---------------------------------------------------------------------------


class TestMultiInstanceFanout:
    """The two bugs that only a real pub/sub round trip can catch.

    These drive the actual listener against a real (in-process) Redis rather
    than calling ``_dispatch`` directly — the double-send only exists in the
    interaction between publishing and this pod's own subscription.

    Unmarked despite being true regressions: the CI regression lane replays a
    marked test against base, and this module now imports
    ``websocket_broadcast_listener``, which does not exist there — the replay
    would error at collection rather than prove anything (tests/CLAUDE.md).
    """

    def setup_method(self) -> None:
        websocket_manager.connections.clear()

    def teardown_method(self) -> None:
        websocket_manager.connections.clear()

    async def _await_delivery(self, sock: AsyncMock, expected: int) -> None:
        """Wait until ``expected`` frames have landed, then a beat longer for extras."""
        for _ in range(40):
            if sock.send_json.await_count >= expected:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)

    async def test_publishing_replica_delivers_exactly_once(self, fake_redis) -> None:
        """The publisher must not write locally AND redeliver off its own subscription."""
        ws = AsyncMock()
        websocket_manager.add_connection("u1", ws)
        listener.start_websocket_broadcast_listener()
        await asyncio.sleep(0.3)
        try:
            await websocket_manager.broadcast_to_user("u1", {"type": "ping"})
            await self._await_delivery(ws, 1)
        finally:
            await listener.stop_websocket_broadcast_listener()

        assert ws.send_json.await_count == 1

    async def test_delivers_a_broadcast_this_replica_did_not_originate(self, fake_redis) -> None:
        """A worker (or another replica) publishes; this replica must still deliver.

        The old RabbitMQ queue was competing-consumers, so exactly one replica
        got each broadcast and every other replica's sockets were stranded.
        """
        ws = AsyncMock()
        websocket_manager.add_connection("u2", ws)
        listener.start_websocket_broadcast_listener()
        await asyncio.sleep(0.3)
        try:
            await fake_redis.publish(
                WEBSOCKET_BROADCAST_CHANNEL,
                json.dumps({"user_id": "u2", "message": {"type": "from_worker"}}),
            )
            await self._await_delivery(ws, 1)
        finally:
            await listener.stop_websocket_broadcast_listener()

        ws.send_json.assert_awaited_once_with({"type": "from_worker"})

    async def test_every_subscribed_replica_receives_the_same_broadcast(self, fake_redis) -> None:
        """Fan-out, not hand-off: two subscribers both get one publish.

        Stands in for two pods; the real two-process proof is the live
        two-replica run, not this.
        """
        subs = [fake_redis.pubsub() for _ in range(2)]
        for ps in subs:
            await ps.subscribe(WEBSOCKET_BROADCAST_CHANNEL)
        await asyncio.sleep(0.1)

        await websocket_manager.broadcast_to_user("u3", {"type": "fan"})

        received = []
        for ps in subs:
            for _ in range(5):
                frame = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if frame and frame.get("type") == "message":
                    received.append(json.loads(frame["data"]))
                    break
            await ps.aclose()

        assert len(received) == 2
        assert all(r["message"] == {"type": "fan"} for r in received)


# ---------------------------------------------------------------------------
# Every broadcast caller reaches the fan-out, regardless of process type
# ---------------------------------------------------------------------------


async def test_workers_publish_without_needing_to_be_the_main_app(fake_redis) -> None:
    """An ARQ worker holds no sockets; it must still be able to broadcast.

    Broadcasting used to branch on the process type and take a different
    transport in a worker. There is one path now — publish to the Redis channel —
    so a worker publishes exactly like a request handler does, no process-type
    check involved.
    """
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(WEBSOCKET_BROADCAST_CHANNEL)

    await websocket_manager.broadcast_to_user("u4", {"type": "from_arq"})

    received = None
    for _ in range(5):
        frame = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if frame and frame.get("type") == "message":
            received = json.loads(frame["data"])
            break
    await pubsub.aclose()

    assert received == {"user_id": "u4", "message": {"type": "from_arq"}}


# ---------------------------------------------------------------------------
# broadcast listener: _dispatch and _listener_loop
# ---------------------------------------------------------------------------

_MOD = "app.core.websocket_broadcast_listener"


@asynccontextmanager
async def _noop_log_context(*_a: Any, **_k: Any):
    yield


class TestBroadcastDispatchLogging:
    @staticmethod
    async def _run(raw: str, *, deliver_return: int = 0):
        fake_log = MagicMock()
        deliver = AsyncMock(return_value=deliver_return)
        with (
            patch(f"{_MOD}.log", fake_log),
            patch(f"{_MOD}.log_context", side_effect=_noop_log_context) as ctx,
            patch(f"{_MOD}.websocket_manager.deliver_local", deliver),
        ):
            await listener._dispatch(raw)
        return fake_log, ctx, deliver

    async def test_delivers_a_valid_broadcast_to_local_sockets(self):
        raw = json.dumps({"user_id": "u1", "message": {"type": "x"}})
        fake_log, ctx, deliver = await self._run(raw, deliver_return=3)

        deliver.assert_awaited_once_with("u1", {"type": "x"})
        ctx.assert_called_once_with("websocket_broadcast")
        fake_log.set.assert_any_call(user={"id": "u1"})
        fake_log.set.assert_any_call(result_count=3)

    async def test_drops_malformed_json_with_a_reason(self):
        try:
            json.loads("not-json")
        except json.JSONDecodeError as e:
            expected_error = str(e)

        fake_log, _ctx, deliver = await self._run("not-json")
        deliver.assert_not_awaited()
        fake_log.warning.assert_called_once_with(
            f"{LogTag.STARTUP} Dropped malformed WebSocket broadcast",
            reason="json_decode",
            error=expected_error,
            error_type="JSONDecodeError",
            raw_length=len("not-json"),
        )

    async def test_drops_payload_with_non_string_user_id(self):
        fake_log, _ctx, deliver = await self._run(json.dumps({"user_id": 1, "message": {}}))
        deliver.assert_not_awaited()
        fake_log.warning.assert_called_once_with(
            f"{LogTag.STARTUP} Dropped WebSocket broadcast missing user_id or message",
            reason="invalid_payload",
        )

    async def test_drops_payload_with_non_dict_message(self):
        # user_id is a valid str but message is not a dict — the `or` in the guard
        # must still drop it (an `and` would let it through).
        fake_log, _ctx, deliver = await self._run(json.dumps({"user_id": "u1", "message": "x"}))
        deliver.assert_not_awaited()
        fake_log.warning.assert_called_once_with(
            f"{LogTag.STARTUP} Dropped WebSocket broadcast missing user_id or message",
            reason="invalid_payload",
        )


class TestBroadcastListenerLoop:
    async def test_logs_and_returns_when_redis_is_absent(self):
        fake_log = MagicMock()
        with (
            patch(f"{_MOD}.log", fake_log),
            patch(f"{_MOD}.log_context", side_effect=_noop_log_context) as ctx,
            patch(f"{_MOD}.redis_cache") as rc,
        ):
            rc.redis = None
            await listener._listener_loop()
        fake_log.error.assert_called_once_with(
            f"{LogTag.STARTUP} WebSocket broadcast listener disabled (no Redis)"
        )
        ctx.assert_called_once_with("websocket_broadcast_subscription")

    async def test_resubscribes_and_logs_when_the_subscription_drops(self):
        fake_log = MagicMock()
        consume = AsyncMock(side_effect=RuntimeError("dropped"))
        # Break the otherwise-infinite loop on the first resubscribe sleep.
        sleep = AsyncMock(side_effect=asyncio.CancelledError)
        with (
            patch(f"{_MOD}.log", fake_log),
            patch(f"{_MOD}.log_context", side_effect=_noop_log_context) as ctx,
            patch(f"{_MOD}.redis_cache") as rc,
            patch(f"{_MOD}._consume", consume),
            patch(f"{_MOD}.asyncio.sleep", sleep),
        ):
            rc.redis = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await listener._listener_loop()

        fake_log.warning.assert_called_once_with(
            f"{LogTag.STARTUP} WebSocket broadcast listener dropped, resubscribing",
            error="dropped",
            error_type="RuntimeError",
        )
        sleep.assert_awaited_once_with(WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS)
        ctx.assert_any_call("websocket_broadcast_subscription")


class TestBroadcastConsume:
    @staticmethod
    def _client_with(pubsub):
        client = MagicMock()
        client.pubsub = MagicMock(return_value=pubsub)
        return client

    async def test_subscribes_decodes_dispatches_and_cleans_up(self):
        pubsub = AsyncMock()
        pubsub.get_message = AsyncMock(
            side_effect=[{"type": "message", "data": b'{"x":1}'}, asyncio.CancelledError()]
        )
        dispatch = AsyncMock()
        with (
            patch(f"{_MOD}.redis_cache") as rc,
            patch(f"{_MOD}._dispatch", dispatch),
        ):
            rc.redis = self._client_with(pubsub)
            with pytest.raises(asyncio.CancelledError):
                await listener._consume()

        pubsub.subscribe.assert_awaited_once_with(WEBSOCKET_BROADCAST_CHANNEL)
        pubsub.get_message.assert_awaited_with(ignore_subscribe_messages=True, timeout=1.0)
        dispatch.assert_awaited_once_with('{"x":1}')  # bytes decoded to str
        pubsub.unsubscribe.assert_awaited_once_with(WEBSOCKET_BROADCAST_CHANNEL)
        pubsub.aclose.assert_awaited_once()

    async def test_teardown_errors_do_not_mask_the_loop_exit(self):
        pubsub = AsyncMock()
        pubsub.get_message = AsyncMock(side_effect=asyncio.CancelledError())
        pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("redis gone"))
        with patch(f"{_MOD}.redis_cache") as rc:
            rc.redis = self._client_with(pubsub)
            with pytest.raises(asyncio.CancelledError):
                await listener._consume()
