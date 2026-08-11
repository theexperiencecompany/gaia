"""``DeviceConnector._drain_inbox``: a malformed MCP frame must not kill the read loop.

The bug this pins: a device can send a corrupted/truncated ``mcp.msg`` frame
(a flaky tunnel, a half-written buffer on the other end). ``_drain_inbox``
guards ``JSONRPCMessage.model_validate_json`` and forwards the parse failure
as a stream error instead of letting it propagate — propagating would hit the
loop's own broad ``except Exception``, which tears the whole session down
(closing the read stream and ending the loop) instead of just failing the one
bad frame. These tests prove a bad frame is reported but the loop survives to
process the next, good, frame.
"""

from __future__ import annotations

import asyncio
import contextlib

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage
import pytest

from app.constants.device_bridge import FRAME_MCP_MSG
from app.services.mcp.device_connector import DeviceConnector

pytestmark = pytest.mark.unit


def _connector_with_inbox(frames: list[dict[str, object]]) -> DeviceConnector:
    connector = DeviceConnector(device_id="dev-1", server_key="server-1")
    inbox: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    for frame in frames:
        inbox.put_nowait(frame)
    connector._inbox = inbox
    return connector


async def _run_drain_and_collect(
    connector: DeviceConnector, count: int
) -> list[SessionMessage | Exception]:
    read_send: MemoryObjectSendStream[SessionMessage | Exception]
    read_recv: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_send, read_recv = anyio.create_memory_object_stream(4)
    task = asyncio.create_task(connector._drain_inbox(read_send))
    try:
        results = []
        for _ in range(count):
            results.append(await asyncio.wait_for(read_recv.receive(), timeout=2.0))
        return results
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


async def test_malformed_frame_forwarded_as_error_without_killing_loop() -> None:
    connector = _connector_with_inbox(
        [
            {"t": FRAME_MCP_MSG, "data": "not-json-at-all"},
            {"t": FRAME_MCP_MSG, "data": '{"jsonrpc":"2.0","method":"ping","params":{}}'},
        ]
    )

    first, second = await _run_drain_and_collect(connector, 2)

    # Bad frame #1: a parse failure, not a SessionMessage — and NOT the
    # generic DeviceConnectionError the outer loop-level except would send if
    # the inner guard were removed (that would also end the loop entirely).
    assert isinstance(first, Exception)
    assert not isinstance(first, SessionMessage)
    assert type(first).__name__ == "ValidationError"

    # Good frame #2 still arrives — proof the loop kept running after the bad
    # frame instead of tearing the session down.
    assert isinstance(second, SessionMessage)
    assert second.message.root.method == "ping"


async def test_valid_frames_after_malformed_frame_are_unaffected() -> None:
    connector = _connector_with_inbox(
        [
            {"t": FRAME_MCP_MSG, "data": "{broken"},
            {"t": FRAME_MCP_MSG, "data": '{"jsonrpc":"2.0","method":"tools/list","params":{}}'},
            {"t": FRAME_MCP_MSG, "data": '{"jsonrpc":"2.0","method":"ping","params":{}}'},
        ]
    )

    results = await _run_drain_and_collect(connector, 3)

    assert isinstance(results[0], Exception)
    assert isinstance(results[1], SessionMessage)
    assert results[1].message.root.method == "tools/list"
    assert isinstance(results[2], SessionMessage)
    assert results[2].message.root.method == "ping"
