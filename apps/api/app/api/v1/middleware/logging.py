"""
Logging decorators and middleware for request logging functionality.

This module provides middleware classes for logging HTTP requests and responses,
as well as function-level logging decorators for performance monitoring and
debugging. The middleware automatically captures request context for all routes.
"""

import time
from functools import wraps
from http import HTTPStatus
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.loggers import (
    request_logger as logger,
    WideEvent,
    wide_logger,
    set_current_event,
    clear_current_event,
)
from app.config.logging import get_contextual_logger

# Import new simplified context
from shared.py.wide_events import (
    RequestContext,
    set_request_context,
    clear_request_context,
)


def log_function_call(func):
    """
    Decorator that logs function calls with execution time tracking.

    Features:
    - Logs function entry with limited argument logging
    - Tracks execution time and warns about slow functions (>1s)
    - Captures and logs exceptions while preserving stack traces
    - Uses contextual logger based on module name

    Usage:
        @log_function_call
        def process_data(data: dict):
            return processed_data

        @log_function_call
        async def fetch_api(url: str):
            return api_response
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        module_name = func.__module__.split(".")[-1] if func.__module__ else "unknown"
        func_logger = get_contextual_logger(
            module_name, function=func.__name__, logger_name=module_name.upper()
        )
        start_time = time.time()

        func_logger.debug(
            "Function called with args={} kwargs={}",
            args[:3] if len(args) > 3 else args,  # Limit args logging
            {k: v for k, v in list(kwargs.items())[:3]},  # Limit kwargs logging
        )

        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time

            if execution_time > 1.0:  # Log slow functions
                func_logger.warning(
                    "Function {} took {:.3f}s to execute", func.__name__, execution_time
                )
            else:
                func_logger.debug(
                    "Function {} completed in {:.3f}s", func.__name__, execution_time
                )

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            func_logger.error(
                "Function {} failed after {:.3f}s with error: {}",
                func.__name__,
                execution_time,
                str(e),
            )
            raise

    return wrapper


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically captures request context for all routes.

    Features:
    - Auto-captures: method, path, client_ip, user_agent, trace_id
    - Auto-captures user context when auth middleware runs
    - Sets both WideEvent (full) and RequestContext (simple) for downstream use
    - Emits wide event with tail-based sampling on completion

    Usage in routes/services:
        from shared.py.wide_events import log, get_request_context

        # Simple logging (auto-includes request context)
        log.info("user_action", action="login")

        # Access request context
        ctx = get_request_context()
        log.info("processing", user_id=ctx.user_id)
    """

    # Paths to skip logging (health checks, static files)
    SKIP_PATHS = frozenset({
        "/", "/ping", "/health",
        "/api/v1/", "/api/v1/ping",
        "/favicon.ico",
    })
    SKIP_PATH_PREFIXES = ("/static/",)

    async def dispatch(self, request: Request, call_next):
        start = time.time()

        # Skip for health checks and static files
        path = request.url.path
        if path in self.SKIP_PATHS or path.startswith(self.SKIP_PATH_PREFIXES):
            return await call_next(request)

        # Generate trace ID
        trace_id = (
            request.headers.get("x-trace-id") or
            request.headers.get("x-request-id") or
            str(uuid4())
        )

        # Get client IP
        client_ip = (
            request.client.host if request.client
            else request.headers.get("x-forwarded-for", "unknown")
        )

        # Create simplified request context (auto-available via get_request_context())
        req_ctx = RequestContext(
            trace_id=trace_id,
            method=request.method,
            path=path,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
        )
        set_request_context(req_ctx)

        # Create wide event for comprehensive logging
        event = WideEvent(service="gaia-api")
        event.set_request_context(
            method=request.method,
            path=path,
            query_params=dict(request.query_params) if request.query_params else None,
            client_ip=client_ip,
            user_agent=request.headers.get("user-agent"),
            trace_id=trace_id,
        )

        # Store in request state for downstream access
        request.state.wide_event = event
        request.state.request_context = req_ctx
        request.state.trace_id = trace_id
        set_current_event(event)

        # Process request
        response = None
        try:
            response = await call_next(request)

            # Update contexts with response info
            event.set_response_context(status_code=response.status_code)
            req_ctx.status_code = response.status_code
            req_ctx.duration_ms = (time.time() - start) * 1000

            # Set outcome
            if response.status_code >= 500:
                event.outcome = "error"
            elif response.status_code >= 400:
                event.outcome = "client_error"
            else:
                event.outcome = "success"

            return response

        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            event.duration_ms = elapsed_ms
            event.set_error(exception=e)
            event.outcome = "error"
            req_ctx.duration_ms = elapsed_ms
            raise

        finally:
            # Enrich with user context if available (set by auth middleware)
            if hasattr(request.state, "user") and request.state.user:
                user = request.state.user
                event.set_user_context(user=user)
                req_ctx.user_id = str(user.get("user_id") or user.get("_id") or "")
                req_ctx.subscription_tier = user.get("subscription_tier") or user.get("plan_type", "free")

            # Calculate final duration
            if event.duration_ms is None:
                event.duration_ms = (time.time() - start) * 1000
            if req_ctx.duration_ms is None:
                req_ctx.duration_ms = event.duration_ms

            # Emit wide event (sampling handled internally)
            wide_logger.emit(event)

            # Simple log line for backward compatibility
            status_code = event.status_code or (response.status_code if response else 500)
            try:
                phrase = HTTPStatus(status_code).phrase
            except ValueError:
                phrase = "Unknown"

            logger.info(
                f"[{client_ip}] {request.method} {path} "
                f"{status_code} {phrase} - {event.duration_ms:.2f}ms "
                f"trace_id={trace_id}"
            )

            # Clear contexts
            clear_current_event()
            clear_request_context()
