"""
API v1 Middleware package initialization.

Exposes main middleware classes, decorators, and utilities for easy import.
"""

from .auth import WorkOSAuthMiddleware
from .logging import LoggingMiddleware, log_function_call
from .profiling import ProfilingMiddleware
from .rate_limiter import limiter
from .tiered_rate_limiter import (
    TieredRateLimiter,
    tiered_rate_limit,
    RateLimitExceededException,
    UsageInfo,
)

__all__ = [
    "WorkOSAuthMiddleware",
    "LoggingMiddleware",
    "log_function_call",
    "ProfilingMiddleware",
    "limiter",
    "TieredRateLimiter",
    "tiered_rate_limit",
    "RateLimitExceededException",
    "UsageInfo",
]
