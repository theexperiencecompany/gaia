"""
Logging decorators and middleware for request logging functionality.

This module provides middleware classes for logging HTTP requests and responses,
as well as function-level logging decorators for performance monitoring and
debugging. Implements the Wide Event / Canonical Log Line pattern for
comprehensive request tracing.
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
    Middleware to log API requests using the Wide Event pattern.

    Creates a comprehensive wide event per request capturing:
    - Request context (method, path, client IP, user agent, trace ID)
    - Response context (status code, duration)
    - User context (user ID, subscription tier - when available)
    - Performance metrics (duration in ms)

    The wide event is stored in request context and can be enriched
    by downstream handlers with business-specific data.
    """

    # Paths to skip wide event logging (health checks, static files)
    SKIP_PATHS = frozenset({
        "/",
        "/ping",
        "/health",
        "/api/v1/",
        "/api/v1/ping",
        "/favicon.ico",
        "/static",
    })

    async def dispatch(self, request: Request, call_next):
        start = time.time()

        # Skip wide events for health checks and static files
        path = request.url.path
        if path in self.SKIP_PATHS or path.startswith("/static"):
            response = await call_next(request)
            return response

        # Create wide event for this request
        event = WideEvent(service="gaia-api")

        # Extract trace ID from header or generate one
        trace_id = request.headers.get("x-trace-id") or request.headers.get(
            "x-request-id"
        ) or str(uuid4())

        # Get client IP safely
        client_ip = (
            request.client.host
            if request.client
            else request.headers.get("x-forwarded-for", "unknown")
        )

        # Set request context
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
        request.state.trace_id = trace_id
        set_current_event(event)

        # Process the request
        response = None
        try:
            response = await call_next(request)

            # Set response context
            event.set_response_context(status_code=response.status_code)

            # Determine outcome
            if response.status_code >= 500:
                event.outcome = "error"
            elif response.status_code >= 400:
                event.outcome = "client_error"
            else:
                event.outcome = "success"

            return response

        except Exception as e:
            # Capture exception in wide event
            elapsed_ms = (time.time() - start) * 1000
            event.duration_ms = elapsed_ms
            event.set_error(exception=e)
            event.outcome = "error"
            raise

        finally:
            # Enrich with user context if available
            if hasattr(request.state, "user") and request.state.user:
                user = request.state.user
                event.set_user_context(user=user)

            # Calculate final duration
            if event.duration_ms is None:
                event.duration_ms = (time.time() - start) * 1000

            # Emit the wide event (sampling handled internally)
            wide_logger.emit(event)

            # Also emit the simple log line for backward compatibility
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

            # Clear the context
            clear_current_event()
