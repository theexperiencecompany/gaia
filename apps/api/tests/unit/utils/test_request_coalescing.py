"""Unit tests for ``app.utils.request_coalescing`` — one factory run per key."""

import asyncio
from unittest.mock import AsyncMock

from app.utils.request_coalescing import coalesce_request


async def test_concurrent_callers_share_one_factory_run() -> None:
    """The thundering-herd contract: N concurrent callers for one key run the
    factory exactly once and all receive its result (the pending-task branch
    is what the second caller takes)."""
    calls = 0
    started = asyncio.Event()

    async def factory() -> int:
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.sleep(0.05)
        return 42

    first = asyncio.create_task(coalesce_request("tools", factory))
    await started.wait()
    second = asyncio.create_task(coalesce_request("tools", factory))

    results = await asyncio.gather(first, second)
    assert results == [42, 42]
    assert calls == 1


async def test_distinct_keys_do_not_coalesce() -> None:
    factory_a = AsyncMock(return_value="a")
    factory_b = AsyncMock(return_value="b")

    results = await asyncio.gather(
        coalesce_request("key-a", factory_a),
        coalesce_request("key-b", factory_b),
    )

    assert results == ["a", "b"]
    factory_a.assert_awaited_once()
    factory_b.assert_awaited_once()


async def test_second_caller_after_completion_runs_factory_again() -> None:
    """Coalescing is per-in-flight-request, not a permanent cache: once the
    first run completes and cleans up, a new call runs the factory again."""
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        return f"run-{calls}"

    assert await coalesce_request("key", factory) == "run-1"
    assert await coalesce_request("key", factory) == "run-2"
    assert calls == 2
