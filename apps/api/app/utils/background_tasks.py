"""Fire-and-forget task spawning and guarding with GC-safe lifetime management."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

# asyncio.create_task holds only a weak reference, so an unreferenced
# fire-and-forget task can be GC'd before it finishes; this set strong-refs
# each task until its done-callback discards it.
_background_tasks: set[asyncio.Task[Any]] = set()


def spawn_background_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    on_done: Callable[[asyncio.Task[Any]], None] | None = None,
) -> asyncio.Task[Any]:
    """Schedule coro as a fire-and-forget task kept alive until it finishes; the single canonical way to run a detached coroutine.

    Requires a running event loop (raises RuntimeError otherwise, like asyncio.create_task). on_done runs as an additional done-callback, e.g. to log the task's outcome since a detached task can't surface it otherwise.
    """
    try:
        task = asyncio.create_task(coro, name=name)
    except RuntimeError:
        # create_task never took ownership without a loop, so coro would leak as
        # un-awaited; close it before re-raising to avoid that warning.
        coro.close()
        raise
    guard_task(task)
    if on_done is not None:
        task.add_done_callback(on_done)
    return task


def guard_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """Strong-reference an already-created task until it finishes, then release it.

    For a task the caller built and may await but which must survive beyond the awaiting scope; use spawn_background_task instead when starting from a coroutine.
    """
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
