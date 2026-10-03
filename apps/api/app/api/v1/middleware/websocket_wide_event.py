"""Wide-event boundary for WebSocket connections.

LoggingMiddleware is a BaseHTTPMiddleware and therefore only ever sees
http scope — Starlette passes websocket scope straight through the HTTP
middleware stack. A websocket connection therefore has no automatic canonical
event, and every handler used to open its own log_context() boundary by
hand. That is the same footgun per handler: forget the wrapper and the whole
connection is invisible in Loki, and no static check notices (the scanner
assumed websocket was covered like HTTP).

This is a pure ASGI middleware, not a BaseHTTPMiddleware: it intercepts
scope["type"] == "websocket" and wraps the entire connection lifetime in a
log_context() boundary, so a handler just calls log.set() exactly like
an HTTP handler. On close — normal, cancelled, or raised — the boundary emits
one canonical background_task line with outcome and duration_ms.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.v1.middleware.asgi_scope import AsgiScope
from shared.py.wide_events import log_context


class WebSocketWideEventMiddleware:
    """Emit one wide event per WebSocket connection, spanning its lifetime."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parsed = AsgiScope.model_validate(scope)
        if parsed.type != "websocket":
            await self.app(scope, receive, send)
            return

        # Mirror LoggingMiddleware: honour an incoming trace-id so distributed
        # callers can correlate the connection with the request that opened it.
        trace_id = parsed.header(b"x-trace-id")
        task = _task_name(parsed.path)
        async with log_context(task, trace_id=trace_id, path=parsed.path):
            await self.app(scope, receive, send)


def _task_name(path: str) -> str:
    """Return the boundary's unit-of-work name, derived from the connection path.

    Matched against the exact registered paths so a future device subroute
    is never silently mislabelled; an unknown path gets the generic name.
    """
    if path.rstrip("/") == "/api/v1/ws/device":
        return "device_ws_connection"
    return "ws_connection"
