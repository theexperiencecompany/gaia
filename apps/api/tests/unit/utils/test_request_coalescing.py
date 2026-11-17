"""coalesce_request: one shared run per key, which no single waiter's cancellation stops."""

import asyncio

import pytest

from app.utils import request_coalescing
from app.utils.request_coalescing import coalesce_request


async def test_concurrent_callers_share_one_run() -> None:
    release = asyncio.Event()
    runs = 0

    async def work() -> str:
        nonlocal runs
        runs += 1
        await release.wait()
        return "done"

    first = asyncio.ensure_future(coalesce_request("shared", work))
    second = asyncio.ensure_future(coalesce_request("shared", work))
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(first, second) == ["done", "done"]
    assert runs == 1


async def test_different_keys_run_separately() -> None:
    release = asyncio.Event()

    async def work(value: str) -> str:
        await release.wait()
        return value

    first = asyncio.ensure_future(coalesce_request("one", lambda: work("one")))
    second = asyncio.ensure_future(coalesce_request("two", lambda: work("two")))
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(first, second) == ["one", "two"]


@pytest.mark.regression
async def test_a_cancelled_waiter_leaves_the_run_going_for_the_others() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    runs = 0

    async def work() -> str:
        nonlocal runs
        runs += 1
        started.set()
        await release.wait()
        return "loaded"

    impatient = asyncio.ensure_future(coalesce_request("load", work))
    await started.wait()
    impatient.cancel()
    with pytest.raises(asyncio.CancelledError):
        await impatient
    survivor = asyncio.ensure_future(coalesce_request("load", work))
    await asyncio.sleep(0)
    release.set()

    assert await survivor == "loaded"
    assert runs == 1


async def test_a_finished_run_is_not_reused() -> None:
    runs = 0

    async def work() -> int:
        nonlocal runs
        runs += 1
        return runs

    assert await coalesce_request("again", work) == 1
    assert await coalesce_request("again", work) == 2


async def test_a_finished_run_leaves_the_registry() -> None:
    """Eviction bounds the registry; a leak would hold every key's result for the process's life."""

    async def work() -> str:
        return "done"

    await coalesce_request("evicted", work)
    await asyncio.sleep(0)

    assert request_coalescing._pending_requests == {}


def test_a_run_from_a_previous_loop_is_never_joined() -> None:
    """A task left pending by a dead loop is ignored, never awaited cross-loop."""
    other_loop = asyncio.new_event_loop()
    stale = other_loop.create_task(asyncio.Event().wait())
    request_coalescing._pending_requests[(other_loop, "loop-bound")] = stale

    async def work() -> str:
        return "fresh"

    try:
        assert asyncio.run(coalesce_request("loop-bound", work)) == "fresh"
    finally:
        request_coalescing._pending_requests.pop((other_loop, "loop-bound"), None)
        stale.cancel()
        other_loop.run_until_complete(asyncio.sleep(0))
        other_loop.close()


async def test_a_failed_run_raises_to_every_waiter() -> None:
    async def work() -> str:
        raise ConnectionError("down")

    with pytest.raises(ConnectionError, match="down"):
        await coalesce_request("fails", work)
