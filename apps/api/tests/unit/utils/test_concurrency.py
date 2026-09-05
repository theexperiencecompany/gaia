"""Unit tests for app.utils.concurrency.

``run_on_captured_loop`` is the sync->async bridge the calendar Composio tools
use. The bug it fixes: the old bridge ran coroutines on a fresh ``asyncio.run``
loop, so a coroutine that awaited a loop-bound client (Motor) raised
``RuntimeError: ... attached to a different loop``. The regression is pinned with
a loop-bound ``asyncio.Future`` standing in for that client — a fresh loop cannot
await it, the captured loop can.
"""

import asyncio

import pytest

from app.utils.concurrency import (
    capture_running_loop,
    reset_captured_loop,
    run_on_captured_loop,
)


@pytest.fixture(autouse=True)
def _isolate_captured_loop():
    """Capture is process-global; clear it around every test so none leaks."""
    reset_captured_loop()
    yield
    reset_captured_loop()


async def _echo(value: str) -> str:
    await asyncio.sleep(0)
    return value


async def _boom() -> None:
    raise KeyError("kaboom")


@pytest.mark.unit
class TestRunOnCapturedLoop:
    async def test_without_capture_runs_on_a_fresh_loop(self) -> None:
        # No server loop captured (a loop-less script or sync-graph test context):
        # the coroutine runs on a fresh loop rather than failing. The autouse
        # fixture already cleared any captured loop.
        result = await asyncio.to_thread(lambda: run_on_captured_loop(_echo("x")))
        assert result == "x"

    async def test_dispatches_onto_the_captured_loop_from_a_worker_thread(self) -> None:
        capture_running_loop()
        result = await asyncio.to_thread(lambda: run_on_captured_loop(_echo("ok")))
        assert result == "ok"

    async def test_awaits_a_loop_bound_future_without_cross_loop_error(self) -> None:
        # A Future bound to THIS loop. The old bridge (asyncio.run in a worker
        # thread) drives a fresh loop and raises "attached to a different loop"
        # here — the exact calendar failure. Dispatching onto the captured loop
        # resolves the future on the loop that owns it.
        capture_running_loop()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        loop.call_soon(fut.set_result, "resolved")

        async def waits_on_loop_bound_future() -> str:
            return await fut

        result = await asyncio.to_thread(lambda: run_on_captured_loop(waits_on_loop_bound_future()))
        assert result == "resolved"

    async def test_propagates_exceptions(self) -> None:
        capture_running_loop()
        with pytest.raises(KeyError):
            await asyncio.to_thread(lambda: run_on_captured_loop(_boom()))

    async def test_timeout_bounds_the_wait(self) -> None:
        capture_running_loop()

        async def slow() -> str:
            await asyncio.sleep(1.0)
            return "late"

        with pytest.raises(TimeoutError):
            await asyncio.to_thread(lambda: run_on_captured_loop(slow(), timeout=0.1))

    async def test_refuses_to_block_the_captured_loop_itself(self) -> None:
        # Called ON the captured loop's own thread: run_coroutine_threadsafe would
        # deadlock, so it must refuse rather than hang.
        capture_running_loop()
        with pytest.raises(RuntimeError, match="from the server loop itself"):
            run_on_captured_loop(_echo("x"))
