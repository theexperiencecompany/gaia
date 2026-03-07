"""
Logging decorators and middleware for request logging functionality.

This module provides middleware classes for logging HTTP requests and responses,
as well as function-level logging decorators for performance monitoring and
debugging.
"""

import time
from functools import wraps
from http import HTTPStatus

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config.loggers import get_contextual_logger, request_logger as logger


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
    """Middleware to emit one structured wide event per HTTP request.

    Every field is available for LogQL filtering in Grafana without any
    pre-processing — just add `| json` to any query.
    """

    # Paths that are too noisy and add no debugging value
    _SKIP_PATHS = frozenset(["/health", "/metrics", "/favicon.ico"])

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 2)

        client_ip = (
            request.client.host
            if request.client
            else request.headers.get("x-forwarded-for", "unknown")
        )

        try:
            status_phrase = HTTPStatus(response.status_code).phrase
        except ValueError:
            status_phrase = "Unknown"

        log = logger.bind(
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            status_phrase=status_phrase,
            duration_ms=duration_ms,
            client_ip=client_ip,
            request_id=request.headers.get("x-request-id"),
            user_agent=request.headers.get("user-agent"),
        )

        if response.status_code >= 500:
            log.error("http_request")
        elif response.status_code >= 400:
            log.warning("http_request")
        else:
            log.info("http_request")

        return response
