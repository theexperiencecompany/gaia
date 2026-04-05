"""
Request timeout middleware.

Pure ASGI middleware (not BaseHTTPMiddleware) using anyio structured concurrency.
Cancels HTTP requests that exceed a time limit and returns 504 Gateway Timeout.

SSE, WebSocket, and stream paths are excluded — they are long-lived by design.
"""

from collections.abc import MutableMapping
from typing import Any

import anyio
from fastapi.responses import JSONResponse
from shared.py.wide_events import log
from starlette.types import ASGIApp, Receive, Scope, Send

TIMEOUT_EXCLUDE_PREFIXES: tuple[str, ...] = (
    "/api/v1/chat-stream",
    "/api/v1/bot/chat-stream",
    "/api/v1/ws/",
    "/api/v1/stream/",
    "/api/v1/sse/",
)

DEFAULT_TIMEOUT_SECONDS: float = 300.0  # 5 minutes — enough for long agent runs


class RequestTimeoutMiddleware:
    """Abort HTTP requests that exceed a time limit.

    Uses anyio.move_on_after instead of asyncio.wait_for to avoid the
    BaseHTTPMiddleware cancellation bug in Starlette.
    """

    def __init__(
        self,
        app: ASGIApp,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        exclude_prefixes: tuple[str, ...] = TIMEOUT_EXCLUDE_PREFIXES,
    ) -> None:
        self.app = app
        self.timeout = timeout
        self.exclude_prefixes = exclude_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in self.exclude_prefixes):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        with anyio.move_on_after(self.timeout) as cancel_scope:
            await self.app(scope, receive, send_wrapper)

        if cancel_scope.cancelled_caught:
            if not response_started:
                response = JSONResponse(
                    status_code=504,
                    content={
                        "error": "request_timeout",
                        "detail": f"Request exceeded {self.timeout}s timeout",
                    },
                    headers={"Retry-After": "60"},
                )
                await response(scope, receive, send)
            else:
                log.warning(
                    f"Request to {path} timed out after {self.timeout}s "
                    "but response already started — connection may be broken"
                )
