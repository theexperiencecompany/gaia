"""Service tests: call real device-bridge modules against real Redis.

The conftest's ``real_redis`` fixture patches ``redis_cache.redis`` to a real
connection; every function under test runs unmodified. A "fake daemon" task
plays the *other* end of the tunnel (subscribing to the down-channel and
replying on the up-channel exactly like ``gaia bridge`` would) so
``DeviceConnector`` is exercised end-to-end without spawning Node.

Each test targets a specific bug this bridge has actually shipped with:
presence flapping across pods, a session's replies leaking to another
session, a revoke closing the wrong socket, and cancellation leaking out of
``disconnect()``.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from unittest.mock import AsyncMock

import pytest

import app.services.device.bridge as bridge_module
from app.services.device.connection_manager import device_connection_manager
from app.services.device.revoke_listener import start_revoke_listener, stop_revoke_listener
import app.services.device.up_listener as up_listener_module
from app.services.mcp.device_connector import DeviceConnector

FAKE_SERVER_KEY = "fake-server"


async def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05) -> None:
    """Poll ``predicate`` until it's truthy or raise on timeout (for pub/sub-driven state)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s")
        await asyncio.sleep(interval)


async def _fake_daemon(device_id: str, real_redis) -> None:
    """Stand in for the ``gaia bridge`` daemon: relay down-channel frames to a

    canned MCP ``initialize`` response on the up-channel, exactly like the
    real daemon's ``openSession``/``forwardToServer`` would for a real server.

    ``pod`` only rides the ``mcp.open`` frame (see ``DeviceConnector.connect``);
    every later down-frame for the session omits it, exactly as the real
    ``gaia bridge`` daemon's own ``tunnel.ts`` expects — it caches the pod id
    once, at open time, and echoes that cached value on every reply for the
    session's lifetime rather than re-reading it each time.
    """
    session_pods: dict[str, str] = {}
    pubsub = real_redis.pubsub()
    await pubsub.subscribe(bridge_module.down_channel(device_id))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None or message.get("type") != "message":
                continue
            frame = json.loads(message["data"])
            sid = frame.get("sid")
            if frame["t"] == "mcp.open":
                session_pods[sid] = frame["pod"]
                pod = session_pods[sid]
                await bridge_module.publish_up_to_pod(
                    pod, json.dumps({"t": "mcp.opened", "sid": sid, "pod": pod})
                )
            elif frame["t"] == "mcp.msg":
                pod = session_pods[sid]
                rpc = json.loads(frame["data"])
                if rpc.get("method") != "initialize":
                    continue
                response = {
                    "jsonrpc": "2.0",
                    "id": rpc["id"],
                    "result": {
                        "protocolVersion": rpc["params"]["protocolVersion"],
                        "capabilities": {},
                        "serverInfo": {"name": "fake-daemon-server", "version": "0.0.1"},
                    },
                }
                await bridge_module.publish_up_to_pod(
                    pod,
                    json.dumps(
                        {"t": "mcp.msg", "sid": sid, "pod": pod, "data": json.dumps(response)}
                    ),
                )
            elif frame["t"] == "mcp.close":
                return
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(bridge_module.down_channel(device_id))
            await pubsub.aclose()


@pytest.mark.service
class TestPresenceOwnership:
    """mark_offline is a compare-and-delete keyed on POD_ID — a stale pod's

    teardown must never evict a presence claim a live reconnect already made
    on another pod.
    """

    async def test_mark_offline_evicts_when_this_pod_still_owns_it(self, real_redis, monkeypatch):
        device_id = "dev-presence-owned"
        monkeypatch.setattr(bridge_module, "POD_ID", "pod-a")

        await bridge_module.mark_online(device_id)
        assert await bridge_module.is_online(device_id)

        await bridge_module.mark_offline(device_id)
        assert not await bridge_module.is_online(device_id)

    async def test_mark_offline_is_a_noop_once_another_pod_has_claimed_presence(
        self, real_redis, monkeypatch
    ):
        device_id = "dev-presence-reclaimed"

        monkeypatch.setattr(bridge_module, "POD_ID", "pod-a")
        await bridge_module.mark_online(device_id)

        # The device reconnected and pod B now owns it.
        monkeypatch.setattr(bridge_module, "POD_ID", "pod-b")
        await bridge_module.mark_online(device_id)

        # Pod A's stale connection is only now getting around to tearing down.
        monkeypatch.setattr(bridge_module, "POD_ID", "pod-a")
        await bridge_module.mark_offline(device_id)

        assert await bridge_module.is_online(device_id)


@pytest.mark.service
class TestSendDown:
    async def test_send_down_delivers_the_frame_verbatim(self, real_redis):
        device_id = "dev-down-1"
        pubsub = real_redis.pubsub()
        await pubsub.subscribe(bridge_module.down_channel(device_id))
        try:
            await bridge_module.send_down(device_id, {"t": "mcp.open", "sid": "s1"})

            message = None
            for _ in range(20):
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                if message is not None:
                    break
            assert message is not None
            assert json.loads(message["data"]) == {"t": "mcp.open", "sid": "s1"}
        finally:
            await pubsub.unsubscribe(bridge_module.down_channel(device_id))
            await pubsub.aclose()


