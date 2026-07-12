"""One shared per-pod subscription for device up-frames (MCP replies from devices).

A worker running an MCP session over a paired device used to hold one Redis
pub/sub subscription per session — one dedicated Redis connection per concurrent
session, the axis that scales with agent activity and hits Redis ``maxclients``
first. Instead, each pod subscribes ONCE to its own up-channel
(``device:up:pod:<POD_ID>``). The device's owning pod addresses each reply frame
to the consumer pod (the daemon echoes the ``pod`` id it received on ``mcp.open``),
and this listener dispatches by ``sid`` to the waiting connector's in-memory inbox.

Per-session ordering and isolation are preserved by giving each session its own
inbox queue, drained by its own task: a slow or wedged session backs up only its
own queue and never stalls the shared listener or other sessions.
"""

import asyncio
import contextlib
import json
from typing import Any

from app.constants.device_bridge import DEVICE_LISTENER_RESUBSCRIBE_SECONDS
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.device.bridge import POD_ID, up_pod_channel
from shared.py.wide_events import log

Frame = dict[str, Any]

# session_id -> that session's inbox. The owning connector creates and drains it.
_inboxes: dict[str, asyncio.Queue[Frame]] = {}

_listener_task: asyncio.Task[None] | None = None


def register_up_session(session_id: str) -> asyncio.Queue[Frame]:
    """Create and register an inbox for a session; the connector drains it."""
    queue: asyncio.Queue[Frame] = asyncio.Queue()
    _inboxes[session_id] = queue
    return queue


def unregister_up_session(session_id: str) -> None:
    _inboxes.pop(session_id, None)


def _dispatch(session_id: str, frame: Frame) -> None:
    queue = _inboxes.get(session_id)
    if queue is not None:
        queue.put_nowait(frame)


async def _consume() -> None:
    """Subscribe once to this pod's up-channel and fan frames to session inboxes."""
    client = redis_cache.redis
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(up_pod_channel(POD_ID))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            try:
                frame: Frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            session_id = frame.get("sid")
            if isinstance(session_id, str):
                _dispatch(session_id, frame)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(up_pod_channel(POD_ID))
            await pubsub.aclose()


async def _listener_loop() -> None:
    if not redis_cache.redis:
        log.warning(f"{LogTag.API} Device up-listener disabled (no Redis connection)")
        return
    while True:
        try:
            await _consume()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"{LogTag.API} Device up-listener dropped, resubscribing: {e}")
        await asyncio.sleep(DEVICE_LISTENER_RESUBSCRIBE_SECONDS)


def start_up_listener() -> None:
    """Start the shared per-pod up-frame listener (idempotent)."""
    global _listener_task
    if _listener_task is not None and not _listener_task.done():
        return
    _listener_task = asyncio.get_running_loop().create_task(_listener_loop())
    log.info(f"{LogTag.API} Device up-listener started")


async def stop_up_listener() -> None:
    """Cancel and await the up-frame listener."""
    global _listener_task
    if _listener_task is None:
        return
    _listener_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _listener_task
    _listener_task = None
