"""One engine websocket per session, shared by the host, the CDP proxy and the screencast.

Obscura isolates every CDP connection: contexts, pages and cookie jars never
cross one, and two connections both name their first context context-1. So a
session is a connection, not a context id. This owns that connection, allocates
every outbound id, routes each reply back to whoever asked, and fans events out.

Subscriber sinks run inside the read loop, so a sink that awaits the socket it is
being read from deadlocks the loop that would deliver its reply. Queue and return.

A sink may claim one CDP session id. Claimed frames reach only their owner, and
every other frame reaches every sink that claimed nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import json
from typing import Any, Protocol

import websockets

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

# Outbound CDP ids come from one allocator, so a control call and a forwarded
# client frame can never collide the way two independent counters would.
_FIRST_MESSAGE_ID = 1

# Every path that ends a session's connection reports it the same way, so a
# caller can match on one message rather than three near-identical copies.
_CONNECTION_CLOSED = "browser session connection closed"

CdpFrame = dict[str, Any]
FrameSink = Callable[[CdpFrame], None]
# A sink plus the CDP session id it claims, or None when it takes the open stream.
Subscription = tuple[FrameSink, str | None]


def sinks_for(subscriptions: Sequence[Subscription], frame: CdpFrame) -> list[FrameSink]:
    """Return the sinks a frame belongs to: its session's owner alone, else the open stream.

    The one statement of the routing rule, so a test double cannot hold a second,
    drifting copy of it. The result is a snapshot, so a sink may unsubscribe as
    it is called.
    """
    session_id = frame.get("sessionId")
    claimed = session_id is not None and any(owned == session_id for _, owned in subscriptions)
    return [
        sink
        for sink, owned in subscriptions
        if (owned == session_id if owned is not None else not claimed)
    ]


class CdpTransport(Protocol):
    """All a CDP round-trip needs of its transport, so cdp_call can take a test double too."""

    async def send_raw(
        self,
        method: str,
        params: CdpFrame | None = None,
        session_id: str | None = None,
    ) -> CdpFrame: ...


class CdpConnectionClosed(RuntimeError):
    """Raised when the session's engine connection is gone, so callers fail instead of hanging."""


