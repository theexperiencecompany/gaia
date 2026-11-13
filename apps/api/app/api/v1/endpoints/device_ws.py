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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import WebSocketException

from app.constants.device_bridge import (
    DEVICE_HEARTBEAT_INTERVAL_SECONDS,
    DEVICE_HEARTBEAT_TIMEOUT_SECONDS,
    DEVICE_RELAY_READY_TIMEOUT_SECONDS,
    FRAME_EXEC_EXIT,
    FRAME_EXEC_STDERR,
    FRAME_EXEC_STDOUT,
    FRAME_HELLO,
    FRAME_MCP_ERROR,
    FRAME_MCP_MSG,
    FRAME_MCP_OPENED,
    FRAME_PING,
    FRAME_PONG,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.decorators.entitlements import is_paid
from app.services.device.bridge import (
    down_channel,
    mark_offline,
    mark_online,
    publish_up_to_pod,
)
from app.services.device.connection_manager import device_connection_manager
from app.services.device.device_auth import verify_device_token
from app.services.device.device_service import (
    enqueue_device_server_warmup,
    get_active_device,
    reconcile_device_servers,
)
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


def _rejected(reason: str) -> WebSocketException:
    """Refuse the dial the same way every other socket does — by raising."""
    return WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=reason)


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
        raise _rejected("device token missing or invalid")

    device_id = info["device_id"]
    user_id = info["user_id"]
    log.set(device={"id": device_id}, user={"id": user_id})

    # A revoked/deleted device must not be able to reconnect on a still-valid JWT.
    if await get_active_device(device_id) is None:
        log.set(disconnect_reason="device_revoked")
        raise _rejected("device revoked")

    # Paid-only gate: the HTTP paywall middleware never sees this socket, and
    # the device JWT outlives a subscription, so a lapsed daemon would tunnel
    # MCP traffic indefinitely otherwise. Checked at connect, like revocation.
    if not await is_paid(user_id):
        log.set(disconnect_reason="subscription_required")
        raise _rejected("subscription required")

    uses_subprotocol = websocket.headers.get("sec-websocket-protocol", "").startswith("Bearer, ")
    await websocket.accept(subprotocol="Bearer" if uses_subprotocol else None)

    device_connection_manager.add(device_id, websocket)
    # last_seen_at was just written by the token exchange (rotate_refresh_token)
    # that immediately precedes every dial; presence lives in Redis, so no
    # second Postgres write here.
    await mark_online(device_id)

    # The down relay must hold its subscription before any worker publishes:
    # Redis drops pub/sub frames with no subscriber, surfacing as a warmup
    # open-timeout that leaves tools undiscoverable until reconnect (bounded above).
    subscribed = asyncio.Event()
    state = {"last_recv": time.monotonic()}
    tasks = [
        asyncio.create_task(_down_relay(websocket, device_id, subscribed)),
        asyncio.create_task(_heartbeat(websocket, device_id, state)),
    ]
    try:
        async with asyncio.timeout(DEVICE_RELAY_READY_TIMEOUT_SECONDS):
            await subscribed.wait()
    except TimeoutError:
        log.warning(
            f"{LogTag.API} Down relay not subscribed before warmup",
            device_id=device_id,
        )
    # A device coming online re-drives warm-connect for all its servers, so tools
    # a registration couldn't index (Redis down, or the device was offline) get
    # indexed now. Best-effort — a socket must never fail on the warmup enqueue.
    try:
        await enqueue_device_server_warmup(device_id)
    except Exception as e:
        log.warning(
            f"{LogTag.API} Failed to enqueue device warmup on connect",
            device_id=device_id,
            error=str(e),
            error_type=type(e).__name__,
        )

    try:
        await _receive_loop(websocket, device_id, user_id, state)
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
        # Only clear presence if this pod holds no more sockets for the device:
        # mark_offline's compare-and-delete keys only on POD_ID, so an old
        # socket's teardown could wipe a newer same-pod socket's re-claimed key.
        if not device_connection_manager.owns(device_id):
            await mark_offline(device_id)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _receive_loop(
    websocket: WebSocket, device_id: str, user_id: str, state: dict[str, float]
) -> None:
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
        if frame_type in (
            FRAME_MCP_MSG,
            FRAME_MCP_OPENED,
            FRAME_MCP_ERROR,
            FRAME_EXEC_STDOUT,
            FRAME_EXEC_STDERR,
            FRAME_EXEC_EXIT,
        ):
            # The daemon echoes the consumer pod id (from mcp.open / exec.open) on
            # every up frame; route the reply to that pod's shared up-channel, where
            # the up-listener dispatches by "sid". No per-session subscription.
            pod = frame.get("pod")
            if isinstance(pod, str):
                await publish_up_to_pod(pod, raw)
            continue
        if frame_type == FRAME_HELLO:
            # The daemon's local config is the source of truth: prune server rows it
            # no longer exposes. Only act on an explicit list — an older daemon
            # omitting `servers` must not wipe everything.
            servers = frame.get("servers")
            if isinstance(servers, list):
                keys = [s for s in servers if isinstance(s, str)]
                try:
                    await reconcile_device_servers(user_id, device_id, keys)
                except Exception as e:
                    log.warning(
                        f"{LogTag.API} Failed to reconcile device servers on HELLO",
                        device_id=device_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
            continue
        # Unknown frame types are informational; ignore quietly.


async def _down_relay(
    websocket: WebSocket, device_id: str, subscribed: asyncio.Event | None = None
) -> None:
    """Subscribe to this device's down channel and write frames to the socket.

    Signals ``subscribed`` once the subscription holds, so the connect handler
    can enqueue warmup only after a worker's open frame has someone to land on.
    """
    if not redis_cache.redis:
        if subscribed is not None:
            subscribed.set()
        return
    pubsub = redis_cache.redis.pubsub()
    await pubsub.subscribe(down_channel(device_id))
    if subscribed is not None:
        subscribed.set()
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
