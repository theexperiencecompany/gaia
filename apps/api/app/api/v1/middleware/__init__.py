"""
API v1 Middleware package initialization.

Exposes main middleware classes, decorators, and utilities for easy import.
"""

from .auth import PostHogRequestContextMiddleware, WorkOSAuthMiddleware
from .logging import LoggingMiddleware, log_function_call
from .profiling import ProfilingMiddleware
from .rate_limiter import limiter
from .tiered_rate_limiter import (
    RateLimitExceededException,
    TieredRateLimiter,
    UsageInfo,
)

# `tiered_rate_limit` is deliberately NOT re-exported here: it lives in
# app/decorators/rate_limiting.py. A second copy in this package drifted and
# silently skipped rate limiting — import it from `app.decorators`.
__all__ = [
    "PostHogRequestContextMiddleware",
    "WorkOSAuthMiddleware",
    "LoggingMiddleware",
    "log_function_call",
    "ProfilingMiddleware",
    "limiter",
    "TieredRateLimiter",
    "RateLimitExceededException",
    "UsageInfo",
]
