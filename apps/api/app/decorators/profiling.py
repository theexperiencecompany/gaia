"""
Clean and simple profiling decorator using pyinstrument.

This module provides a lightweight decorator that can profile both synchronous and
asynchronous functions. Profiling is optional and controlled via environment variables.

Features:
- Works with both async and sync functions
- Simple environment-based enable/disable
- Proper error handling and race condition prevention
- Clean logging output

Environment Variables:
    ENABLE_PROFILING: bool = False (must be explicitly enabled)
    PROFILING_SAMPLE_RATE: float = 1.0 (100% sampling rate)

Usage:
    @profile_function
    async def my_async_function():
        pass

    @profile_function
    def my_sync_function():
        pass
"""

import functools
import inspect
import random
from typing import Callable, Optional

from app.config.loggers import profiler_logger as logger
from app.config.settings import settings

Profiler = None
try:
    from pyinstrument import Profiler as _Profiler

    Profiler = _Profiler
    PROFILING_AVAILABLE = True
except ImportError:
    logger.warning("pyinstrument not available - profiling disabled")
    PROFILING_AVAILABLE = False


def profile_function(
    func: Optional[Callable] = None,
    *,
    sample_rate: Optional[float] = None,
) -> Callable:
    """
    Simple profiling decorator for both async and sync functions.

    Args:
        func: The function to profile (when used as decorator)
        sample_rate: Override global sampling rate (0.0 to 1.0)

    Returns:
        Decorated function or decorator function
    """

    def decorator(f: Callable) -> Callable:
        # Early return if profiling not available or disabled
        if not PROFILING_AVAILABLE or not settings.ENABLE_PROFILING:
            return f

        # Get effective sample rate
        effective_sample_rate = (
            sample_rate if sample_rate is not None else settings.PROFILING_SAMPLE_RATE
        )

        # Determine if function is async
        is_async = inspect.iscoroutinefunction(f)

        if is_async:

            @functools.wraps(f)
            async def async_wrapper(*args, **kwargs):
                # Apply sampling - skip profiling if random check fails
                # Non-cryptographic sampling: random.random() is safe here (Bandit B311 # nosec)
                if (
                    effective_sample_rate < 1.0
                    and random.random() >= effective_sample_rate  # nosec: B311
                ):
                    return await f(*args, **kwargs)

                profiler = None
                try:
                    if Profiler is not None:
                        profiler = Profiler()
                        profiler.start()
                    result = await f(*args, **kwargs)
                    return result
                except Exception:
                    # Re-raise the original exception, profiling error logged separately
                    raise
                finally:
                    if profiler is not None:
                        try:
                            profiler.stop()
                            output = profiler.output_text()
                            logger.info(f"Profile for {f.__name__}:\n{output}")
                        except Exception as e:
                            logger.warning(
                                f"Failed to generate profile for {f.__name__}: {e}"
                            )

            return async_wrapper
        else:

            @functools.wraps(f)
            def sync_wrapper(*args, **kwargs):
                # Apply sampling - skip profiling if random check fails
                # Non-cryptographic sampling: random.random() is safe here (Bandit B311 # nosec)
                if (
                    effective_sample_rate < 1.0
                    and random.random() >= effective_sample_rate  # nosec: B311
                ):
                    return f(*args, **kwargs)

                profiler = None
                try:
                    if Profiler is not None:
                        profiler = Profiler()
                        profiler.start()
                    result = f(*args, **kwargs)
                    return result
                except Exception:
                    # Re-raise the original exception, profiling error logged separately
                    raise
                finally:
                    if profiler is not None:
                        try:
                            profiler.stop()
                            output = profiler.output_text()
                            logger.info(f"Profile for {f.__name__}:\n{output}")
                        except Exception as e:
                            logger.warning(
                                f"Failed to generate profile for {f.__name__}: {e}"
                            )

            return sync_wrapper

    # Handle both @profile_function and @profile_function() usage
    if func is None:
        return decorator
    else:
        return decorator(func)
