"""
Middleware configuration for the GAIA FastAPI application.

This module provides functions to configure middleware for the FastAPI application.
"""

import math
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import UJSONResponse
from limits import RateLimitItem
from limits.errors import StorageError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from workos import AsyncWorkOSClient

from app.api.v1.middleware.auth import PostHogRequestContextMiddleware, WorkOSAuthMiddleware
from app.api.v1.middleware.entitlement import EntitlementMiddleware
from app.api.v1.middleware.logging import LoggingMiddleware
from app.api.v1.middleware.profiling import ProfilingMiddleware
from app.api.v1.middleware.rate_limiter import RouterAwareSlowAPIMiddleware, limiter
from app.api.v1.middleware.timeout import RequestTimeoutMiddleware
from app.api.v1.middleware.unhandled_exception import UnhandledExceptionMiddleware
from app.api.v1.middleware.websocket_wide_event import WebSocketWideEventMiddleware
from app.config.settings import settings
from app.constants.http import RETRY_AFTER_HEADER
from app.core.bot_auth_middleware import BotAuthMiddleware
from app.schemas.errors import ErrorEnvelope, error_response
from shared.py.wide_events import log as wide_log

RATE_LIMIT_EXCEEDED_CODE = "rate_limit_exceeded"


def _retry_after_seconds(request: Request) -> int | None:
    """Whole seconds until the window that refused this request reopens.

    RateLimitExceeded carries no retry hint; the limiter records the window on
    request.state just before raising, and the full window length is the correct
    upper bound when storage cannot answer. Read the limiter off request.app.state
    — the module-level one queries a storage that never saw the request.
    """
    current_limit: tuple[RateLimitItem, list[str]] | None = getattr(
        request.state, "view_rate_limit", None
    )
    if current_limit is None:
        return None
    request_limiter: Limiter = request.app.state.limiter
    window, identifiers = current_limit
    try:
        reset_time, _remaining = request_limiter.limiter.get_window_stats(window, *identifiers)
    except StorageError:
        return window.get_expiry()
    return max(1, math.ceil(reset_time - time.time()))


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> UJSONResponse:
    """Render a rate-limit refusal as the envelope, with a real Retry-After.

    Deliberately sync: SlowAPIMiddleware answers the default limit through
    sync_check_limits, which discards a coroutine handler and silently falls
    back to slowapi's own error body.
    """
    retry_after = _retry_after_seconds(request)
    wide_log.warning(
        RATE_LIMIT_EXCEEDED_CODE,
        client_ip=request.client.host
        if request.client
        else request.headers.get("x-forwarded-for", "unknown"),
        path=request.url.path,
        method=request.method,
        retry_after=retry_after,
    )
    return error_response(
        429,
        ErrorEnvelope(message=str(exc.detail), code=RATE_LIMIT_EXCEEDED_CODE),
        headers=None if retry_after is None else {RETRY_AFTER_HEADER: str(retry_after)},
    )


def configure_middleware(app: FastAPI) -> None:
    """Configure middleware for the FastAPI application."""

    # Attach limiter to app state
    app.state.limiter = limiter

    # Decorator form, as in app_factory: add_exception_handler is typed
    # Callable[[Request, Exception], ...], which rejects a handler naming
    # the exception it's registered for.
    app.exception_handler(RateLimitExceeded)(rate_limit_handler)

    # Middleware stack, innermost -> outermost (add order == inner first).
    # LoggingMiddleware is outermost: it owns the wide event, so anything
    # outside its boundary is invisible in Loki (how timeouts used to vanish).

    # Rate limiting (innermost — a 429 flows up through the boundary)
    app.add_middleware(RouterAwareSlowAPIMiddleware)

    # Pyinstrument profiling for detailed call stack analysis
    app.add_middleware(ProfilingMiddleware)

    # Inside Logging on purpose: its cancel scope is contained in its own
    # __call__, so the synthesized 504 travels up as a normal response and gets
    # emitted. Outside Logging, the cancellation killed the emit for the slowest requests.
    app.add_middleware(RequestTimeoutMiddleware)

    # Inside CORS on purpose: runs after WorkOSAuthMiddleware sets request.state.user
    # and before any handler can spend money. Outside CORS, its 402 would carry no
    # Access-Control-Allow-Origin, so the browser couldn't read the checkout link.
    app.add_middleware(EntitlementMiddleware)

    # Crash catch-all, innermost inside CORS: Starlette's ServerErrorMiddleware
    # wraps CORS, so the 500 it returns carries no Access-Control-Allow-Origin
    # and a browser cannot read it. The app-level handler is the last resort.
    app.add_middleware(UnhandledExceptionMiddleware)

    # CORS (inside Logging so preflight rejections are visible in Loki)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_origin_regex=get_allowed_origin_regex(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
    )

    # PostHog's context must run after BOTH auth layers have populated
    # request.state.user, while still wrapping every downstream handler.
    app.add_middleware(PostHogRequestContextMiddleware)

    # Bot authentication (before WorkOS to allow bot auth to take precedence)
    app.add_middleware(BotAuthMiddleware)

    # WorkOS authentication — inside the logging boundary, so its rejections
    # are logged and its log.set()/log.error() calls reach the wide event.
    workos_client = AsyncWorkOSClient(
        api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
    )
    app.add_middleware(WorkOSAuthMiddleware, workos_client=workos_client)

    # Wide-event boundary — outermost (see block comment above).
    app.add_middleware(LoggingMiddleware)

    # Pure ASGI middleware (not BaseHTTPMiddleware, which drops websocket scope),
    # so add_middleware still works and the app keeps its FastAPI type. Wraps every
    # websocket connection in a log_context() boundary so handlers just call log.set().
    app.add_middleware(WebSocketWideEventMiddleware)


def get_allowed_origins() -> list[str]:
    """
    Get allowed origins for CORS based on environment.

    Returns:
        list[str]: List of allowed origins
    """
    # Always include configured frontend URL
    allowed_origins = [settings.FRONTEND_URL]

    # Desktop app embedded Next.js server ports (5174 is preferred; 5175-5180
    # are fallbacks when the preferred port is already in use)
    desktop_origins = [f"http://localhost:{port}" for port in range(5174, 5181)]

    # Add additional origins based on environment
    if settings.ENV == "production":
        # Only allow trusted HTTPS origins in production
        allowed_origins.extend(
            [
                "https://heygaia.io",
                "https://www.heygaia.io",
                "https://heygaia.app",
                # Cloudflare/OpenNext deployment of the web app (migration target).
                "https://cf.heygaia.io",
                *desktop_origins,
            ]
        )
    else:
        # Allow development origins
        allowed_origins.extend(
            [
                "http://localhost:3000",
                "http://192.168.138.215:5173",
                "https://192.168.13.215:5173",
                *desktop_origins,
            ]
        )

    return allowed_origins


def get_allowed_origin_regex() -> str | None:
    """Regex of additional allowed origins (dev-only).

    Matches any localhost origin on any port over http or https, with or
    without a subdomain — covers dev servers on arbitrary ports (e.g. worktree
    ports) and *.localhost tunnels alike.
    """
    if settings.ENV == "production":
        return None
    return r"^https?://([a-z0-9-]+\.)?localhost(?::\d+)?$"
