"""Catch-all that turns a crash into the envelope while CORS can still see it.

Starlette answers an uncaught exception in ServerErrorMiddleware, which wraps
the whole application — outside CORSMiddleware. The 500 envelope it returns
therefore carries no Access-Control-Allow-Origin, so a browser refuses to read
it. This middleware is added innermost, inside CORS, and converts the exception
there; the outer handler stays as a last resort.

Pure ASGI, not BaseHTTPMiddleware: the latter re-raises through its own task
group and would reintroduce the layering this exists to avoid.
"""

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1.middleware.asgi_scope import AsgiMessage, AsgiScope
from app.core.unhandled_errors import capture_unhandled_exception, internal_error_response
from shared.py.wide_events import log


class UnhandledExceptionMiddleware:
    """Answer an uncaught exception with the 500 envelope, inside CORS."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        parsed = AsgiScope.model_validate(scope)
        if parsed.type != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if AsgiMessage.model_validate(message).type == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            # Once the status line is on the wire there is no envelope to send;
            # let it propagate so ServerErrorMiddleware tears the connection down.
            if response_started:
                raise
            # LoggingMiddleware's except path records the crash for requests
            # that reach it; this one never does, because the exception stops
            # here. Record it so the wide event still names the failure.
            log.error(
                "unhandled_exception",
                error_type=type(exc).__name__,
                error=str(exc),
                path=parsed.path,
            )
            capture_unhandled_exception(Request(scope), exc)
            envelope = internal_error_response()
            # Response.__call__ only ever sends, so a mutant that drops
            # ``receive`` cannot change what the client gets.
            await envelope(scope, receive, send)  # pragma: no mutate -- see comment above
