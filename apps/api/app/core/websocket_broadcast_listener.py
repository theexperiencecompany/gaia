"""One shared per-pod subscription that delivers user WebSocket broadcasts.

Every replica subscribes to ``WEBSOCKET_BROADCAST_CHANNEL`` and writes each
message to the sockets it happens to hold; replicas that hold none ignore it.
This is what makes a broadcast raised anywhere — another replica's request
handler, an ARQ worker, a scheduler — reach a user regardless of which replica
the load balancer parked their socket on.

It replaced a durable RabbitMQ queue that carried the same messages. A queue is
competing-consumers: with more than one replica each broadcast went to exactly
one of them, so a user connected to any other replica silently received nothing.
Nothing is lost by dropping the durability, because a broadcast is only ever
meaningful to a socket that is connected *now* — a message held for a replica
that is down would have no socket to land on when it came back.
"""

import asyncio
import contextlib
import json

from app.constants.log_tags import LogTag
from app.constants.websocket import (
    WEBSOCKET_BROADCAST_CHANNEL,
    WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS,
)
from app.core.websocket_manager import websocket_manager
from app.db.redis import redis_cache
from shared.py.wide_events import log, log_context

_listener_task: asyncio.Task[None] | None = None


async def _dispatch(raw: str) -> None:
    """Deliver one broadcast to this pod's sockets, as its own wide event.

    This runs outside any request, so without a boundary a drop here would be a
    silently missing push notification rather than a queryable event naming the
    reason.
    """
    async with log_context("websocket_broadcast"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning(
                f"{LogTag.STARTUP} Dropped malformed WebSocket broadcast",
                reason="json_decode",
                error=str(e),
                error_type=type(e).__name__,
                raw_length=len(raw),
            )
            return
        user_id = payload.get("user_id")
        message = payload.get("message")
        if not isinstance(user_id, str) or not isinstance(message, dict):
            log.warning(
                f"{LogTag.STARTUP} Dropped WebSocket broadcast missing user_id or message",
                reason="invalid_payload",
            )
            return
        log.set(user={"id": user_id})
        # Sockets reached on THIS pod; zero is normal and means the user is
        # connected elsewhere (or not at all), not that delivery failed.
        log.set(result_count=await websocket_manager.deliver_local(user_id, message))


async def _consume() -> None:
    """Subscribe once to the broadcast channel and fan messages to local sockets."""
    client = redis_cache.redis
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(WEBSOCKET_BROADCAST_CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode()
            await _dispatch(raw)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(WEBSOCKET_BROADCAST_CHANNEL)
            await pubsub.aclose()


async def _listener_loop() -> None:
    """One wide event per subscription lifetime, so a wedged listener is visible.

    The boundary is per attempt, not around the loop: it emits when a
    subscription ends, carrying how long it survived and why it dropped. One
    boundary around the whole loop would emit a single event at process exit.
    """
    if redis_cache.redis is None:
        async with log_context("websocket_broadcast_subscription"):
            log.error(f"{LogTag.STARTUP} WebSocket broadcast listener disabled (no Redis)")
        return
    while True:
        async with log_context("websocket_broadcast_subscription"):
            try:
                await _consume()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    f"{LogTag.STARTUP} WebSocket broadcast listener dropped, resubscribing",
                    error=str(e),
                    error_type=type(e).__name__,
                )
        await asyncio.sleep(WEBSOCKET_LISTENER_RESUBSCRIBE_SECONDS)


def start_websocket_broadcast_listener() -> None:
    """Start the shared per-pod broadcast listener (idempotent)."""
    global _listener_task
    if _listener_task is not None and not _listener_task.done():
        return
    _listener_task = asyncio.get_running_loop().create_task(_listener_loop())
    log.info(f"{LogTag.STARTUP} WebSocket broadcast listener started")


async def stop_websocket_broadcast_listener() -> None:
    """Cancel and await the broadcast listener."""
    global _listener_task
    if _listener_task is None:
        return
    _listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _listener_task
    _listener_task = None
    log.info(f"{LogTag.STARTUP} WebSocket broadcast listener stopped")
