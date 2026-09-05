"""The device tunnel WebSocket: one outbound socket per paired machine.

The daemon dials in with a short-lived device connect JWT (Authorization header,
subprotocol fallback). While connected, this pod:
  * relays downstream frames (from any worker, via Redis) into the socket,
  * publishes upstream frames (from the socket) onto per-session Redis channels,
  * heartbeats the socket and refreshes the device's presence key.

Revocation is enforced out-of-band by a single shared per-pod listener
(``device.revoke_listener``) that closes this socket when the device is revoked.
"""

import asyncio
import contextlib
import json
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.constants.device_bridge import (
    DEVICE_HEARTBEAT_INTERVAL_SECONDS,
    DEVICE_HEARTBEAT_TIMEOUT_SECONDS,
    FRAME_MCP_ERROR,
    FRAME_MCP_MSG,
    FRAME_MCP_OPENED,
    FRAME_PING,
    FRAME_PONG,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.device.bridge import (
    down_channel,
    mark_offline,
    mark_online,
    publish_disconnect,
    publish_up_to_pod,
)
from app.services.device.connection_manager import device_connection_manager
from app.services.device.device_auth import verify_device_token
from app.services.device.device_service import get_active_device
from shared.py.wide_events import log

router = APIRouter(prefix="/ws", tags=["Device Bridge"])


def _extract_token(websocket: WebSocket) -> str | None:
    auth = websocket.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    protocol_header = websocket.headers.get("sec-websocket-protocol", "")
    if protocol_header.startswith("Bearer, "):
        return protocol_header[8:]
    return None


@router.websocket("/device")
async def device_ws(websocket: WebSocket) -> None:
    """Device tunnel socket: authenticate the daemon, then relay MCP frames both ways.

    WebSocketWideEventMiddleware emits the connection's wide event — one
    ``ws_connection`` line per connection lifetime, covering auth rejections
    too — so this handler just calls ``log.set()`` like an HTTP handler.
    """
    token = _extract_token(websocket)
    info = verify_device_token(token) if token else None
    if not info:
        log.set(disconnect_reason="auth_failure")
        await websocket.close(code=1008)
        return

    device_id = info["device_id"]
    user_id = info["user_id"]
    log.set(device={"id": device_id}, user={"id": user_id})

    # A revoked/deleted device must not be able to reconnect on a still-valid JWT.
    if await get_active_device(device_id) is None:
        log.set(disconnect_reason="device_revoked")
        await websocket.close(code=1008)
        return

    uses_subprotocol = websocket.headers.get("sec-websocket-protocol", "").startswith("Bearer, ")
    await websocket.accept(subprotocol="Bearer" if uses_subprotocol else None)

    device_connection_manager.add(device_id, websocket)
    # last_seen_at was just written by the token exchange (rotate_refresh_token)
    # that immediately precedes every dial; presence lives in Redis, so no
    # second Postgres write here.
    await mark_online(device_id)

    state = {"last_recv": time.monotonic()}
    tasks = [
        asyncio.create_task(_down_relay(websocket, device_id)),
        asyncio.create_task(_heartbeat(websocket, device_id, state)),
    ]
    try:
        await _receive_loop(websocket, device_id, state)
    # evlog-map-disable-next-line error-handling -- normal websocket disconnect; info-level is correct
    except WebSocketDisconnect:
        log.set(disconnect_reason="client_close")
        log.info(f"{LogTag.API} Device disconnected", device_id=device_id)
    except Exception as e:
        log.set(disconnect_reason="server_error")
        log.warning(
            f"{LogTag.API} Device socket error",
            device_id=device_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        device_connection_manager.remove(device_id, websocket)
        # Fail any in-flight MCP session tunneling through this device. The daemon
        # drops its side of every session when the socket closes, so a parked
        # call would otherwise hang until the tunnel's call timeout. Fans out
        # cross-pod; the up-listener on each consumer pod injects the mcp.error.
        await publish_disconnect(device_id)
        # Only clear presence if this pod no longer holds any socket for the
        # device. Without this, an old socket's teardown would wipe the presence
        # key a newer same-pod socket just re-claimed (the compare-and-delete in
        # mark_offline keys only on POD_ID and can't tell them apart), flipping a
        # live device offline until its next heartbeat.
        if not device_connection_manager.owns(device_id):
            await mark_offline(device_id)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _receive_loop(websocket: WebSocket, device_id: str, state: dict[str, float]) -> None:
    """Read frames off the socket and route upstream ones onto Redis."""
    while True:
        raw = await websocket.receive_text()
        state["last_recv"] = time.monotonic()
        try:
            frame: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"{LogTag.API} Device sent malformed frame", device_id=device_id)
            continue

        frame_type = frame.get("t")
        if frame_type == FRAME_PONG:
            # Liveness is tracked by state["last_recv"] above; presence is
            # refreshed by the 30s heartbeat — no need to write it per pong.
            continue
        if frame_type in (FRAME_MCP_MSG, FRAME_MCP_OPENED, FRAME_MCP_ERROR):
            # The daemon echoes the consumer pod id (from mcp.open) on every up
            # frame; route the reply to that pod's shared up-channel, where the
            # up-listener dispatches by "sid". No per-session subscription.
            pod = frame.get("pod")
            if isinstance(pod, str):
                await publish_up_to_pod(pod, raw)
            continue
        # FRAME_HELLO and unknown types are informational; ignore quietly.


async def _down_relay(websocket: WebSocket, device_id: str) -> None:
    """Subscribe to this device's down channel and write frames to the socket."""
    if not redis_cache.redis:
        return
    pubsub = redis_cache.redis.pubsub()
    await pubsub.subscribe(down_channel(device_id))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            await websocket.send_text(data)
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(down_channel(device_id))
            await pubsub.aclose()


async def _heartbeat(websocket: WebSocket, device_id: str, state: dict[str, float]) -> None:
    """Ping periodically; refresh presence; drop the socket if it goes silent."""
    while True:
        await asyncio.sleep(DEVICE_HEARTBEAT_INTERVAL_SECONDS)
        if time.monotonic() - state["last_recv"] > DEVICE_HEARTBEAT_TIMEOUT_SECONDS:
            log.warning(f"{LogTag.API} Device heartbeat timed out", device_id=device_id)
            with contextlib.suppress(Exception):
                await websocket.close(code=1001)
            return
        await mark_online(device_id)
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps({"t": FRAME_PING}))
