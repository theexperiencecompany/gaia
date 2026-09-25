"""Fire-and-forget task spawning and guarding with GC-safe lifetime management."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import TypeVar

from shared.py.wide_events import emit_unobserved_task_failure, get_trace_id

T = TypeVar("T")

# asyncio.create_task holds only a weak reference, so an unreferenced
# fire-and-forget task can be GC'd before it finishes; this set strong-refs
# each task until its done-callback discards it.
_background_tasks: set[asyncio.Task[object]] = set()


def spawn_background_task(
    coro: Coroutine[object, object, T],
    *,
    name: str | None = None,
    on_done: Callable[[asyncio.Task[T]], None] | None = None,
) -> asyncio.Task[T]:
    """Schedule coro as a fire-and-forget task kept alive until it finishes; the single canonical way to run a detached coroutine.

    Requires a running event loop (raises RuntimeError otherwise, like asyncio.create_task). An exception the task raises emits a failed background_task event named name (the coroutine's name when unset) under the spawner's trace id; on_done runs as an additional done-callback for whatever else the caller needs from the outcome.
    """
    task_name = name or coro.__qualname__
    try:
        task = asyncio.create_task(coro, name=task_name)
    except RuntimeError:
        # create_task never took ownership without a loop, so coro would leak as
        # un-awaited; close it before re-raising to avoid that warning.
        coro.close()
        raise
    guard_task(task)
    task.add_done_callback(_failure_reporter(task_name, get_trace_id()))
    if on_done is not None:
        task.add_done_callback(on_done)
    return task


def guard_task(task: asyncio.Task[T]) -> asyncio.Task[T]:
    """Strong-reference an already-created task until it finishes, then release it.

    For a task the caller built and may await but which must survive beyond the awaiting scope; use spawn_background_task instead when starting from a coroutine.
    """
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _failure_reporter(task_name: str, trace_id: str) -> Callable[[asyncio.Task[T]], None]:
    """Build the done-callback that emits a failed event when the task raised.

    A cancelled task is a clean exit, not a failure: it is checked first because
    Task.exception() on a cancelled task raises CancelledError into the loop.
    """

    def _report(task: asyncio.Task[T]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            emit_unobserved_task_failure(task_name, exc, trace_id=trace_id)

    return _report
