"""
API v1 Middleware package initialization.

Exposes main middleware classes, decorators, and utilities for easy import.
"""

from .auth import WorkOSAuthMiddleware
from .logging import LoggingMiddleware, log_function_call
from .profiling import ProfilingMiddleware
from .rate_limiter import limiter
from .tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
    UsageInfo,
    tiered_rate_limit,
)

__all__ = [
    "LoggingMiddleware",
    "ProfilingMiddleware",
    "RateLimitExceededException",
    "TieredRateLimiter",
    "UsageInfo",
    "WorkOSAuthMiddleware",
    "limiter",
    "log_function_call",
    "tiered_rate_limit",
]
