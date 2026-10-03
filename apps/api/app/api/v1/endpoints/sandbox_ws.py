"""The sandbox bridge WebSocket: one outbound socket per acquired sandbox.

The in-sandbox bridge client dials in with a short-lived sandbox JWT
(minted at acquire time, ``aud=sandbox-bridge``). While connected, this pod:
  * relays downstream frames (from any worker, via Redis) into the socket,
  * publishes upstream frames (from the socket) onto per-pod Redis channels,
  * heartbeats the socket and refreshes the sandbox's presence key.

Unlike the device tunnel there is no pairing flow: the sandbox's identity
comes from ``acquire_sandbox`` (the token's ``sandbox_id`` must match the
user's recorded sandbox), and reconnects are expected on every resume — an
E2B pause kills the socket, so this handler is designed for churn, not
persistence.
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
from app.db.repositories.e2b_sandboxes import e2b_sandbox_repository
from app.decorators.entitlements import is_paid
from app.services.device.bridge import publish_up_to_pod
from app.services.sandbox.bridge_registry import (
    mark_offline,
    mark_online,
    sandbox_connection_manager,
    sandbox_down_channel,
)
from app.services.sandbox.bridge_token import verify_sandbox_bridge_token
from shared.py.wide_events import log

router = APIRouter(prefix="/ws", tags=["Sandbox Bridge"])


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


@router.websocket("/sandbox")
async def sandbox_ws(websocket: WebSocket) -> None:
    """Sandbox bridge socket: authenticate the bridge client, then relay MCP frames both ways.

    WebSocketWideEventMiddleware emits the connection's wide event — one
    ``sandbox_ws_connection`` line per connection lifetime, covering auth
    rejections too — so this handler just calls ``log.set()`` like an HTTP handler.
    """
    token = _extract_token(websocket)
    info = verify_sandbox_bridge_token(token) if token else None
    if not info:
        log.set(disconnect_reason="auth_failure")
        raise _rejected("sandbox token missing or invalid")

    sandbox_id = info["sandbox_id"]
    user_id = info["user_id"]
    log.set(sandbox={"id": sandbox_id}, user={"id": user_id})

    # The token's sandbox must be the user's live sandbox: after an
    # E2B-side kill + recreate, the record points at the new sandbox and a
    # stale bridge redialing on its old token is cut off here.
    record = await e2b_sandbox_repository.get_for_user(user_id)
    if record is not None and record.sandbox_id not in (None, sandbox_id):
        log.set(disconnect_reason="stale_token")
        raise _rejected("sandbox token stale")

    # Paid-only gate: the HTTP paywall middleware never sees this socket, and
    # the bridge JWT outlives a subscription, so a lapsed sandbox would tunnel
    # MCP traffic indefinitely otherwise. Checked at connect, like staleness.
    if not await is_paid(user_id):
        log.set(disconnect_reason="subscription_required")
        raise _rejected("subscription required")

    uses_subprotocol = websocket.headers.get("sec-websocket-protocol", "").startswith("Bearer, ")
    await websocket.accept(subprotocol="Bearer" if uses_subprotocol else None)

    sandbox_connection_manager.add(sandbox_id, websocket)
    await mark_online(sandbox_id, user_id)

    # The down relay must hold its subscription before any worker publishes:
    # Redis drops pub/sub frames with no subscriber, surfacing as an
    # open-timeout that leaves tools undiscoverable until reconnect.
    subscribed = asyncio.Event()
    state = {"last_recv": time.monotonic()}
    tasks = [
        asyncio.create_task(_down_relay(websocket, sandbox_id, subscribed)),
        asyncio.create_task(_heartbeat(websocket, sandbox_id, user_id, state)),
    ]
    try:
        async with asyncio.timeout(DEVICE_RELAY_READY_TIMEOUT_SECONDS):
            await subscribed.wait()
    except TimeoutError:
        log.warning(
            f"{LogTag.API} Sandbox down relay not subscribed",
            sandbox_id=sandbox_id,
        )

    try:
        await _receive_loop(websocket, sandbox_id, state)
    # evlog-map-disable-next-line error-handling -- normal websocket disconnect; info-level is correct
    except WebSocketDisconnect:
        log.set(disconnect_reason="client_close")
        log.info(f"{LogTag.API} Sandbox disconnected", sandbox_id=sandbox_id)
    except Exception as e:
        log.set(disconnect_reason="server_error")
        log.warning(
            f"{LogTag.API} Sandbox socket error",
            sandbox_id=sandbox_id,
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        for task in tasks:
            task.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*tasks, return_exceptions=True)
        sandbox_connection_manager.remove(sandbox_id, websocket)
        # Only clear presence if this pod holds no more sockets for the sandbox.
        if not sandbox_connection_manager.owns(sandbox_id):
            await mark_offline(sandbox_id, user_id)
        with contextlib.suppress(Exception):
            await websocket.close()


async def _receive_loop(websocket: WebSocket, sandbox_id: str, state: dict[str, float]) -> None:
    """Read frames off the socket and route upstream ones onto Redis."""
    while True:
        raw = await websocket.receive_text()
        state["last_recv"] = time.monotonic()
        try:
            frame: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            log.warning(f"{LogTag.API} Sandbox sent malformed frame", sandbox_id=sandbox_id)
            continue

        frame_type = frame.get("t")
        if frame_type == FRAME_PONG:
            # Liveness is tracked by state["last_recv"] above; presence is
            # refreshed by the heartbeat — no need to write it per pong.
            continue
        if frame_type in (
            FRAME_MCP_MSG,
            FRAME_MCP_OPENED,
            FRAME_MCP_ERROR,
            FRAME_EXEC_STDOUT,
            FRAME_EXEC_STDERR,
            FRAME_EXEC_EXIT,
        ):
            # The bridge echoes the consumer pod id (from mcp.open / exec.open)
            # on every up frame; route the reply to that pod's shared
            # up-channel, where the up-listener dispatches by "sid".
            pod = frame.get("pod")
            if isinstance(pod, str):
                await publish_up_to_pod(pod, raw)
            continue
        if frame_type == FRAME_HELLO:
            # No server registry to reconcile against yet — the sandbox's
            # local config is allowlisted per-acquire, so the hello is
            # informational only.
            continue
        # Unknown frame types are informational; ignore quietly.


async def _down_relay(
    websocket: WebSocket, sandbox_id: str, subscribed: asyncio.Event | None = None
) -> None:
    """Subscribe to this sandbox's down channel and write frames to the socket.

    Signals ``subscribed`` once the subscription holds, so the connect handler
    knows a worker's open frame has someone to land on.
    """
    if not redis_cache.redis:
        if subscribed is not None:
            subscribed.set()
        return
    pubsub = redis_cache.redis.pubsub()
    await pubsub.subscribe(sandbox_down_channel(sandbox_id))
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
            await pubsub.unsubscribe(sandbox_down_channel(sandbox_id))
            await pubsub.aclose()


async def _heartbeat(
    websocket: WebSocket, sandbox_id: str, user_id: str, state: dict[str, float]
) -> None:
    """Ping periodically; refresh presence; drop the socket if it goes silent."""
    while True:
        await asyncio.sleep(DEVICE_HEARTBEAT_INTERVAL_SECONDS)
        if time.monotonic() - state["last_recv"] > DEVICE_HEARTBEAT_TIMEOUT_SECONDS:
            log.warning(f"{LogTag.API} Sandbox heartbeat timed out", sandbox_id=sandbox_id)
            with contextlib.suppress(Exception):
                await websocket.close(code=1001)
            return
        await mark_online(sandbox_id, user_id)
        with contextlib.suppress(Exception):
            await websocket.send_text(json.dumps({"t": FRAME_PING}))
