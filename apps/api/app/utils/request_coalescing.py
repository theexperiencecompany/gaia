"""
Request coalescing: concurrent callers for one key share a single run of the work.

Each waiter awaits the run shielded, so a waiter that is cancelled or out of
its own budget leaves the run going for the others. The registry holds the task
until it finishes, so it cannot be collected mid-flight.

Coalescing is per process and per event loop; the factories are idempotent with
last-write-wins cache writes, so N replicas cost duplicate calls, not wrong results.
"""

import asyncio
from collections.abc import Callable, Coroutine
import functools
from typing import TypeVar, cast

T = TypeVar("T")

_Slot = tuple[asyncio.AbstractEventLoop, str]

#: In-flight runs. Keyed by loop as well, so a task bound to a closed loop (tests,
#: reloads) is never awaited from another.
_pending_requests: dict[_Slot, asyncio.Task[object]] = {}


def _forget(slot: _Slot, task: asyncio.Task[object]) -> None:
    if _pending_requests.get(slot) is task:
        del _pending_requests[slot]


async def coalesce_request(key: str, factory: Callable[[], Coroutine[object, None, T]]) -> T:
    """Join key's in-flight run, or start factory as it; return its result or raise its error."""
    slot = (asyncio.get_running_loop(), key)
    pending = _pending_requests.get(slot)
    if pending is not None:
        # One key always names one piece of work, so its task returns that work's type.
        return await asyncio.shield(cast("asyncio.Task[T]", pending))
    task = asyncio.ensure_future(factory())
    _pending_requests[slot] = task
    task.add_done_callback(functools.partial(_forget, slot))
    return await asyncio.shield(task)
