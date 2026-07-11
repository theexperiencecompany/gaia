"""One shared per-pod subscription to the device-revoke channel.

Revocation is rare and fans out on a single global channel, so a subscription
per connected device (each holding its own Redis connection to watch the same
channel) is pure overhead — N connections and O(N) delivery to enforce one
event. This listener subscribes once per pod and closes the locally-held socket
when its device is revoked; pods that don't own the device simply ignore it.

Because it is now the sole enforcement point for the whole pod, the listener
re-subscribes on a dropped connection instead of dying silently.
"""

import asyncio
import contextlib
import json

from app.constants.device_bridge import (
    DEVICE_LISTENER_RESUBSCRIBE_SECONDS,
    DEVICE_REVOKE_CHANNEL,
    FRAME_REVOKE,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.device.connection_manager import device_connection_manager
from shared.py.wide_events import log

_listener_task: asyncio.Task[None] | None = None


async def _dispatch_revoke(device_id: str) -> None:
    """Close this device's socket if the revoke lands on the pod that owns it.

    Send the revoke frame first so the daemon exits cleanly via its FRAME_REVOKE
    handler, instead of reconnect-looping against a now-dead refresh credential.
    """
    websocket = device_connection_manager.get(device_id)
    if websocket is None:
        return
    log.info(f"{LogTag.API} Closing revoked device socket", device_id=device_id)
    with contextlib.suppress(Exception):
        await websocket.send_text(json.dumps({"t": FRAME_REVOKE}))
    with contextlib.suppress(Exception):
        await websocket.close(code=1008)


async def _consume() -> None:
    """Subscribe once and dispatch revokes until the connection drops."""
    client = redis_cache.redis
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(DEVICE_REVOKE_CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            await _dispatch_revoke(data)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(DEVICE_REVOKE_CHANNEL)
            await pubsub.aclose()


async def _listener_loop() -> None:
    if not redis_cache.redis:
        log.warning(f"{LogTag.API} Device revoke listener disabled (no Redis connection)")
        return
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"{LogTag.API} Device revoke listener dropped, resubscribing: {e}")
        await asyncio.sleep(DEVICE_LISTENER_RESUBSCRIBE_SECONDS)


def start_revoke_listener() -> None:
    """Start the shared per-pod device-revoke listener (idempotent)."""
    global _listener_task
    if _listener_task is not None and not _listener_task.done():
        return
    _listener_task = asyncio.get_running_loop().create_task(_listener_loop())
    log.info(f"{LogTag.API} Device revoke listener started")


async def stop_revoke_listener() -> None:
    """Cancel and await the revoke listener."""
    global _listener_task
    if _listener_task is None:
        return
    _listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _listener_task
    _listener_task = None
