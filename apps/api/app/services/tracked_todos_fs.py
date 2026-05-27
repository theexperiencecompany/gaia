"""Fire-and-forget glue: pull tracked todos from Mongo, materialize VFS.

Active set definition matches the existing tracked-todo surface in
``app/services/tracked_todo_service.py``:

* The todo carries the ``gaia-tracked`` label
  (``GAIA_TRACKED_LABEL`` — there is no ``is_tracked`` field).
* AND the todo is either still open (``completed`` is false / missing)
  OR was completed within the last 30 days.

Soft-fails on missing JuiceFS mount so the caller (tools, bootstrap)
never has to know whether the dev environment has a FUSE mount.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import TODOS_GUIDE_MD
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.mongodb.collections import todos_collection
from app.services.storage.juicefs import _is_mounted, user_workspace_path
from app.services.storage.metrics import FsOps, fs_timer
from app.services.storage.todos_vfs import (
    TodoProjection,
    catalog_signature,
    materialize_todos,
    per_doc_signature,
    read_todos_marker,
    write_todos_marker,
)
from shared.py.wide_events import log

ACTIVE_WINDOW_DAYS = 30

_background_tasks: set[asyncio.Task] = set()


async def sync_user_todos(user_id: str) -> int:
    """Materialize the user's active tracked todos to JuiceFS.

    Returns the number of todo bodies rewritten on disk (0 means the
    on-disk projection already matched Mongo, or the mount is missing).

    Hash-gated against ``<user_root>/.gaia/todos.v`` — steady state does
    no FS work beyond reading that one marker file.
    """
    if not _is_mounted():
        return 0
    async with fs_timer(FsOps.SYNC_TODOS_VFS):
        docs = await _fetch_active_projections(user_id)
        per_doc = {d["id"]: per_doc_signature(d) for d in docs}
        expected = catalog_signature(per_doc)
        u_root = user_workspace_path(user_id)
        if read_todos_marker(u_root) == expected:
            return 0
        written = await asyncio.to_thread(materialize_todos, u_root, docs, TODOS_GUIDE_MD)
        write_todos_marker(u_root, expected)
        log.info(
            "todos_vfs.synced",
            user_id=user_id,
            written=written,
            total=len(docs),
        )
        return written


def schedule_sync(user_id: str) -> None:
    """Fire-and-forget wrapper. Use from tool/service write-paths.

    The created task is held in a module-level set + removed via
    ``add_done_callback`` so it cannot be garbage-collected mid-flight
    (same pattern as ``tracked_todo_tools._background_tasks``).
    """
    if not _is_mounted():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_safe_sync(user_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _safe_sync(user_id: str) -> None:
    """Background-task body: never raises, always logs failures."""
    try:
        await sync_user_todos(user_id)
    except Exception as e:  # noqa: BLE001 — fire-and-forget body must not crash the loop
        log.warning(
            "todos_vfs.sync_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def _fetch_active_projections(user_id: str) -> list[TodoProjection]:
    """Pull the user's active tracked todos and project to ``TodoProjection``."""
    cutoff = datetime.now(UTC) - timedelta(days=ACTIVE_WINDOW_DAYS)
    cursor = todos_collection.find(
        {
            "user_id": user_id,
            "labels": GAIA_TRACKED_LABEL,
            "$or": [
                {"completed": {"$ne": True}},
                {"completed_at": {"$gte": cutoff}},
            ],
        }
    )
    out: list[TodoProjection] = []
    async for doc in cursor:
        out.append(
            {
                "id": str(doc["_id"]),
                "canvas": doc.get("canvas_content") or "",
                "log": doc.get("log_content") or "",
                "meta": {
                    "title": doc.get("title"),
                    "completed": bool(doc.get("completed", False)),
                    "completed_at": doc.get("completed_at"),
                    "priority": doc.get("priority"),
                    "due_date": doc.get("due_date"),
                    "due_date_timezone": doc.get("due_date_timezone"),
                    "labels": doc.get("labels", []),
                    "references": doc.get("references", []),
                    "scheduled_at": doc.get("scheduled_at"),
                    "recurrence": doc.get("recurrence"),
                    "expires_at": doc.get("expires_at"),
                    "project_id": doc.get("project_id"),
                    "created_at": doc.get("created_at"),
                    "updated_at": doc.get("updated_at"),
                    "vfs_path": doc.get("vfs_path"),
                },
            }
        )
    return out
