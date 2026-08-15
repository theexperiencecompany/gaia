"""Wide-event boundary for WebSocket connections.

``LoggingMiddleware`` is a ``BaseHTTPMiddleware`` and therefore only ever sees
``http`` scope — Starlette passes ``websocket`` scope straight through the HTTP
middleware stack. A websocket connection therefore has no automatic canonical
event, and every handler used to open its own ``log_context()`` boundary by
hand. That is the same footgun per handler: forget the wrapper and the whole
connection is invisible in Loki, and no static check notices (the scanner
assumed websocket was covered like HTTP).

This is a pure ASGI middleware, not a ``BaseHTTPMiddleware``: it intercepts
``scope["type"] == "websocket"`` and wraps the entire connection lifetime in a
``log_context()`` boundary, so a handler just calls ``log.set()`` exactly like
an HTTP handler. On close — normal, cancelled, or raised — the boundary emits
one canonical ``background_task`` line with ``outcome`` and ``duration_ms``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from shared.py.wide_events import log_context

ASGIApp = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


class WebSocketWideEventMiddleware:
    """Emit one wide event per WebSocket connection, spanning its lifetime."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        # Mirror LoggingMiddleware: honour an incoming trace-id so distributed
        # callers can correlate the connection with the request that opened it.
        trace_id = _header(scope, b"x-trace-id")
        task = _task_name(scope.get("path", ""))
        async with log_context(task, trace_id=trace_id, path=scope.get("path", "")):
            await self.app(scope, receive, send)


def _task_name(path: str) -> str:
    """The boundary's unit-of-work name, derived from the connection path.

    One name per route so dashboards keyed on ``task`` (as they are for every
    other boundary) keep their identity. Matched against the exact registered
    paths so a future device subroute can never be silently mislabelled as
    something else; an unknown websocket path still gets the generic name.
    """
    if path.rstrip("/") == "/api/v1/ws/device":
        return "device_ws_connection"
    return "ws_connection"


def _header(scope: dict[str, Any], key: bytes) -> str | None:
    """The value of a header in a raw ASGI scope, if present."""
    for name, value in scope.get("headers", ()):
        if name == key:
            return str(value.decode("latin-1"))
    return None
