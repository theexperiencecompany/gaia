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

from app.config.loggers import request_logger as logger
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
    """Middleware to log API request and response details."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed_ms = (time.time() - start) * 1000

        # safe lookup of client IP
        if request.client:
            client_ip = request.client.host
        else:
            # fallback to header or literal
            client_ip = request.headers.get("x-forwarded-for", "unknown")

        # status phrase
        try:
            phrase = HTTPStatus(response.status_code).phrase
        except ValueError:
            phrase = "Unknown"

        logger.info(
            f"[{client_ip}] {request.method} {request.url.path} "
            f"{response.status_code} {phrase} - {elapsed_ms:.2f}ms"
        )
        return response
