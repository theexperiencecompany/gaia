"""
Request coalescing utility for preventing thundering herd on cache miss.

When multiple concurrent requests hit an expensive operation (like building
the tools list) simultaneously, only one request executes the work while
others wait for its result. This prevents redundant expensive work.

Usage:
    result = await coalesce_request(
        key="global_tools",
        factory=_build_global_tools
    )
"""

import asyncio
from typing import Any, Coroutine, Callable, Dict, TypeVar

from app.config.loggers import app_logger as logger

T = TypeVar("T")

# In-flight requests: maps key -> task
_pending_requests: Dict[str, asyncio.Task[Any]] = {}
_lock = asyncio.Lock()


async def coalesce_request(
    key: str, factory: Callable[[], Coroutine[Any, Any, T]]
) -> T:
    """
    Coalesce concurrent requests for the same key.

    First request runs the factory function, subsequent concurrent requests
    wait for and share the same result. This prevents thundering herd when
    multiple requests hit a cache miss simultaneously.

    Args:
        key: Unique identifier for this operation (e.g., "global_tools")
        factory: Async function that produces the result

    Returns:
        Result from factory (shared across all concurrent requests)

    Example:
        async def _build_tools():
            # Expensive operation
            return await fetch_and_build_tools()

        # Multiple concurrent calls will only run _build_tools() once
        tools = await coalesce_request("tools", _build_tools)
    """
    async with _lock:
        if key in _pending_requests:
            # Another request is already running, wait for it
            logger.debug(f"Request coalescing: waiting for in-flight '{key}'")
            task = _pending_requests[key]
        else:
            # We're the first, create the task
            logger.debug(f"Request coalescing: starting new request for '{key}'")
            coro = factory()
            task = asyncio.create_task(coro)
            _pending_requests[key] = task

    try:
        result = await task
        return result
    finally:
        # Clean up only if we're the task owner
        async with _lock:
            if key in _pending_requests and _pending_requests[key] is task:
                del _pending_requests[key]
