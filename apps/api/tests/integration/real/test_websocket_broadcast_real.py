"""WebSocket broadcast delivery across replicas, against real Redis.

Only real Redis proves this. The property is about Redis pub/sub's *delivery
shape*, and the two bugs on either side of it are opposites:

- A durable queue (the RabbitMQ predecessor) is competing-consumers: with N
  replicas each broadcast reached exactly ONE of them, so a user parked on any
  other replica silently received nothing. ``test_every_replica_receives_it``
  pins the fan-out that replaced it.
- Delivering locally *and* publishing means the publishing replica writes to its
  own sockets twice — once directly, once off its own subscription. Every other
  replica still sees one. ``test_broadcast_writes_nothing_locally`` pins the
  publish-only rule that prevents it; the asymmetry is what made it survive
  review, because a two-replica smoke test only shows it on one side.

A fake mocking either half would assert nothing about Redis, which is where both
behaviours actually live.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.constants.websocket import WEBSOCKET_BROADCAST_CHANNEL
from app.core.websocket_broadcast_listener import _dispatch
from app.core.websocket_manager import WebSocketBroadcastError, websocket_manager
from app.db.redis import redis_cache

USER = "ws_fanout_user"


class RecordingSocket:
    """Stands in for a connected client; records every frame written to it."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_json(self, message: dict[str, Any]) -> None:
        self.frames.append(message)


@pytest.fixture
def sockets(real_redis):
    """Two sockets for one user on this replica, torn off the singleton after."""
    a, b = RecordingSocket(), RecordingSocket()
    # RecordingSocket duck-types the only WebSocket method the manager calls
    # (send_json); mypy can't see a fake as structurally sufficient here.
    websocket_manager.connections[USER] = {a, b}  # type: ignore[dict-item]  # test double, not a real WebSocket
    yield a, b
    websocket_manager.connections.pop(USER, None)


async def _published_payload(client) -> str:
    """Subscribe, run one real broadcast, return exactly what went on the wire."""
    pubsub = client.pubsub()
    await pubsub.subscribe(WEBSOCKET_BROADCAST_CHANNEL)
    try:
        await websocket_manager.broadcast_to_user(USER, {"type": "probe", "n": 1})
        deadline = asyncio.get_running_loop().time() + 5
        while asyncio.get_running_loop().time() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("type") == "message":
                raw = message["data"]
                return raw.decode() if isinstance(raw, bytes) else raw
        raise AssertionError("broadcast never reached the channel")
    finally:
        await pubsub.unsubscribe(WEBSOCKET_BROADCAST_CHANNEL)
        await pubsub.aclose()


@pytest.mark.asyncio
async def test_broadcast_writes_nothing_locally(real_redis, sockets) -> None:
    """The publishing replica must not touch its own sockets.

    Its listener will deliver the message like everyone else's; writing here too
    is what makes the publisher — and only the publisher — deliver twice.
    """
    a, b = sockets

    await websocket_manager.broadcast_to_user(USER, {"type": "probe", "n": 1})

    assert a.frames == []
    assert b.frames == []


@pytest.mark.asyncio
async def test_each_local_socket_receives_exactly_one_copy(real_redis, sockets) -> None:
    """One broadcast, one frame per socket — through the real published payload."""
    a, b = sockets

    await _dispatch(await _published_payload(real_redis))

    assert a.frames == [{"type": "probe", "n": 1}]
    assert b.frames == [{"type": "probe", "n": 1}]


@pytest.mark.asyncio
async def test_every_replica_receives_it(real_redis) -> None:
    """Fan-out, not competing-consumers: N subscribers each get the message.

    Two independent subscriptions stand in for two replicas' listeners. Under
    the old queue exactly one of them would have seen it.
    """
    first, second = real_redis.pubsub(), real_redis.pubsub()
    await first.subscribe(WEBSOCKET_BROADCAST_CHANNEL)
    await second.subscribe(WEBSOCKET_BROADCAST_CHANNEL)
    try:
        await websocket_manager.broadcast_to_user(USER, {"type": "probe", "n": 2})

        received = []
        for pubsub in (first, second):
            deadline = asyncio.get_running_loop().time() + 5
            while asyncio.get_running_loop().time() < deadline:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    raw = message["data"]
                    received.append(json.loads(raw.decode() if isinstance(raw, bytes) else raw))
                    break

        assert len(received) == 2
        assert all(r["message"] == {"type": "probe", "n": 2} for r in received)
        assert all(r["user_id"] == USER for r in received)
    finally:
        for pubsub in (first, second):
            await pubsub.unsubscribe(WEBSOCKET_BROADCAST_CHANNEL)
            await pubsub.aclose()


@pytest.mark.asyncio
async def test_a_replica_holding_no_socket_delivers_nothing(real_redis) -> None:
    """Zero local sockets is the normal case on most replicas, not a failure."""
    payload = json.dumps({"user_id": "nobody_here", "message": {"type": "probe"}})

    await _dispatch(payload)  # must not raise

    assert "nobody_here" not in websocket_manager.connections


@pytest.mark.asyncio
async def test_broadcast_fails_loud_without_redis(real_redis, monkeypatch, sockets) -> None:
    """No Redis means no delivery anywhere — surface it instead of dropping it."""
    monkeypatch.setattr(redis_cache, "redis", None)

    with pytest.raises(WebSocketBroadcastError):
        await websocket_manager.broadcast_to_user(USER, {"type": "probe"})
