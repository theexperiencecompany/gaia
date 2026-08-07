"""
Logging decorators and middleware for request-level wide event logging.

Every HTTP request produces exactly ONE structured JSON event (the wide event)
emitted at request completion. Route handlers and service functions call
log.set() to add business context; log.warning() / log.error() add entries
to warnings[] / errors[] arrays on the same event.

The wide event is stored in a ContextVar so each async request is fully
isolated — no cross-request data leakage.

Environment characteristics (env, service, commit) are injected into every
event at the middleware level — no per-file boilerplate required.
"""

import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from http import HTTPStatus
import time
from typing import ParamSpec, TypeVar, cast

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config.loggers import request_logger
from shared.py.wide_events import log as wide_log

_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}

P = ParamSpec("P")
R = TypeVar("R")


def log_function_call(
    func: Callable[P, Awaitable[R]] | Callable[P, R],
) -> Callable[P, Awaitable[R]] | Callable[P, R]:
    """
    Decorator that logs function calls with execution time tracking.

    Slow functions (>1s) emit a warning that is captured in the wide event's
    warnings[] array. Exceptions emit an error into errors[].

    Supports both sync and async functions.
    """

    func_name = func.__qualname__

    if asyncio.iscoroutinefunction(func):
        async_func = cast(Callable[P, Awaitable[R]], func)

        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start_time = time.time()
            try:
                result = await async_func(*args, **kwargs)
                execution_time = time.time() - start_time
                if execution_time > 1.0:
                    wide_log.warning(
                        "slow function",
                        function=func_name,
                        duration_ms=round(execution_time * 1000, 2),
                    )
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                wide_log.error(
                    "function failed",
                    function=func_name,
                    duration_ms=round(execution_time * 1000, 2),
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise

        return async_wrapper

    sync_func = cast(Callable[P, R], func)

    @wraps(func)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start_time = time.time()
        try:
            result = sync_func(*args, **kwargs)
            execution_time = time.time() - start_time
            if execution_time > 1.0:
                wide_log.warning(
                    "slow function",
                    function=func_name,
                    duration_ms=round(execution_time * 1000, 2),
                )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            wide_log.error(
                "function failed",
                function=func_name,
                duration_ms=round(execution_time * 1000, 2),
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    return sync_wrapper


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware that emits one structured wide event per HTTP request.

    Every scalar field is available for LogQL filtering in Grafana without any
    pre-processing — just add `| json` to any query. The `errors`/`warnings`
    arrays are the exception: bare `| json` drops arrays outright, and they are
    absent (not empty) when nothing was recorded, so `| errors != "[]"` matches
    every line. Reach into them with an explicit JSON expression instead.

    LogQL examples:
        # Requests that had any warning (even if 200 OK)
        {service="gaia-backend"} | json first_warning="warnings[0].msg" | first_warning != ""

        # Requests that had any error logged mid-flight
        {service="gaia-backend"} | json first_error="errors[0].msg" | first_error != ""

        # Every failed request — final_level folds in the HTTP status, so this
        # also catches a 5xx that logged nothing
        {service="gaia-backend"} | json | message="http_request" | final_level =~ "ERROR|CRITICAL"

        # All chat requests by duration
        {service="gaia-backend"} | json | path =~ "/api/v1/chat.*" | unwrap duration_ms

        # Errors on a specific commit
        {service="gaia-backend"} | json | commit="abc1234"
            | json first_error="errors[0].msg" | first_error != ""

        # Requests by specific user
        {service="gaia-backend"} | json | user_id="<id>"
    """

    _SKIP_PATHS = frozenset(["/health", "/metrics", "/favicon.ico"])

    @staticmethod
    def _attach_user_context(request: Request) -> None:
        """Merge the authenticated user's identity into the wide event.

        Called after ``call_next``: the auth middlewares run inside this
        boundary and populate ``request.state.user`` during it. Attaching from
        state here guarantees user identity on every event regardless of what
        the handler did; fields a handler set explicitly win over the
        automatic ones.
        """
        user = getattr(request.state, "user", None)
        if not user:
            return
        auto = {"id": user.get("user_id")} if user.get("user_id") else {}
        if not auto:
            return
        wide_log.set(user={**auto, **wide_log.get().get("user", {})})

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        # Fresh wide event for this request — ContextVar isolated per async task
        wide_log.reset()

        # Honour an incoming trace-id so distributed callers can correlate logs.
        incoming_trace_id = request.headers.get("x-trace-id")
        if incoming_trace_id:
            wide_log.set(trace_id=incoming_trace_id)

        # Capture request size from Content-Length header (available without reading body)
        try:
            request_size_bytes = int(request.headers.get("content-length", 0))
        except (ValueError, TypeError):
            request_size_bytes = 0

        start = time.time()
        status_code = 500
        status_phrase = "Internal Server Error"
        response = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            try:
                status_phrase = HTTPStatus(response.status_code).phrase
            except ValueError:
                status_phrase = "Unknown"
        except Exception as exc:
            wide_log.error(
                "unhandled_exception",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            wide_log.set(outcome="failed")
            # Still emit the wide event before re-raising
            duration_ms = round((time.time() - start) * 1000, 2)
            wide_log.set(final_level="ERROR")
            self._attach_user_context(request)
            wide_event_context = wide_log.get()
            client_ip = (
                request.client.host
                if request.client
                else request.headers.get("x-forwarded-for", "unknown")
            )
            context = {
                **wide_event_context,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "status_phrase": "Internal Server Error",
                "duration_ms": duration_ms,
                "client_ip": client_ip,
                "request_id": request.headers.get("x-request-id"),
                "user_agent": request.headers.get("user-agent"),
                "request_size_bytes": request_size_bytes,
            }
            request_logger.bind(**context).log("ERROR", "http_request")
            raise
        duration_ms = round((time.time() - start) * 1000, 2)

        client_ip = (
            request.client.host
            if request.client
            else request.headers.get("x-forwarded-for", "unknown")
        )

        # Final level = worst of: HTTP status code + explicit warning/error calls
        level = wide_log.get_max_level()
        if status_code >= 500:
            level = "ERROR"
        elif status_code >= 400 and _LEVEL_ORDER[level] < _LEVEL_ORDER["WARNING"]:
            level = "WARNING"

        # Store final_level before get() so it appears in the emitted JSON
        wide_log.set(final_level=level)

        # Merge all context accumulated by route handlers and services
        self._attach_user_context(request)
        wide_event_context = wide_log.get()

        context = {
            # --- Business context accumulated by handlers/services ---
            # Spread first so the authoritative HTTP values below always win.
            # env/service/commit are NOT spread here: the JSON sink stamps them
            # on every line (shared.py.logging._build_json_entry) and re-emits a
            # colliding app field as ctx_<key>, so the infra identity is
            # authoritative for real-time lines too, not just this one.
            **wide_event_context,
            # --- HTTP request characteristics (always authoritative) ---
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "status_phrase": status_phrase,
            "duration_ms": duration_ms,
            "client_ip": client_ip,
            "request_id": request.headers.get("x-request-id"),
            "user_agent": request.headers.get("user-agent"),
            "request_size_bytes": request_size_bytes,
            "response_size_bytes": int(response.headers.get("content-length", 0) or 0),
        }

        request_logger.bind(**context).log(level, "http_request")

        trace_id = wide_log.get().get("trace_id", "")
        if trace_id:
            response.headers["x-trace-id"] = trace_id

        return response
