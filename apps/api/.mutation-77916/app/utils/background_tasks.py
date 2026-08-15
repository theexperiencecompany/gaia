"""Fire-and-forget task spawning and guarding with GC-safe lifetime management."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

# ``asyncio.create_task`` holds only a WEAK reference to the task it returns, so
# an otherwise-unreferenced fire-and-forget task can be garbage-collected before
# it finishes. Strong-referencing every task here until it completes is what
# keeps it alive; the done-callback discards it so the set stays bounded.
_background_tasks: set[asyncio.Task[Any]] = set()


def spawn_background_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str | None = None,
    on_done: Callable[[asyncio.Task[Any]], None] | None = None,
) -> asyncio.Task[Any]:
    """Schedule ``coro`` as a fire-and-forget task kept alive until it finishes.

    The single canonical way to run a coroutine detached from its caller. The
    returned task is strong-referenced in a module-level set until it completes,
    then discarded — without that reference the event loop can collect a still-
    running task (see the module docstring). Requires a running event loop;
    raises ``RuntimeError`` otherwise, exactly like ``asyncio.create_task``.

    ``on_done`` runs as an additional done-callback once the task finishes — use
    it to log the task's outcome, which a detached task cannot surface otherwise.
    """
    try:
        task = asyncio.create_task(coro, name=name)
    except RuntimeError:
        # No running loop: create_task never took ownership of ``coro``, so it
        # would leak as an un-awaited coroutine. Close it before re-raising so
        # callers still see the RuntimeError but get no "coroutine was never
        # awaited" warning.
        coro.close()
        raise
    guard_task(task)
    if on_done is not None:
        task.add_done_callback(on_done)
    return task


def guard_task(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    """Strong-reference an already-created ``task`` until it finishes, then release it.

    For a task the caller built and may await, but which must survive if it
    outlives the awaiting scope — the module-level set is the strong reference the
    event loop needs to not collect it mid-flight (see the module docstring), and
    the done-callback discards it so the set stays bounded. Use
    ``spawn_background_task`` instead when you have a coroutine rather than a task.
    """
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
