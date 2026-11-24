"""DeviceConnector._drain_inbox: a malformed MCP frame must not kill the read loop.

The bug this pins: a device can send a corrupted/truncated mcp.msg frame
(a flaky tunnel, a half-written buffer on the other end). _drain_inbox
guards JSONRPCMessage.model_validate_json and forwards the parse failure
as a stream error instead of letting it propagate — propagating would hit the
loop's own broad except Exception, which tears the whole session down
(closing the read stream and ending the loop) instead of just failing the one
bad frame. These tests prove a bad frame is reported but the loop survives to
process the next, good, frame.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage
from mcp.types import (
    CONNECTION_CLOSED,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
)
import pytest

from app.constants.device_bridge import (
    DEVICE_DISCONNECTED_MESSAGE,
    FRAME_MCP_ERROR,
    FRAME_MCP_MSG,
    FRAME_TUNNEL_CLOSED,
)
from app.services.mcp.device_connector import DeviceConnectionError, DeviceConnector

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
    assert second.message.root == JSONRPCNotification(jsonrpc="2.0", method="ping", params={})


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
    assert results[1].message.root == JSONRPCNotification(
        jsonrpc="2.0", method="tools/list", params={}
    )
    assert isinstance(results[2], SessionMessage)
    assert results[2].message.root == JSONRPCNotification(jsonrpc="2.0", method="ping", params={})


def _request(request_id: int) -> SessionMessage:
    return SessionMessage(
        JSONRPCMessage(JSONRPCRequest(jsonrpc="2.0", id=request_id, method="tools/call"))
    )


def _response_frame(request_id: int) -> dict[str, object]:
    response = JSONRPCResponse(jsonrpc="2.0", id=request_id, result={})
    return {"t": FRAME_MCP_MSG, "data": JSONRPCMessage(response).model_dump_json()}


async def _lose_session_mid_call(loss: dict[str, object]) -> list[SessionMessage]:
    """Send requests 1 and 2 down, answer 1, then lose the session; return what the session reads."""
    connector = DeviceConnector(device_id="dev-1", server_key="server-1")
    connector._inbox = asyncio.Queue()
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](4)
    read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](4)
    with patch("app.services.mcp.device_connector.send_down", AsyncMock()):
        pump = asyncio.create_task(connector._pump_downstream(write_recv))
        await write_send.send(_request(1))
        await write_send.send(_request(2))
        await write_send.aclose()
        await pump
    connector._inbox.put_nowait(_response_frame(1))
    connector._inbox.put_nowait(loss)
    await asyncio.wait_for(connector._drain_inbox(read_send), timeout=2.0)
    received: list[SessionMessage] = []
    async for message in read_recv:
        assert isinstance(message, SessionMessage)
        received.append(message)
    return received


@pytest.mark.regression
@pytest.mark.parametrize(
    ("loss", "reason"),
    [
        ({"t": FRAME_TUNNEL_CLOSED}, DEVICE_DISCONNECTED_MESSAGE),
        ({"t": FRAME_MCP_ERROR, "error": "Local server 'x' exited"}, "Local server 'x' exited"),
        ({"t": FRAME_MCP_ERROR}, "device MCP error"),
    ],
    ids=["socket-dropped", "local-server-exited", "unexplained"],
)
async def test_a_lost_session_answers_only_its_unanswered_request_then_ends(
    loss: dict[str, object], reason: str
) -> None:
    """Regression for #1144: the session read the loss as an exception and its call waited 120s."""
    answered, failed = await _lose_session_mid_call(loss)

    assert answered.message.root == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
    assert failed.message.root == JSONRPCError(
        jsonrpc="2.0", id=2, error=ErrorData(code=CONNECTION_CLOSED, message=reason)
    )


async def test_a_failure_while_opening_fails_the_open_with_its_reason() -> None:
    connector = _connector_with_inbox([{"t": FRAME_MCP_ERROR, "error": "Local server 'x' exited"}])
    connector._opened = asyncio.get_running_loop().create_future()
    read_send, _ = anyio.create_memory_object_stream[SessionMessage | Exception](1)

    await asyncio.wait_for(connector._drain_inbox(read_send), timeout=2.0)

    with pytest.raises(DeviceConnectionError, match="Local server 'x' exited"):
        await connector._opened
