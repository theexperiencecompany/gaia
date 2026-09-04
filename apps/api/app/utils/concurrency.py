"""Async concurrency helpers.

``loop_bound_semaphore`` bounds one event loop, by design — it exists to cap a
single process's fan-out, not the fleet's.
"""

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


#: The loop this process runs on, recorded at startup. A sync callable running
#: on a worker thread cannot discover it — ``get_running_loop`` succeeds only ON
#: the loop thread — so startup is the one place that can hand it over.
_server_loop: asyncio.AbstractEventLoop | None = None


def remember_server_loop() -> None:
    """Record the running loop as this process's server loop.

    Sync bodies called from async code (Composio custom tools, invoked through
    ``asyncio.to_thread``) need to run their coroutines on the loop the app's
    singletons are bound to — Motor clients, lazy-provider locks and
    ``loop_bound_semaphore`` all raise "attached to a different event loop"
    otherwise. Called once per process from ``unified_startup``.
    """
    global _server_loop
    _server_loop = asyncio.get_running_loop()


def server_loop() -> asyncio.AbstractEventLoop | None:
    """The recorded server loop, or ``None`` outside a running app.

    ``None`` in scripts and tests, which have no shared singletons to respect,
    so a caller is free to run the coroutine on a loop of its own there.
    """
    loop = _server_loop
    return loop if loop is not None and loop.is_running() else None
