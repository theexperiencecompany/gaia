"""Give each browser run its own bubus event lock instead of one for the whole process.

bubus runs every EventBus's handlers under one process-wide re-entrant lock
(bubus/service.py:951, _get_global_lock at :204), so every Browser-Use session
in a worker process queues its state reads, navigations and screenshots behind
every other session's. Measured 2026-09-25, four runs in one process: 22.9 to
34.5 s each, against 12.6 to 23.4 s with a lock per run and 6 to 11 s alone.
Upstream keeps the lock by design (browser-use/bubus#21): it serialises
handlers that touch shared browser state, and bubus 1.5.6 is still what
browser-use 0.13.10 pins.

A lock per run keeps that guarantee, because nothing a run's handlers share is
shared with another run:
- Each run builds its own Agent and BrowserSession, and each creates its own
  EventBus (browser_use/agent/service.py:582, browser/session.py:695 and :720):
  its own CDP connection, watchdogs, agent state and file system.
- Browser-Use never forwards events between buses (the one `.on('*', ...)` is
  the CLI's logger, browser_use/cli.py:936), so no event crosses runs.
- bubus's process-global state is the EventBus.all_instances WeakSet and the
  cross-bus parent lookups in event_history (bubus/service.py:261, :297, :995,
  :1307). Every access copies or tests without an await in between, so on one
  event loop it cannot interleave with another run, lock or no lock.
- A bus's run loop task starts inside the run (on its first dispatch), so it
  inherits the run's context and reads the run's lock; re-entrancy is tracked
  per context by bubus's own holds_global_lock ContextVar, unchanged.
Code outside a run keeps the process-wide lock.

Pinned to bubus==1.5.6; the import fails loudly if _get_global_lock moves.
"""

from contextvars import ContextVar

import bubus.service as bubus_service
from bubus.service import ReentrantLock

_original_get_global_lock = bubus_service._get_global_lock

#: The lock every EventBus created and run inside the current browser run takes.
_run_lock: ContextVar[ReentrantLock | None] = ContextVar("browser_run_event_lock", default=None)


def _get_run_lock() -> ReentrantLock:
    """Return the current run's lock, or the process-wide one outside a run."""
    lock = _run_lock.get()
    return lock if lock is not None else _original_get_global_lock()


def isolate_run_events() -> None:
    """Give the calling run, and every task it starts from here on, its own event lock."""
    _run_lock.set(ReentrantLock())


def apply() -> None:
    """Route bubus's lock lookup through the run's context."""
    bubus_service._get_global_lock = _get_run_lock


apply()
