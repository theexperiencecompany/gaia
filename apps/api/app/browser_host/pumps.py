"""Shared bidirectional websocket pump for the CDP proxy, the screencast and the live-view relay.

Every bridge runs its directions concurrently and must tear down cleanly the
moment one side closes: a client leaving or the engine closing its socket is an
expected end, not an error to propagate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Sequence

from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocket, WebSocketState
from websockets.exceptions import ConnectionClosed


def is_disconnect(exc: BaseException, sockets: Sequence[WebSocket] = ()) -> bool:
    """Whether exc is an ordinary peer close: the client gone or the engine's socket closed.

    Starlette raises a bare RuntimeError when a socket is used after it closed,
    so one counts as a disconnect only when one of sockets really has closed.
    """
    if isinstance(exc, ConnectionClosed | WebSocketDisconnect):
        return True
    return type(exc) is RuntimeError and any(
        WebSocketState.DISCONNECTED in (ws.client_state, ws.application_state) for ws in sockets
    )


async def pump_until_first_close(
    *coros: Awaitable[None], sockets: Sequence[WebSocket] = ()
) -> None:
    """Run every direction; when one ends, cancel the rest and finish.

    A real error (anything but a peer disconnect on one of sockets) from any
    direction is re-raised so the caller's logging and teardown see it.
    """
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not is_disconnect(exc, sockets):
                raise exc
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
