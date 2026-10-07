"""One engine websocket per session, shared by the host, the CDP proxy and the screencast.

Obscura isolates every CDP connection: contexts, pages and cookie jars never
cross one, and two connections both name their first context context-1. So a
session is a connection, not a context id. This owns that connection, allocates
every outbound id, routes each reply back to whoever asked, and fans events out.

Subscriber sinks run inside the read loop, so a sink that awaits the socket it is
being read from deadlocks the loop that would deliver its reply. Queue and return.

A sink may claim one CDP session id. Claimed frames reach only their owner, and
every other frame reaches every sink that claimed nothing. A session the host
attaches itself is claimed from the engine's first word about it, so a client
sharing the connection never sees, adopts or loses it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
import contextlib
import json
from typing import Any, Protocol

import websockets

from app.constants.log_tags import LogTag
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import log

# Outbound CDP ids come from one allocator, so a control call and a forwarded
# client frame can never collide the way two independent counters would.
_FIRST_MESSAGE_ID = 1

# Every path that ends a session's connection reports it the same way, so a
# caller can match on one message rather than three near-identical copies.
_CONNECTION_CLOSED = "browser session connection closed"

# How long a close waits for the engine's half of the handshake; a dead engine never sends it.
_CLOSE_TIMEOUT_SECONDS = 2.0

# CdpMux puts no timeout on a reply, so every host call is bounded here: a wedged
# renderer must not freeze the caller while the process stays alive and looks healthy.
CDP_CALL_TIMEOUT_SECONDS = 20.0

# Connection-level events that announce a session rather than travel on one.
_ATTACHED_EVENT = "Target.attachedToTarget"
_SESSION_LIFECYCLE_EVENTS = frozenset({_ATTACHED_EVENT, "Target.detachedFromTarget"})

CdpFrame = dict[str, Any]
FrameSink = Callable[[CdpFrame], None]
# A sink plus the CDP session id it claims, or None when it takes the open stream.
Subscription = tuple[FrameSink, str | None]
# Runs on a tracked command's reply, in the read loop; None when the command never left.
ReplyHook = Callable[[CdpFrame | None], None]


def _session_of(frame: CdpFrame) -> str | None:
    """Return the CDP session a frame belongs to: the one it travels on, or the one it announces."""
    session_id = frame.get("sessionId")
    if session_id is None and frame.get("method") in _SESSION_LIFECYCLE_EVENTS:
        params = frame.get("params")
        announced = params.get("sessionId") if isinstance(params, dict) else None
        return announced if isinstance(announced, str) else None
    return session_id if isinstance(session_id, str) else None


def _announced_target(frame: CdpFrame) -> str | None:
    """Return the target a connection-level attachedToTarget announces a session for, else None."""
    if frame.get("method") != _ATTACHED_EVENT or "sessionId" in frame:
        return None
    params = frame.get("params")
    info = params.get("targetInfo") if isinstance(params, dict) else None
    target_id = info.get("targetId") if isinstance(info, dict) else None
    return target_id if isinstance(target_id, str) else None


def sinks_for(subscriptions: Sequence[Subscription], frame: CdpFrame) -> list[FrameSink]:
    """Return the sinks a frame belongs to: its session's owner alone, else the open stream.

    The one statement of the routing rule, so a test double cannot hold a second,
    drifting copy of it. The result is a snapshot, so a sink may unsubscribe as
    it is called.
    """
    session_id = _session_of(frame)
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


class CdpCommandError(RuntimeError):
    """Raised when the engine answers a command with its own error object."""


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
        # our id -> what runs in the read loop the moment its reply lands, before
        # any later frame is routed; attach() claims its session there.
        self._reply_hooks: dict[int, ReplyHook] = {}
        # target id -> host attaches to it still awaiting their reply, and the
        # attach announcements withheld until those replies say whose they are.
        self._attaching: dict[str, int] = {}
        self._withheld: list[CdpFrame] = []
        self._closed = asyncio.Event()

    async def start(self) -> None:
        """Open the connection and begin reading; every consumer shares what this returns."""
        if self._ws is not None:
            raise RuntimeError("browser session connection is already open")
        self._ws = await websockets.connect(
            self._url, max_size=None, ping_interval=None, close_timeout=_CLOSE_TIMEOUT_SECONDS
        )
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        """Close the connection and fail anything still waiting on it."""
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
        ws, self._ws = self._ws, None
        # Waiters are released before the close handshake, which a dead engine never answers.
        self._mark_closed(CdpConnectionClosed(_CONNECTION_CLOSED))
        if ws is not None:
            await ws.close()

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

    def subscribe(self, sink: FrameSink) -> Callable[[], None]:
        """Register a non-blocking sink for the open stream; returns its remover.

        The open stream is every event and reply that no attach() owner claims.
        """
        entry: Subscription = (sink, None)
        self._sinks.append(entry)

        def _remove() -> None:
            if entry in self._sinks:
                self._sinks.remove(entry)

        return _remove

    async def attach(self, target_id: str, owner: FrameSink) -> str:
        """Attach a page session that belongs to owner alone and return its CDP session id.

        The engine announces the attach with a connection-level attachedToTarget
        just before replying; that announcement and every frame on the session go
        to owner, never to a client sharing the connection, which would adopt it.
        """
        message: CdpFrame = {
            "method": "Target.attachToTarget",
            "params": {"targetId": target_id, "flatten": True},
        }
        self._attaching[target_id] = self._attaching.get(target_id, 0) + 1
        waiting = True

        def settle(reply: CdpFrame | None) -> None:
            self._settle_attach(target_id, owner if waiting else _discard, reply)

        try:
            reply = await self._send_tracked(message, on_reply=settle)
        except BaseException:
            waiting = False
            raise
        if "error" in reply:
            raise CdpCommandError(reply["error"])
        return str(reply["result"]["sessionId"])

    async def detach(self, session_id: str) -> None:
        """Detach a session attach() opened, then drop its owner's claim on it."""
        try:
            await self.send_raw("Target.detachFromTarget", {"sessionId": session_id})
        finally:
            self._sinks = [entry for entry in self._sinks if entry[1] != session_id]

    async def send_raw(
        self,
        method: str,
        params: CdpFrame | None = None,
        session_id: str | None = None,
    ) -> CdpFrame:
        """Issue one CDP command and return its result.

        Raises CdpCommandError carrying the engine's own error object, so a failed
        command is a failure rather than an empty result the caller misreads.
        """
        message: CdpFrame = {"method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        reply = await self._send_tracked(message)
        if "error" in reply:
            raise CdpCommandError(reply["error"])
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

    async def _send_tracked(
        self, message: CdpFrame, *, on_reply: ReplyHook | None = None
    ) -> CdpFrame:
        mux_id = self._allocate()
        message["id"] = mux_id
        future: asyncio.Future[CdpFrame] = asyncio.get_running_loop().create_future()
        self._pending[mux_id] = future
        if on_reply is not None:
            self._reply_hooks[mux_id] = on_reply
        try:
            await self._write(message)
        except BaseException:
            self._pending.pop(mux_id, None)
            hook = self._reply_hooks.pop(mux_id, None)
            if hook is not None:
                hook(None)
            raise
        try:
            return await future
        except BaseException:
            # A caller that gave up is no longer owed a reply: a late one is dropped
            # as nobody's, while its reply hook stays to settle what it started.
            self._pending.pop(mux_id, None)
            raise

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
            self._dispatch_reply(message_id, frame)
            return
        announced = _announced_target(frame)
        if announced is not None and announced in self._attaching:
            self._withheld.append(frame)
            return
        self._fan_out(frame)

    def _dispatch_reply(self, message_id: int, frame: CdpFrame) -> None:
        pending = self._pending.pop(message_id, None)
        hook = self._reply_hooks.pop(message_id, None)
        if hook is not None:
            hook(frame)
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
                frame.pop("id")
            else:
                frame["id"] = client_id
            self._deliver(reply_to, frame)
            return
        if hook is None:
            # A client handed a reply wearing an id the mux allocated could take it
            # for the answer to its own command of the same number.
            log.warning(
                f"{LogTag.BROWSER} browser session dropped a reply nobody awaits",
                error_type="OrphanCdpReply",
            )

    def _settle_attach(self, target_id: str, owner: FrameSink, reply: CdpFrame | None) -> None:
        """Claim an attach's session for owner and release what was withheld; runs in the read loop.

        reply is None when the command never left, so no session exists to claim.
        The owner _discard means the caller gave up: the session is let go unheard.
        """
        remaining = self._attaching[target_id] - 1
        if remaining:
            self._attaching[target_id] = remaining
        else:
            del self._attaching[target_id]
        result = reply.get("result") if reply is not None else None
        session_id = result.get("sessionId") if isinstance(result, dict) else None
        if isinstance(session_id, str):
            self._sinks.append((owner, session_id))
            if owner is _discard:
                spawn_background_task(self._detach_abandoned(session_id))
        # Claimed first, so the owner's own announcement routes to it like any of its frames.
        withheld, self._withheld = self._withheld, []
        for frame in withheld:
            if _announced_target(frame) in self._attaching:
                self._withheld.append(frame)
            else:
                self._fan_out(frame)

    async def _detach_abandoned(self, session_id: str) -> None:
        # A connection closing under it has detached everything already.
        with contextlib.suppress(CdpConnectionClosed):
            await self.detach(session_id)

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
        self._reply_hooks.clear()
        for future in pending.values():
            if not future.done():
                future.set_exception(exc)


def _discard(_frame: CdpFrame) -> None:
    """Own a session whose attach was abandoned, so its frames go nowhere."""


class CDPTimeoutError(RuntimeError):
    """Raised when a CDP call outruns its budget — the engine is wedged, not busy."""


async def cdp_call(
    cdp: CdpTransport,
    method: str,
    params: CdpFrame | None = None,
    *,
    session_id: str | None = None,
    timeout: float = CDP_CALL_TIMEOUT_SECONDS,
) -> CdpFrame:
    """One CDP round-trip, bounded by timeout: the single place the host talks to an engine.

    A wedged engine raises CDPTimeoutError instead of suspending its caller forever.
    """
    try:
        return await asyncio.wait_for(
            cdp.send_raw(method, params, session_id=session_id), timeout=timeout
        )
    except TimeoutError as exc:
        log.error(
            f"{LogTag.BROWSER} browser host CDP call timed out",
            error_type="CDPTimeoutError",
            browser={"cdp_method": method, "timeout_seconds": timeout},
        )
        raise CDPTimeoutError(method) from exc


async def cdp_attach(mux: CdpMux, target_id: str, owner: FrameSink, *, timeout: float) -> str:
    """CdpMux.attach bounded by timeout, failing as a CDP call does when the engine is wedged."""
    try:
        return await asyncio.wait_for(mux.attach(target_id, owner), timeout=timeout)
    except TimeoutError as exc:
        raise CDPTimeoutError("Target.attachToTarget") from exc


async def cdp_detach(mux: CdpMux, session_id: str, *, timeout: float) -> None:
    """CdpMux.detach bounded by timeout, failing as a CDP call does when the engine is wedged."""
    try:
        await asyncio.wait_for(mux.detach(session_id), timeout=timeout)
    except TimeoutError as exc:
        raise CDPTimeoutError("Target.detachFromTarget") from exc
