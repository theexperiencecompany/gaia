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

from app.constants.device_bridge import (
    DEVICE_DISCONNECT_CHANNEL,
    DEVICE_LISTENER_RESUBSCRIBE_SECONDS,
    FRAME_MCP_ERROR,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.device.bridge import POD_ID, up_pod_channel
from shared.py.wide_events import log, log_context

Frame = dict[str, Any]

# session_id -> that session's inbox. The owning connector creates and drains it.
_inboxes: dict[str, asyncio.Queue[Frame]] = {}
# device_id -> its live session ids on this pod, so a device's socket teardown
# fails exactly the sessions tunneling through it.
_sessions_by_device: dict[str, set[str]] = {}
# session_id -> device_id, for O(1) reverse-index cleanup on unregister.
_session_devices: dict[str, str] = {}

_listener_task: asyncio.Task[None] | None = None


def register_up_session(session_id: str, device_id: str) -> asyncio.Queue[Frame]:
    """Create and register an inbox for a session; the connector drains it."""
    queue: asyncio.Queue[Frame] = asyncio.Queue()
    _inboxes[session_id] = queue
    _sessions_by_device.setdefault(device_id, set()).add(session_id)
    _session_devices[session_id] = device_id
    return queue


def unregister_up_session(session_id: str) -> None:
    _inboxes.pop(session_id, None)
    device_id = _session_devices.pop(session_id, None)
    if device_id is None:
        return
    sessions = _sessions_by_device.get(device_id)
    if sessions is not None:
        sessions.discard(session_id)
        if not sessions:
            del _sessions_by_device[device_id]


def fail_device_sessions(device_id: str, error: str) -> int:
    """Inject a synthetic mcp.error into every local session tunneling through a device.

    Returns the count notified. ``_drain_inbox`` turns the frame into a
    read-stream error, so an in-flight call fails at once instead of parking on
    ``inbox.get()`` until the tunnel's call timeout.
    """
    session_ids = _sessions_by_device.get(device_id)
    if not session_ids:
        return 0
    failed = 0
    for session_id in list(session_ids):
        queue = _inboxes.get(session_id)
        if queue is None:
            continue
        queue.put_nowait({"t": FRAME_MCP_ERROR, "sid": session_id, "error": error})
        failed += 1
    return failed


async def _dispatch(raw: str) -> None:
    """Route one up-frame to its session inbox, as its own wide event.

    Every drop here is an MCP call that will hang until it times out, so each
    frame gets a boundary and each drop reason is recorded on it — a dropped
    reply used to be indistinguishable from one that was never sent.
    """
    async with log_context("device_up_frame"):
        try:
            frame: Frame = json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning(
                f"{LogTag.API} Dropped malformed device up-frame",
                reason="json_decode",
                error=str(e),
                error_type=type(e).__name__,
                raw_length=len(raw),
            )
            return
        session_id = frame.get("sid")
        if not isinstance(session_id, str):
            log.warning(
                f"{LogTag.API} Dropped device up-frame without a session id", reason="no_sid"
            )
            return
        log.set(device={"session_id": session_id})
        queue = _inboxes.get(session_id)
        if queue is None:
            log.warning(
                f"{LogTag.API} Dropped device up-frame for an unknown session",
                reason="unknown_session",
                session_id=session_id,
            )
            return
        queue.put_nowait(frame)


async def _handle_disconnect(device_id: str) -> None:
    """Fail every local session tunneling through a device whose socket dropped.

    Own boundary per disconnect so a stall shows which device dropped and how
    many parked calls it unblocked; a pod that holds no session for the device
    records zero and moves on.
    """
    async with log_context("device_disconnect", device={"id": device_id}):
        failed = fail_device_sessions(device_id, "device disconnected")
        log.set_ns("device", sessions_failed=failed)
        if failed:
            log.info(f"{LogTag.API} Failed in-flight device sessions on disconnect")


async def _consume() -> None:
    """Subscribe once to this pod's up-channel plus the disconnect fan-out.

    Both channels feed the session inboxes — up-frames route replies by ``sid``,
    a disconnect fails every session on the named device — so one subscription
    serves both rather than a second per-pod Redis connection.
    """
    client = redis_cache.redis
    if client is None:
        return
    pubsub = client.pubsub()
    await pubsub.subscribe(up_pod_channel(POD_ID), DEVICE_DISCONNECT_CHANNEL)
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            channel = message.get("channel")
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")
            raw = message["data"]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if channel == DEVICE_DISCONNECT_CHANNEL:
                await _handle_disconnect(raw)
            else:
                await _dispatch(raw)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(up_pod_channel(POD_ID), DEVICE_DISCONNECT_CHANNEL)
            await pubsub.aclose()


async def _listener_loop() -> None:
    """One wide event per subscription lifetime, so a wedged listener is visible.

    The boundary is per attempt, not around the loop: it emits when the
    subscription ends, carrying how long it survived and why it dropped. One
    boundary around the whole loop would emit a single event at process exit.
    """
    if not redis_cache.redis:
        async with log_context("device_up_subscription"):
            log.warning(f"{LogTag.API} Device up-listener disabled (no Redis connection)")
        return
    while True:
        async with log_context("device_up_subscription"):
            try:
                await _consume()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning(
                    f"{LogTag.API} Device up-listener dropped, resubscribing",
                    error=str(e),
                    error_type=type(e).__name__,
                )
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
