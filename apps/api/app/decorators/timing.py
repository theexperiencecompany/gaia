"""
Timing decorators for measuring function execution time.

This module provides simple timing decorators that log execution time
for both async and sync functions. These are lightweight alternatives
to the full profiling decorators when you just need timing information.

Usage:
    @async_timer
    async def my_async_function():
        pass

    @sync_timer
    def my_sync_function():
        pass

    @timer  # Works for both async and sync
    def any_function():
        pass
"""

from collections.abc import Callable
import functools
import inspect
import time

from shared.py.wide_events import log


def async_timer(func: Callable) -> Callable:
    """
    Timing decorator for async functions.

    Args:
        func: The async function to time

    Returns:
        Decorated function that logs execution time
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info(f"⏱️  {func.__name__} completed in {execution_time:.3f}s")
            if execution_time > 1.0:
                log.warning(
                    "slow function",
                    function=func.__name__,
                    duration_ms=round(execution_time * 1000, 2),
                )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(f"⏱️  {func.__name__} failed after {execution_time:.3f}s: {e}")
            raise

    return wrapper


def sync_timer(func: Callable) -> Callable:
    """
    Timing decorator for sync functions.

    Args:
        func: The sync function to time

    Returns:
        Decorated function that logs execution time
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info(f"⏱️  {func.__name__} completed in {execution_time:.3f}s")
            if execution_time > 1.0:
                log.warning(
                    "slow function",
                    function=func.__name__,
                    duration_ms=round(execution_time * 1000, 2),
                )
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error(f"⏱️  {func.__name__} failed after {execution_time:.3f}s: {e}")
            raise

    return wrapper


def timer(func: Callable) -> Callable:
    """
    Universal timing decorator that works for both async and sync functions.

    Args:
        func: The function to time (async or sync)

    Returns:
        Decorated function that logs execution time
    """
    if inspect.iscoroutinefunction(func):
        return async_timer(func)
    return sync_timer(func)
