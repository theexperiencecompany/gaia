"""Unit tests for the device tunnel WebSocket connect ordering.

The online handler must hold the down-channel subscription before enqueueing
warmup: Redis drops pub/sub frames with no subscriber, which surfaces as a
warmup open-timeout and leaves the server's tools undiscoverable until the
next reconnect.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import WebSocketDisconnect
import pytest

from app.api.v1.endpoints import device_ws as ws_module
from tests.helpers import captured_wide_event

_MODULE = "app.api.v1.endpoints.device_ws"


def _socket() -> MagicMock:
    ws = MagicMock()
    ws.headers = {"authorization": "Bearer device-token"}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def _manager() -> MagicMock:
    manager = MagicMock()
    manager.owns = MagicMock(return_value=False)
    return manager


async def _run_handler(ws, relay, enqueue, receive=None):
    if receive is None:
        receive = AsyncMock(side_effect=WebSocketDisconnect())
    with (
        patch.object(
            ws_module, "verify_device_token", return_value={"device_id": "d1", "user_id": "u1"}
        ),
        patch.object(ws_module, "get_active_device", AsyncMock(return_value=object())),
        # The connect-time paywall is covered by its own tests; these pin ordering for a Pro user.
        patch.object(ws_module, "is_paid", AsyncMock(return_value=True)),
        patch.object(ws_module, "mark_online", AsyncMock()),
        patch.object(ws_module, "mark_offline", AsyncMock()),
        patch.object(ws_module, "device_connection_manager", _manager()),
        patch.object(ws_module, "enqueue_device_server_warmup", enqueue),
        patch.object(ws_module, "_down_relay", relay),
        patch.object(ws_module, "_heartbeat", AsyncMock()),
        patch.object(ws_module, "_receive_loop", receive),
    ):
        await ws_module.device_ws(ws)
    return receive


@pytest.mark.asyncio
async def test_warmup_enqueued_only_after_relay_subscribes():
    """The relay task starts first and the enqueue waits for its subscribe-ready signal — reversing the order drops the open frame."""
    order: list[str] = []
    seen: dict[str, object] = {}
    ws = _socket()

    async def fake_relay(websocket, device_id, ready=None):
        order.append("relay-start")
        seen["relay"] = (websocket, device_id, ready)
        await asyncio.sleep(0)
        ready.set()
        order.append("relay-subscribed")

    async def fake_enqueue(device_id, *args, **kwargs):
        order.append("enqueue")
        seen["enqueue"] = (device_id, args, kwargs)

    receive = await _run_handler(ws, fake_relay, fake_enqueue)

    assert order.index("relay-subscribed") < order.index("enqueue")
    # relay/warmup/reader must all get the same socket, device id, and
    # readiness event — a blanked or swapped arg here would silently
    # misroute the connection without failing any assertion by itself.
    relay_ws, relay_device, relay_ready = seen["relay"]
    assert relay_ws is ws
    assert relay_device == "d1"
    assert isinstance(relay_ready, asyncio.Event) and relay_ready.is_set()
    assert seen["enqueue"] == ("d1", (), {})
    assert receive.await_args.args[:3] == (ws, "d1", "u1")
    state = receive.await_args.args[3]
    assert set(state) == {"last_recv"} and isinstance(state["last_recv"], float)


@pytest.mark.asyncio
async def test_stalled_relay_does_not_block_the_socket():
    """A subscribe that never lands still lets the socket connect: the wait is bounded and the enqueue proceeds."""
    enqueued = asyncio.Event()

    async def stalled_relay(websocket, device_id, ready=None):
        await asyncio.sleep(60)

    async def fake_enqueue(device_id, server_keys=None):
        enqueued.set()

    with patch.object(ws_module, "DEVICE_RELAY_READY_TIMEOUT_SECONDS", 0.01):
        async with captured_wide_event() as event:
            await asyncio.wait_for(_run_handler(_socket(), stalled_relay, fake_enqueue), 10)

    assert enqueued.is_set()
    # The stall is observable with its device — a silent proceed hides a
    # relay that will drop every subsequent down frame.
    (warning,) = event["warnings"]
    assert "Down relay not subscribed before warmup" in warning["msg"]
    assert warning["device_id"] == "d1"


@pytest.mark.asyncio
async def test_enqueue_failure_is_logged_with_its_cause_and_not_fatal():
    """A Redis outage on the enqueue must not fail the socket, but the failure and its cause must still reach the wide event."""
    enqueued = asyncio.Event()

    async def fake_relay(websocket, device_id, ready=None):
        ready.set()

    async def failing_enqueue(device_id, *args, **kwargs):
        enqueued.set()
        raise ConnectionError("redis down")

    with patch.object(ws_module, "DEVICE_RELAY_READY_TIMEOUT_SECONDS", 0.01):
        async with captured_wide_event() as event:
            # Must not raise: the connect handler keeps the socket alive.
            await asyncio.wait_for(_run_handler(_socket(), fake_relay, failing_enqueue), 10)

    assert enqueued.is_set()
    (warning,) = event["warnings"]
    assert "Failed to enqueue device warmup on connect" in warning["msg"]
    assert warning["device_id"] == "d1"
    assert warning["error"] == "redis down"
    assert warning["error_type"] == "ConnectionError"


@pytest.mark.asyncio
async def test_relay_signals_only_after_subscribe_returns():
    """The readiness signal fires after subscribe() resolves — not before."""
    events: list[str] = []
    pubsub = MagicMock()

    async def fake_get_message(**kwargs):
        # Yield like real Redis I/O: a bare AsyncMock never suspends, and the
        # tight poll loop would starve the event loop (and its timers).
        await asyncio.sleep(0.01)

    pubsub.get_message = AsyncMock(side_effect=fake_get_message)

    async def fake_subscribe(channel):
        events.append("subscribe")

    pubsub.subscribe = AsyncMock(side_effect=fake_subscribe)
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    ws = _socket()
    ready = asyncio.Event()

    with patch.object(ws_module.redis_cache, "redis", redis):
        task = asyncio.create_task(ws_module._down_relay(ws, "d1", ready))
        await asyncio.wait_for(ready.wait(), 5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert events == ["subscribe"]
    pubsub.subscribe.assert_awaited_once_with("device:down:d1")


@pytest.mark.asyncio
async def test_relay_without_redis_still_signals_ready():
    """No Redis means no subscription is possible — signal anyway so the handler's bounded wait never stalls."""
    ready = asyncio.Event()
    with patch.object(ws_module.redis_cache, "redis", None):
        await ws_module._down_relay(_socket(), "d1", ready)
    assert ready.is_set()
