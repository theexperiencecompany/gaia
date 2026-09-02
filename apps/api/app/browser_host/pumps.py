"""Shared bidirectional websocket pump for the CDP proxy and the screencast.

Both bridges run two directions concurrently and must tear down cleanly the
moment either side closes — a normal client disconnect or Chromium closing its
socket is an expected end, not an error to propagate.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import websockets

# Starlette raises a bare RuntimeError (not a typed disconnect) when a websocket
# is read after it closed or before it was accepted — which happens normally
# during proxy teardown, when one direction closes the viewer socket while the
# other is still looping on receive(). Matched by exact message, and only for a
# plain RuntimeError, so an unrelated RuntimeError still propagates.
_STARLETTE_NOT_CONNECTED_MESSAGES = frozenset(
    {
        'WebSocket is not connected. Need to call "accept" first.',
        'Cannot call "receive" once a disconnect message has been received.',
    }
)


def is_disconnect(exc: BaseException) -> bool:
    """Whether ``exc`` is an ordinary peer close (client gone or Chromium closed)."""
    if isinstance(exc, websockets.exceptions.ConnectionClosed):
        return True
    # FastAPI's WebSocketDisconnect is checked by name so this module need not
    # import fastapi (the host may run without the web stack loaded).
    if type(exc).__name__ == "WebSocketDisconnect":
        return True
    return type(exc) is RuntimeError and str(exc) in _STARLETTE_NOT_CONNECTED_MESSAGES


async def pump_until_first_close(*coros: Coroutine[Any, Any, None]) -> None:
    """Run both pump directions; when either ends, cancel the other and finish.

    A real error (anything that is not a peer disconnect) from either direction
    is re-raised so the caller's logging/teardown sees it.
    """
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None and not is_disconnect(exc):
                raise exc
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
