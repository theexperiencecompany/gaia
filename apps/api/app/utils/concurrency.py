"""Async concurrency helpers."""

from __future__ import annotations

import asyncio

# key -> (semaphore, the loop it was created under)
_loop_semaphores: dict[str, tuple[asyncio.Semaphore, asyncio.AbstractEventLoop]] = {}


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
