"""Async concurrency helpers.

``loop_bound_semaphore`` bounds one event loop, by design — it exists to cap a
single process's fan-out, not the fleet's.

``run_on_captured_loop`` is the bridge for the reverse direction: sync code on a
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


def capture_running_loop() -> None:
    """Record the running event loop as the process's server loop.

    Call once at startup, on the loop the async clients are built on. Worker
    threads then reach that loop through ``run_on_captured_loop`` instead of
    spinning their own, which would strand a loop-bound client on the wrong loop.
    """
    global _captured_loop
    _captured_loop = asyncio.get_running_loop()


def reset_captured_loop() -> None:
    """Clear the captured server loop. For tests, which own their loop lifecycle."""
    global _captured_loop
    _captured_loop = None


def run_on_captured_loop(coro: Coroutine[Any, Any, _T], *, timeout: float | None = None) -> _T:
    """Run ``coro`` to completion from a worker thread that has no running loop.

    When a server loop was captured (production: the loop the Motor/Redis clients
    are bound to), dispatch onto it via ``run_coroutine_threadsafe`` so a
    loop-bound client stays on its own loop — ``asyncio.run`` here would spin a
    fresh loop and make Motor raise "attached to a different loop".

    Without a captured loop — a loop-less context such as a synchronous
    ``graph.stream`` in tests or a standalone script, where the services are
    loop-agnostic — a fresh loop is the right thing. This is not a bug-hiding
    fallback: a genuinely loop-bound client reached with no capture still fails
    loud with the same cross-loop error, so the case this exists to prevent can
    never pass silently.
    """
    loop = _captured_loop
    if loop is None:
        return asyncio.run(coro)
    try:
        current: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        current = None
    if current is loop:
        coro.close()
        raise RuntimeError(
            "run_on_captured_loop called from the server loop itself; await the "
            "coroutine directly instead of blocking the loop it runs on."
        )
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)


def loop_bound_semaphore(key: str, size: int) -> asyncio.Semaphore:
    """A process-wide ``asyncio.Semaphore`` for ``key``, rebound to the running loop.

    ``asyncio.Semaphore`` binds to the loop that created its internal futures, so
    one built under a different loop raises "bound to a different event loop" when
    awaited (a sync caller that spins its own loop, or a fresh test loop).
    Recreating it whenever the running loop changes keeps it usable everywhere;
    in production there is a single long-lived loop so it is created once.
    """
    loop = asyncio.get_running_loop()
    sem, sem_loop = _loop_semaphores.get(key, (None, None))
    if sem is None or sem_loop is not loop:
        sem = asyncio.Semaphore(size)
        _loop_semaphores[key] = (sem, loop)
    return sem