class CdpMux:
    """The one CDP connection behind a session, multiplexed across its consumers."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._next_id = _FIRST_MESSAGE_ID
        # id -> future, for calls this mux made on a consumer's behalf.
        self._pending: dict[int, asyncio.Future[CdpFrame]] = {}
        # our id -> (the client's own id, the sink its reply belongs to).
        self._forwarded: dict[int, tuple[int | None, FrameSink]] = {}
        self._sinks: list[Subscription] = []
        self._closed = asyncio.Event()

    async def start(self) -> None:
        """Open the connection and begin reading; every consumer shares what this returns."""
        if self._ws is not None:
            raise RuntimeError("browser session connection is already open")
        self._ws = await websockets.connect(self._url, max_size=None, ping_interval=None)
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the connection and fail anything still waiting on it."""
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
        ws, self._ws = self._ws, None
        if ws is not None:
            await ws.close()
        self._mark_closed(CdpConnectionClosed(_CONNECTION_CLOSED))

    @property
    def closed(self) -> bool:
        """Whether the connection has ended — whether we closed it or the engine hung up."""
        return self._closed.is_set()

    async def wait_closed(self) -> None:
        """Block until the connection ends, so a consumer can tear itself down with it.

        An idle consumer has nothing to fail on otherwise, and would sit on a
        socket whose engine is already gone.
        """
        await self._closed.wait()

    def subscribe(self, sink: FrameSink, *, owns_session: str | None = None) -> Callable[[], None]:
        """Register a non-blocking sink for events and forwarded replies; returns its remover.

        owns_session claims one CDP session for this sink alone. The live view
        attaches a page session of its own, and its frames are no business of
        the agent's client, which would otherwise be handed a stream of
        screenshots and load events it never asked for.
        """
        entry: Subscription = (sink, owns_session)
        self._sinks.append(entry)

        def _remove() -> None:
            if entry in self._sinks:
                self._sinks.remove(entry)

        return _remove

    async def send_raw(
        self,
        method: str,
        params: CdpFrame | None = None,
        session_id: str | None = None,
    ) -> CdpFrame:
        """Issue one CDP command and return its result.

        Raises RuntimeError carrying the engine's own error object, so a failed
        command is a failure rather than an empty result the caller misreads.
        """
        message: CdpFrame = {"method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        reply = await self._send_tracked(message)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        result = reply.get("result", {})
        if not isinstance(result, dict):
            raise RuntimeError(f"malformed CDP result for {method}: {result!r}")
        return result

    async def forward(self, frame: CdpFrame, reply_to: FrameSink) -> None:
        """Send a client's own frame; its reply returns to reply_to wearing the client's id.

        A reply belongs to whoever asked, never to whoever owns the CDP session it
        names. The live view claims a session of its own, so routing a reply by
        session id could hand it an answer the agent is still waiting for.
        """
        client_id = frame.get("id")
        outbound = dict(frame)
        mux_id = self._allocate()
        outbound["id"] = mux_id
        self._forwarded[mux_id] = (client_id if isinstance(client_id, int) else None, reply_to)
        await self._write(outbound)

    async def _send_tracked(self, message: CdpFrame) -> CdpFrame:
        mux_id = self._allocate()
        message["id"] = mux_id
        future: asyncio.Future[CdpFrame] = asyncio.get_running_loop().create_future()
        self._pending[mux_id] = future
        try:
            await self._write(message)
        except BaseException:
            self._pending.pop(mux_id, None)
            raise
        return await future

    def _allocate(self) -> int:
        mux_id = self._next_id
        self._next_id += 1
        return mux_id

    async def _write(self, message: CdpFrame) -> None:
        ws = self._ws
        # The socket outlives an engine-side hang-up (close() still has to release
        # it), so the end of the read loop — not a None ws — is what says it is over.
        if ws is None or self._closed.is_set():
            raise CdpConnectionClosed(_CONNECTION_CLOSED)
        await ws.send(json.dumps(message))

    async def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                self._dispatch(raw if isinstance(raw, str) else raw.decode())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._mark_closed(exc)
        else:
            self._mark_closed(CdpConnectionClosed(_CONNECTION_CLOSED))

    def _dispatch(self, raw: str) -> None:
        try:
            frame: CdpFrame = json.loads(raw)
        except ValueError:
            log.warning(
                f"{LogTag.BROWSER} browser session dropped an unparsable CDP frame",
                error_type="ValueError",
            )
            return
        message_id = frame.get("id")
        if isinstance(message_id, int):
            pending = self._pending.pop(message_id, None)
            if pending is not None:
                if not pending.done():
                    pending.set_result(frame)
                return
            forwarded = self._forwarded.pop(message_id, None)
            if forwarded is not None:
                client_id, reply_to = forwarded
                # Hand the reply back wearing the id its sender chose, so the
                # client's own routing still recognises it.
                if client_id is None:
                    # isinstance(message_id, int) above proves the key is there.
                    frame.pop("id")
                else:
                    frame["id"] = client_id
                self._deliver(reply_to, frame)
                return
        self._fan_out(frame)

    def _fan_out(self, frame: CdpFrame) -> None:
        for sink in sinks_for(self._sinks, frame):
            self._deliver(sink, frame)

    def _deliver(self, sink: FrameSink, frame: CdpFrame) -> None:
        """Hand one frame to one sink; a sink that raises must not starve the others."""
        try:
            sink(frame)
        except Exception as exc:
            log.warning(
                f"{LogTag.BROWSER} browser session frame sink failed",
                error_type=type(exc).__name__,
            )

    def _mark_closed(self, exc: BaseException) -> None:
        """Release every waiter: the connection is over and nothing more will arrive."""
        self._closed.set()
        pending, self._pending = self._pending, {}
        self._forwarded.clear()
        for future in pending.values():
            if not future.done():
                future.set_exception(exc)