@pytest.mark.service
class TestUpListenerDispatch:
    async def test_dispatch_routes_frames_by_session_id(self, real_redis):
        up_listener_module.start_up_listener()
        try:
            await asyncio.sleep(0.2)  # let the listener's subscribe() land first
            inbox_a = up_listener_module.register_up_session("session-a", "dev-a")
            inbox_b = up_listener_module.register_up_session("session-b", "dev-b")
            try:
                await bridge_module.publish_up_to_pod(
                    up_listener_module.POD_ID,
                    json.dumps({"t": "mcp.msg", "sid": "session-a", "data": "for-a"}),
                )
                await bridge_module.publish_up_to_pod(
                    up_listener_module.POD_ID,
                    json.dumps({"t": "mcp.msg", "sid": "session-b", "data": "for-b"}),
                )

                frame_a = await asyncio.wait_for(inbox_a.get(), timeout=2)
                frame_b = await asyncio.wait_for(inbox_b.get(), timeout=2)

                assert frame_a["data"] == "for-a"
                assert frame_b["data"] == "for-b"
                # Neither session ever saw the other's frame.
                assert inbox_a.empty()
                assert inbox_b.empty()
            finally:
                up_listener_module.unregister_up_session("session-a")
                up_listener_module.unregister_up_session("session-b")
        finally:
            await up_listener_module.stop_up_listener()

    async def test_dispatch_ignores_a_frame_for_an_unregistered_session(self, real_redis):
        """A frame with no matching inbox must be dropped, not raise — an

        uncaught exception here would kill the shared listener loop for every
        session on the pod, not just this one.
        """
        up_listener_module.start_up_listener()
        try:
            await asyncio.sleep(0.2)  # let the listener's subscribe() land first
            await bridge_module.publish_up_to_pod(
                up_listener_module.POD_ID,
                json.dumps({"t": "mcp.msg", "sid": "never-registered", "data": "ghost"}),
            )

            # The listener must still be alive and dispatching afterward.
            inbox = up_listener_module.register_up_session("session-after", "dev-after")
            try:
                await bridge_module.publish_up_to_pod(
                    up_listener_module.POD_ID,
                    json.dumps({"t": "mcp.msg", "sid": "session-after", "data": "still-alive"}),
                )
                frame = await asyncio.wait_for(inbox.get(), timeout=2)
                assert frame["data"] == "still-alive"
            finally:
                up_listener_module.unregister_up_session("session-after")
        finally:
            await up_listener_module.stop_up_listener()


@pytest.mark.service
class TestDeviceDisconnect:
    async def test_disconnect_fails_only_that_devices_in_flight_sessions(self, real_redis):
        """A device socket teardown must unblock its parked calls, not every call.

        Without the disconnect fan-out the session parks on ``inbox.get()`` until
        MCP_SESSION_CALL_TIMEOUT_SECONDS; the broadcast turns that 120s hang into
        an immediate mcp.error. It must reach only the sessions on the dropped
        device — a session on a still-connected device keeps running.
        """
        up_listener_module.start_up_listener()
        dropped_a = up_listener_module.register_up_session("drop-1", "dev-dropped")
        dropped_b = up_listener_module.register_up_session("drop-2", "dev-dropped")
        survivor = up_listener_module.register_up_session("keep-1", "dev-live")
        try:
            await asyncio.sleep(0.2)  # let the listener's subscribe() land first
            await bridge_module.publish_disconnect("dev-dropped")

            frame_a = await asyncio.wait_for(dropped_a.get(), timeout=2)
            frame_b = await asyncio.wait_for(dropped_b.get(), timeout=2)
            assert frame_a["t"] == "mcp.error"
            assert frame_b["t"] == "mcp.error"
            assert frame_a["error"]  # carries a reason the connector surfaces

            # The session on the still-connected device was never touched.
            assert survivor.empty()
        finally:
            up_listener_module.unregister_up_session("drop-1")
            up_listener_module.unregister_up_session("drop-2")
            up_listener_module.unregister_up_session("keep-1")
            await up_listener_module.stop_up_listener()


@pytest.mark.service
class TestRevokeListener:
    async def test_closes_only_the_targeted_devices_socket(self, real_redis):
        device_a, device_b = "dev-revoke-a", "dev-revoke-b"
        socket_a, socket_b = AsyncMock(), AsyncMock()
        device_connection_manager.add(device_a, socket_a)
        device_connection_manager.add(device_b, socket_b)
        start_revoke_listener()
        try:
            await asyncio.sleep(0.2)  # let the listener's subscribe() land first
            await bridge_module.request_revoke(device_a)

            await _wait_until(lambda: socket_a.close.await_count > 0)

            socket_a.close.assert_awaited_once_with(code=1008)
            socket_b.close.assert_not_awaited()
        finally:
            device_connection_manager.remove(device_a, socket_a)
            device_connection_manager.remove(device_b, socket_b)
            await stop_revoke_listener()


@pytest.mark.service
class TestDeviceConnectorRoundTrip:
    async def test_connect_initialize_and_clean_disconnect(self, real_redis):
        device_id = "dev-connector-1"
        await bridge_module.mark_online(device_id)
        up_listener_module.start_up_listener()
        daemon_task = asyncio.create_task(_fake_daemon(device_id, real_redis))
        await asyncio.sleep(0.2)  # let both subscribes land before connect() publishes
        connector = DeviceConnector(device_id, FAKE_SERVER_KEY)
        try:
            await connector.connect()
            session = connector.client_session
            assert session is not None

            result = await session.initialize()
            assert result.serverInfo.name == "fake-daemon-server"

            # disconnect() cancels its own reader/writer tasks; the CancelledError
            # that produces must be absorbed here, not leaked to the caller.
            await connector.disconnect()
        finally:
            daemon_task.cancel()
            with suppress(asyncio.CancelledError):
                await daemon_task
            await up_listener_module.stop_up_listener()

    async def test_connect_raises_when_device_is_offline(self, real_redis):
        connector = DeviceConnector("dev-never-online", FAKE_SERVER_KEY)
        with pytest.raises(Exception, match="offline"):
            await connector.connect()
