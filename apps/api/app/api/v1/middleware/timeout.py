"""
Request timeout middleware.

Pure ASGI middleware (not BaseHTTPMiddleware) using anyio structured concurrency.
Cancels HTTP requests that exceed a time limit and returns 504 Gateway Timeout.

SSE, WebSocket, and conversation events paths are excluded — they are long-lived by design.
"""

import re

import anyio
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1.middleware.asgi_scope import AsgiMessage, AsgiScope
from app.constants.http import RETRY_AFTER_HEADER
from app.constants.log_tags import LogTag
from app.schemas.errors import ErrorEnvelope, error_response
from shared.py.wide_events import log

TIMEOUT_EXCLUDED_PATHS = re.compile(r"/api/v1/(ws/|sse/|conversations/[^/]+/events$)")

DEFAULT_TIMEOUT_SECONDS: float = 300.0  # 5 minutes — enough for long agent runs

#: Long enough that an immediate retry does not re-queue behind the same slow
#: work, short enough that a user who waits beats it.
TIMEOUT_RETRY_AFTER_SECONDS: int = 60


class RequestTimeoutMiddleware:
    """Abort HTTP requests that exceed a time limit.

    Uses anyio.move_on_after instead of asyncio.wait_for to avoid the
    BaseHTTPMiddleware cancellation bug in Starlette.
    """

    def __init__(
        self,
        app: ASGIApp,
        timeout: float | None = None,
    ) -> None:
        self.app = app
        # Resolved here, not as a default argument: a default is bound at class
        # definition, so the module constant would stop being the live budget.
        self.timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parsed = AsgiScope.model_validate(scope)
        if parsed.type != "http":
            await self.app(scope, receive, send)
            return

        path = parsed.path
        if TIMEOUT_EXCLUDED_PATHS.match(path):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if AsgiMessage.model_validate(message).type == "http.response.start":
                response_started = True
            await send(message)

        with anyio.move_on_after(self.timeout) as cancel_scope:
            await self.app(scope, receive, send_wrapper)

        if cancel_scope.cancelled_caught:
            if not response_started:
                response = error_response(
                    504,
                    ErrorEnvelope(
                        message=f"Request exceeded {self.timeout}s timeout", code="request_timeout"
                    ),
                    headers={RETRY_AFTER_HEADER: str(TIMEOUT_RETRY_AFTER_SECONDS)},
                )
                await response(scope, receive, send)
            else:
                log.warning(
                    f"{LogTag.API} Request timed out but response already started — "
                    "connection may be broken",
                    path=path,
                    timeout_s=self.timeout,
                )
