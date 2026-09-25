"""Give each browser run its own bubus event lock instead of one for the whole process.

bubus runs every EventBus's handlers under one process-wide re-entrant lock
(bubus/service.py:951), so every Browser-Use session in a worker queued behind
every other's: four runs in one process took 22.9-34.5 s each, 12.6-23.4 s with a
lock per run, 6-11 s alone (2026-09-25). Upstream keeps the lock (bubus#21).
A lock per run is safe: each run builds its own Agent, BrowserSession and
EventBuses, Browser-Use never forwards events between buses, and bubus's
process-global state is only read or copied without an await between. A bus's
run-loop task starts inside the run, so it inherits the run's lock; outside a
run the process-wide lock is used. Pinned to bubus==1.5.6.
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
