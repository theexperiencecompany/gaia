"""Async concurrency helpers.

loop_bound_semaphore bounds one event loop, by design — it exists to cap a
single process's fan-out, not the fleet's.

run_on_captured_loop is the bridge for the reverse direction: sync code on a
worker thread (a Composio custom tool, an executor-offloaded callable) that must
drive an async client bound to the server's event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")

# key -> (semaphore, the loop it was created under)
_loop_semaphores: dict[str, tuple[asyncio.Semaphore, asyncio.AbstractEventLoop]] = {}

# The process's server loop — the one the Motor/Redis clients are created on.
# Worker threads dispatch coroutines back onto it (see run_on_captured_loop).
_captured_loop: asyncio.AbstractEventLoop | None = None

_ON_SERVER_LOOP_ERROR = (
    "run_on_captured_loop called from the server loop itself; await the "
    "coroutine directly instead of blocking the loop it runs on."
)


def capture_running_loop() -> None:
    """Record the running event loop as the process's server loop.

    Call once at startup, on the loop the async clients are built on. Worker
    threads then reach that loop through run_on_captured_loop instead of
    spinning their own, which would strand a loop-bound client on the wrong loop.
    """
    global _captured_loop
    _captured_loop = asyncio.get_running_loop()


def reset_captured_loop() -> None:
    """Clear the captured server loop. For tests, which own their loop lifecycle."""
    global _captured_loop
    _captured_loop = None


def run_on_captured_loop(coro: Coroutine[Any, Any, _T], *, timeout: float | None = None) -> _T:
    """Run coro to completion from a worker thread that has no running loop.

    Dispatches onto the captured server loop via run_coroutine_threadsafe so a loop-bound client (Motor/Redis) stays on its own loop; without a captured loop (tests, scripts) a fresh loop is used instead, and a genuinely loop-bound client reached with no capture still fails loud rather than passing silently.
    """
    loop = _captured_loop
    if loop is None:
        return asyncio.run(coro)
    try:
        on_server_loop = asyncio.get_running_loop() is loop
    except RuntimeError:
        # No running loop on this thread — so not on the server loop. Only ever
        # read as a bool below, so None/"" would behave identically here.
        on_server_loop = False  # pragma: no mutate
    if on_server_loop:
        coro.close()
        raise RuntimeError(_ON_SERVER_LOOP_ERROR)
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)


def loop_bound_semaphore(key: str, size: int) -> asyncio.Semaphore:
    """Return a process-wide asyncio.Semaphore for key, rebound to the running loop.

    A Semaphore binds to the loop that created its futures and raises if awaited under a different one (a sync caller spinning its own loop, or a fresh test loop); recreating it when the running loop changes keeps it usable everywhere, though production has one long-lived loop so it's created once.
    """
    loop = asyncio.get_running_loop()
    sem, sem_loop = _loop_semaphores.get(key, (None, None))
    if sem is None or sem_loop is not loop:
        sem = asyncio.Semaphore(size)
        _loop_semaphores[key] = (sem, loop)
    return sem
