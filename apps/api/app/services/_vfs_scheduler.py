"""Shared orchestration for VFS sync glue modules.

The two glue modules (``gaia_tasks_fs``, ``user_todos_fs``) share two
distinct patterns:

* **Hash-gated sync**: bail on missing mount, fetch active docs from
  Mongo, hash them, compare against the on-disk catalog marker, run
  the materializer in a thread only on mismatch, stamp the new marker,
  log the result. Implemented by :func:`run_hashed_sync`.

* **Fire-and-forget scheduling**: turn an async sync function into a
  ``schedule(user_id)`` callable that creates a background task, holds
  a reference so the task isn't garbage-collected, and never raises
  into the caller. Implemented by :func:`make_scheduler`.

Both helpers are deliberately small. They exist to make the two glue
modules read top-down and identical in shape — if a third VFS area
(``/workspace/memory/`` for semantic memory, say) gets added later it
slots in by providing the same five callbacks.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, TypeVar

from app.services.storage._vfs_common import (
    catalog_signature,
    read_marker,
    write_marker,
)
from app.services.storage.juicefs import _is_mounted, user_workspace_path
from app.services.storage.metrics import fs_timer
from shared.py.wide_events import log

# Generic over each module's projection TypedDict (``GaiaTaskProjection``,
# ``UserTodoProjection``, …). ``Mapping[str, Any]`` is the right bound:
# TypedDicts structurally satisfy ``Mapping`` (covariant in the value
# type), so callers can pass their concrete TypedDict here without any
# cast, while the helper still gets ``d["id"]`` access.
ProjectionT = TypeVar("ProjectionT", bound=Mapping[str, Any])


async def run_hashed_sync(
    user_id: str,
    *,
    fs_op: str,
    fetch_fn: Callable[[str], Awaitable[list[ProjectionT]]],
    per_doc_sig_fn: Callable[[ProjectionT], str],
    materialize_fn: Callable[[Path, list[ProjectionT], str], int],
    guide_md: str,
    catalog_marker_path_fn: Callable[[Path], Path],
    log_name: str,
) -> int:
    """Run a hash-gated VFS sync for ``user_id``.

    Returns the number of doc bodies rewritten. ``0`` means either the
    mount was missing (native dev) or the on-disk catalog signature
    already matched Mongo — both are no-ops from the caller's POV.

    Steps (do not reorder):

    1. Short-circuit on missing mount.
    2. Open the ``fs_timer`` so dashboards see the call even when it's
       a no-op due to the marker match (helps spot a runaway caller).
    3. Fetch + hash + compare against the catalog marker.
    4. If mismatch, materialize off the event loop and stamp the new
       marker.
    5. Emit a single structured log line.
    """
    if not _is_mounted():
        return 0
    async with fs_timer(fs_op):
        docs = await fetch_fn(user_id)
        per_doc = {d["id"]: per_doc_sig_fn(d) for d in docs}
        expected = catalog_signature(per_doc)
        u_root = user_workspace_path(user_id)
        marker_path = catalog_marker_path_fn(u_root)
        if read_marker(marker_path) == expected:
            return 0
        written = await asyncio.to_thread(materialize_fn, u_root, docs, guide_md)
        write_marker(marker_path, expected)
        log.info(
            f"{log_name}.synced",
            user_id=user_id,
            written=written,
            total=len(docs),
        )
        return written


def make_scheduler(
    sync_fn: Callable[[str], Awaitable[int]],
    *,
    log_name: str,
) -> Callable[[str], None]:
    """Build a ``schedule(user_id)`` wrapper around ``sync_fn``.

    The returned closure:

    * No-ops when JuiceFS isn't mounted (native dev mode) so callers
      don't need to know which dev mode they're in.
    * Returns silently if no asyncio loop is running (e.g. workers
      calling tools synchronously during startup).
    * Wraps every task body in a try/except that logs but never raises
      — fire-and-forget MUST NOT crash the host coroutine.
    * Holds task refs in a closure-local set + ``add_done_callback`` so
      tasks aren't garbage-collected mid-flight.
    """
    tasks: set[asyncio.Task] = set()

    async def _safe(user_id: str) -> None:
        try:
            await sync_fn(user_id)
        except Exception as e:  # noqa: BLE001 — fire-and-forget body must not crash
            log.warning(
                f"{log_name}.sync_failed",
                user_id=user_id,
                error=str(e),
                error_type=type(e).__name__,
            )

    def schedule(user_id: str) -> None:
        if not _is_mounted():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(_safe(user_id))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    return schedule
