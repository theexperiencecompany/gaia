"""An mcp_use connector that speaks MCP over the device tunnel.

The cloud runs a real ``mcp.ClientSession``; its read/write streams are pumped
through the device bridge (Redis pub/sub → the owning pod → the daemon → the
local MCP server) and back. To the rest of GAIA's MCP stack this connector is
indistinguishable from an HTTP one, so tool conversion, subagents and namespacing
all work unchanged.

Frames on the wire are transparent JSON-RPC — the daemon never parses them, it
just relays between this session and the local server's transport.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any
import uuid

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp_use.client.connectors.base import BaseConnector

from app.constants.device_bridge import (
    FRAME_MCP_CLOSE,
    FRAME_MCP_ERROR,
    FRAME_MCP_MSG,
    FRAME_MCP_OPEN,
    FRAME_MCP_OPENED,
    MCP_SESSION_CALL_TIMEOUT_SECONDS,
    MCP_SESSION_OPEN_TIMEOUT_SECONDS,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.services.device.bridge import POD_ID, is_online, send_down
from app.services.device.up_listener import register_up_session, unregister_up_session
from mcp import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage
from shared.py.wide_events import log


class DeviceConnectionError(RuntimeError):
    """The device is offline or the tunnel could not open a session."""


class DeviceConnector(BaseConnector):
    """MCP connector that tunnels a session to a local server on a paired device."""

    def __init__(self, device_id: str, server_key: str) -> None:
        super().__init__()
        # Re-annotate the base's attribute so mypy has a concrete type for it
        # (mcp_use ships no stubs, so BaseConnector's attributes read as Any).
        self.client_session: ClientSession | None = None
        self.device_id = device_id
        self.server_key = server_key
        self.session_id = uuid.uuid4().hex
        # Fed by the shared per-pod up-listener (up_listener.py); drained by
        # _reader_task. Replaces a per-session Redis pub/sub subscription.
        self._inbox: asyncio.Queue[dict[str, Any]] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._writer_task: asyncio.Task[None] | None = None
        self._opened: asyncio.Future[None] | None = None
        self._read_send: MemoryObjectSendStream[SessionMessage | Exception] | None = None
        self._write_recv: MemoryObjectReceiveStream[SessionMessage] | None = None

    @property
    def public_identifier(self) -> str:
        return f"device:{self.device_id}:{self.server_key}"

    async def connect(self) -> None:
        if self.client_session is not None:
            return
        if not redis_cache.redis:
            raise DeviceConnectionError("Device bridge unavailable (no Redis connection)")
        if not await is_online(self.device_id):
            raise DeviceConnectionError(
                "Your device is offline. Run `gaia bridge up` on that machine and try again."
            )

        loop = asyncio.get_running_loop()
        self._opened = loop.create_future()

        read_send, read_recv = anyio.create_memory_object_stream[SessionMessage | Exception](0)
        write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)
        self._read_send = read_send
        self._write_recv = write_recv

        # Register the inbox BEFORE sending open so the 'opened' ack can't slip
        # past us (the shared up-listener is always subscribed; this makes it
        # dispatch this session's frames to us).
        self._inbox = register_up_session(self.session_id)
        self._reader_task = asyncio.create_task(self._drain_inbox(read_send))

        try:
            # "pod" tells the device (and the owning pod, which echoes it back on
            # every reply) which pod's up-channel to address responses to.
            await send_down(
                self.device_id,
                {
                    "t": FRAME_MCP_OPEN,
                    "sid": self.session_id,
                    "server": self.server_key,
                    "pod": POD_ID,
                },
            )
            await asyncio.wait_for(self._opened, timeout=MCP_SESSION_OPEN_TIMEOUT_SECONDS)
        except TimeoutError as e:
            await self._fail_open()
            raise DeviceConnectionError(
                f"Timed out opening '{self.server_key}' on your device"
            ) from e
        except Exception:
            # Any other failure — a device-side mcp.error surfaced through the
            # open future, or a Redis publish error from send_down — must still
            # tear down the reader task and inbox registered above.
            await self._fail_open()
            raise

        # Bound every request: if the owning pod or the device dies mid-call, the
        # reply never arrives — without a read timeout the ClientSession waits
        # forever (SDK default). This turns that hang into a surfaced timeout.
        self.client_session = ClientSession(
            read_recv,
            write_send,
            read_timeout_seconds=timedelta(seconds=MCP_SESSION_CALL_TIMEOUT_SECONDS),
        )
        await self.client_session.__aenter__()
        self._writer_task = asyncio.create_task(self._pump_downstream(write_recv))
        self._connected = True
        log.set_ns(
            "mcp",
            operation="device_connect",
            server_id=self.public_identifier,
            session_id=self.session_id,
        )

    async def _drain_inbox(
        self, read_send: MemoryObjectSendStream[SessionMessage | Exception]
    ) -> None:
        """This session's inbox (fed by the shared up-listener) → the read stream."""
        # The up-listener populates the inbox before any session stream starts;
        # assert is a dev guard, not a runtime check.
        assert self._inbox is not None  # nosec B101
        inbox = self._inbox
        try:
            while True:
                frame = await inbox.get()
                frame_type = frame.get("t")
                if frame_type == FRAME_MCP_OPENED:
                    self._resolve_open(None)
                elif frame_type == FRAME_MCP_ERROR:
                    error = DeviceConnectionError(frame.get("error") or "device MCP error")
                    if not self._resolve_open(error):
                        # Mid-session error: fail the read stream to tear down.
                        with contextlib.suppress(Exception):
                            await read_send.send(error)
                elif frame_type == FRAME_MCP_MSG:
                    data = frame.get("data")
                    if not isinstance(data, str):
                        continue
                    try:
                        jsonrpc = JSONRPCMessage.model_validate_json(data)
                    except Exception as parse_err:  # forward as stream error
                        await read_send.send(parse_err)
                        continue
                    await read_send.send(SessionMessage(jsonrpc))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} Device inbox drain ended", error=str(e), error_type=type(e).__name__
            )
            # Fail the read stream so an in-flight call unblocks immediately and
            # the session tears down, instead of hanging until the read timeout.
            with contextlib.suppress(Exception):
                await read_send.send(DeviceConnectionError("device tunnel closed"))

    async def _pump_downstream(self, write_recv: MemoryObjectReceiveStream[SessionMessage]) -> None:
        """The ClientSession's write stream → Redis down-channel to the device."""
        try:
            async for session_message in write_recv:
                payload = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                await send_down(
                    self.device_id,
                    {"t": FRAME_MCP_MSG, "sid": self.session_id, "data": payload},
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                f"{LogTag.MCP} Device downstream pump ended",
                error=str(e),
                error_type=type(e).__name__,
            )

    def _resolve_open(self, error: Exception | None) -> bool:
        """Settle the open future once. Returns True if this call settled it."""
        if self._opened is None or self._opened.done():
            return False
        if error is None:
            self._opened.set_result(None)
        else:
            self._opened.set_exception(error)
        return True

    async def disconnect(self) -> None:
        if not self._connected and self._reader_task is None:
            return
        with contextlib.suppress(Exception):
            await send_down(self.device_id, {"t": FRAME_MCP_CLOSE, "sid": self.session_id})
        for task in (self._writer_task, self._reader_task):
            if task is not None:
                task.cancel()
        for task in (self._writer_task, self._reader_task):
            if task is not None:
                # A cancelled task re-raises CancelledError (a BaseException, so
                # suppress(Exception) would miss it and disconnect() would leak
                # the cancellation into its caller's teardown).
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._writer_task = None
        self._reader_task = None
        await super().disconnect()
        await self._teardown_streams()

    async def _fail_open(self) -> None:
        """Clean up after a failed open. Cancels the reader task first.

        The reader (``_drain_inbox``) is parked on ``inbox.get()``; unregistering
        the inbox and closing the streams does not wake it (the queue has no
        close), so without an explicit cancel it would leak, blocked forever.
        ``disconnect()`` is never reached on this path — ``_build_device_client``
        raises before the session is registered with any client.
        """
        if self._reader_task is not None:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader_task
            self._reader_task = None
        await self._teardown_streams()

    async def _teardown_streams(self) -> None:
        unregister_up_session(self.session_id)
        self._inbox = None
        for stream in (self._read_send, self._write_recv):
            if stream is not None:
                with contextlib.suppress(Exception):
                    await stream.aclose()
        self._read_send = None
        self._write_recv = None
