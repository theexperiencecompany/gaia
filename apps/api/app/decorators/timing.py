"""Timing decorators that log execution time for async and sync functions.

Lightweight alternative to the profiling decorators when you only need timing.
"""

from collections.abc import Awaitable, Callable
import functools
import inspect
import time
from typing import ParamSpec, TypeVar, cast

from app.constants.log_tags import LogTag
from shared.py.wide_events import log

P = ParamSpec("P")
R = TypeVar("R")


def async_timer(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Timing decorator for async functions."""

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info(
                f"{LogTag.API} ⏱️ completed", func_name=func.__name__, execution_time=execution_time
            )
            if execution_time > 1.0:
                log.warning(
                    "slow function",
                    function=func.__name__,
                    duration_ms=round(execution_time * 1000, 2),
                )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(
                f"{LogTag.API} ⏱️ failed",
                func_name=func.__name__,
                execution_time=execution_time,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    return wrapper


def sync_timer(func: Callable[P, R]) -> Callable[P, R]:
    """Timing decorator for sync functions."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info(
                f"{LogTag.API} ⏱️ completed", func_name=func.__name__, execution_time=execution_time
            )
            if execution_time > 1.0:
                log.warning(
                    "slow function",
                    function=func.__name__,
                    duration_ms=round(execution_time * 1000, 2),
                )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(
                f"{LogTag.API} ⏱️ failed",
                func_name=func.__name__,
                execution_time=execution_time,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise

    return wrapper


def timer(
    func: Callable[P, Awaitable[R]] | Callable[P, R],
) -> Callable[P, Awaitable[R]] | Callable[P, R]:
    """Universal timing decorator for both async and sync functions."""
    if inspect.iscoroutinefunction(func):
        return async_timer(cast(Callable[P, Awaitable[R]], func))
    return sync_timer(cast(Callable[P, R], func))
