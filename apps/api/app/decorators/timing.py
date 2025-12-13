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

import functools
import inspect
import time
from typing import Callable

from app.config.loggers import app_logger as logger


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
            logger.info(f"⏱️  {func.__name__} completed in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"⏱️  {func.__name__} failed after {execution_time:.3f}s: {e}")
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
            logger.info(f"⏱️  {func.__name__} completed in {execution_time:.3f}s")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"⏱️  {func.__name__} failed after {execution_time:.3f}s: {e}")
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
    else:
        return sync_timer(func)


def detailed_timer(include_args: bool = False, include_kwargs: bool = False):
    """
    Timing decorator factory that can include function arguments in logs.

    Args:
        include_args: Whether to include positional arguments in logs
        include_kwargs: Whether to include keyword arguments in logs

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                arg_info = ""
                if include_args and args:
                    arg_info += f" args={args[:3]}{'...' if len(args) > 3 else ''}"
                if include_kwargs and kwargs:
                    arg_info += f" kwargs={dict(list(kwargs.items())[:2])}{'...' if len(kwargs) > 2 else ''}"

                try:
                    result = await func(*args, **kwargs)
                    execution_time = time.time() - start_time
                    logger.info(
                        f"⏱️  {func.__name__}{arg_info} completed in {execution_time:.3f}s"
                    )
                    return result
                except Exception as e:
                    execution_time = time.time() - start_time
                    logger.error(
                        f"⏱️  {func.__name__}{arg_info} failed after {execution_time:.3f}s: {e}"
                    )
                    raise

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                arg_info = ""
                if include_args and args:
                    arg_info += f" args={args[:3]}{'...' if len(args) > 3 else ''}"
                if include_kwargs and kwargs:
                    arg_info += f" kwargs={dict(list(kwargs.items())[:2])}{'...' if len(kwargs) > 2 else ''}"

                try:
                    result = func(*args, **kwargs)
                    execution_time = time.time() - start_time
                    logger.info(
                        f"⏱️  {func.__name__}{arg_info} completed in {execution_time:.3f}s"
                    )
                    return result
                except Exception as e:
                    execution_time = time.time() - start_time
                    logger.error(
                        f"⏱️  {func.__name__}{arg_info} failed after {execution_time:.3f}s: {e}"
                    )
                    raise

            return sync_wrapper

    return decorator


# Convenience decorators
def quick_timer(func: Callable) -> Callable:
    """Quick timing decorator with minimal overhead."""
    return timer(func)


def verbose_timer(func: Callable) -> Callable:
    """Timing decorator that includes function arguments."""
    return detailed_timer(include_args=True, include_kwargs=True)(func)
