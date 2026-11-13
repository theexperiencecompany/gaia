"""Shared orchestration for VFS sync glue modules.

The glue modules (gaia_tasks_fs, user_todos_fs, memory_fs) share two patterns:

* Hash-gated sync: bail on missing mount, fetch docs from Mongo, hash them,
  compare to the on-disk marker, materialize in a thread only on mismatch,
  stamp the marker, log the result. See run_hashed_sync.

* Fire-and-forget scheduling: wrap an async sync function as schedule(user_id),
  spawning a background task that holds a reference and never raises into the
  caller. See make_scheduler.

Both are deliberately small so the glue modules read identically; a new VFS
area slots in via the same HashedSyncSpec.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from app.services.storage._vfs_common import (
    catalog_signature,
    read_marker,
    write_marker,
)
from app.services.storage.juicefs import _is_mounted, user_workspace_path
from app.services.storage.metrics import fs_timer
from app.utils.background_tasks import spawn_background_task
from shared.py.wide_events import UserContext, log, wide_task

# Generic over each module's projection TypedDict. Mapping[str, Any] is the
# right bound: TypedDicts structurally satisfy Mapping, so callers pass their
# concrete TypedDict here without a cast, while the helper still gets d["id"].
ProjectionT = TypeVar("ProjectionT", bound=Mapping[str, Any])


@dataclass(frozen=True)
class HashedSyncSpec(Generic[ProjectionT]):
    """The per-area inputs for run_hashed_sync.

    One value groups the fetch/hash/materialize callbacks with the area's
    fs-op, guide doc, marker path, and log name — the pieces every VFS area
    (gaia-tasks, user todos, memory) provides together. Grouping them keeps
    the sync entry point to (user_id, spec) instead of an 8-argument
    call that grows with every new area concern.
    """

    fs_op: str
    fetch_fn: Callable[[str], Awaitable[list[ProjectionT]]]
    per_doc_sig_fn: Callable[[ProjectionT], str]
    materialize_fn: Callable[[Path, list[ProjectionT], str], int]
    guide_md: str
    catalog_marker_path_fn: Callable[[Path], Path]
    log_name: str


async def run_hashed_sync(user_id: str, spec: HashedSyncSpec[ProjectionT]) -> int:
    """Run a hash-gated VFS sync for user_id.

    0 means either the mount was missing or the on-disk signature already
    matched Mongo — both are no-ops from the caller's POV. fs_timer wraps even
    the no-op path so dashboards see the call and can spot a runaway caller.
    """
    if not _is_mounted():
        return 0
    async with fs_timer(spec.fs_op):
        docs = await spec.fetch_fn(user_id)
        per_doc = {d["id"]: spec.per_doc_sig_fn(d) for d in docs}
        expected = catalog_signature(per_doc)
        u_root = user_workspace_path(user_id)
        marker_path = spec.catalog_marker_path_fn(u_root)
        if read_marker(marker_path) == expected:
            return 0
        written = await asyncio.to_thread(spec.materialize_fn, u_root, docs, spec.guide_md)
        write_marker(marker_path, expected)
        log.set(vfs_sync={"name": spec.log_name, "written": written, "total": len(docs)})
        return written


def make_scheduler(
    sync_fn: Callable[[str], Awaitable[int]],
    *,
    log_name: str,
) -> Callable[[str], None]:
    """Build a schedule(user_id) wrapper around sync_fn.

    No-ops when unmounted or with no running loop, and never raises out of the
    background task. Runs at most one sync per user at a time — a schedule()
    landing mid-flight marks the user dirty so the running task re-syncs once more, costing two syncs per write burst instead of one per write.
    """
    in_flight: set[str] = set()
    dirty: set[str] = set()

    async def _safe(user_id: str) -> None:
        # Own wide_task scope: no request middleware runs in this fire-and-forget
        # task, so this is what makes the result and failure emit a queryable
        # wide event. wide_task already records failure, so suppress the re-raise.
        with contextlib.suppress(Exception):
            async with wide_task(log_name, user=UserContext(id=user_id)):
                await sync_fn(user_id)

    async def _drain(user_id: str) -> None:
        try:
            while True:
                dirty.discard(user_id)
                await _safe(user_id)
                # No await between this check and the ``finally``: a schedule()
                # that arrives after the loop exits sees the user idle and spawns.
                if user_id not in dirty:
                    return
        finally:
            in_flight.discard(user_id)

    def schedule(user_id: str) -> None:
        if not _is_mounted():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        if user_id in in_flight:
            dirty.add(user_id)
            return
        in_flight.add(user_id)
        spawn_background_task(_drain(user_id))

    return schedule
