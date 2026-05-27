"""Fire-and-forget glue: project the USER's own todos to /workspace/todos/.

User todos are everything in the ``todos`` collection that is NOT a
gaia-task (i.e. does NOT carry the ``gaia-tracked`` label). They are
the items the user sees in the UI todo list.

Active window is 7 days (vs 30 for gaia-tasks): user todos are
high-churn, completed items are less likely to be re-read by the agent.

Soft-fails on missing JuiceFS mount so the caller (tools, bootstrap,
service write paths) never has to know whether the dev environment has
a FUSE mount.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import USER_TODOS_GUIDE_MD
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.mongodb.collections import todos_collection
from app.services.storage.juicefs import _is_mounted, user_workspace_path
from app.services.storage.metrics import FsOps, fs_timer
from app.services.storage.user_todos_vfs import (
    UserTodoProjection,
    catalog_signature,
    materialize_user_todos,
    per_doc_signature,
    read_user_todos_marker,
    write_user_todos_marker,
)
from shared.py.wide_events import log

ACTIVE_WINDOW_DAYS = 7

_background_tasks: set[asyncio.Task] = set()


async def sync_user_todos(user_id: str) -> int:
    """Materialize the user's active todos (UI todo list) to JuiceFS.

    Returns the number of todo bodies rewritten (0 means the on-disk
    projection already matched Mongo, or the mount is missing).

    Hash-gated against ``<user_root>/.gaia/user-todos.v`` — steady state
    does no FS work beyond reading that one marker file.
    """
    if not _is_mounted():
        return 0
    async with fs_timer(FsOps.SYNC_USER_TODOS_VFS):
        docs = await _fetch_active_projections(user_id)
        per_doc = {d["id"]: per_doc_signature(d) for d in docs}
        expected = catalog_signature(per_doc)
        u_root = user_workspace_path(user_id)
        if read_user_todos_marker(u_root) == expected:
            return 0
        written = await asyncio.to_thread(materialize_user_todos, u_root, docs, USER_TODOS_GUIDE_MD)
        write_user_todos_marker(u_root, expected)
        log.info(
            "user_todos_vfs.synced",
            user_id=user_id,
            written=written,
            total=len(docs),
        )
        return written


def schedule_user_todos_sync(user_id: str) -> None:
    """Fire-and-forget wrapper. Use from the user-facing todo service
    write paths (create_todo, update_todo, delete_todo, bulk ops).

    The created task is held in a module-level set + removed via
    ``add_done_callback`` so it cannot be garbage-collected mid-flight.
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
            "user_todos_vfs.sync_failed",
            user_id=user_id,
            error=str(e),
            error_type=type(e).__name__,
        )


async def _fetch_active_projections(user_id: str) -> list[UserTodoProjection]:
    """Pull the user's active non-gaia-tracked todos.

    Filter: ``labels`` does NOT contain ``gaia-tracked``, AND
    (``completed`` is false/missing OR ``completed_at`` >= now - 7 days).
    """
    cutoff = datetime.now(UTC) - timedelta(days=ACTIVE_WINDOW_DAYS)
    cursor = todos_collection.find(
        {
            "user_id": user_id,
            "labels": {"$nin": [GAIA_TRACKED_LABEL]},
            "$or": [
                {"completed": {"$ne": True}},
                {"completed_at": {"$gte": cutoff}},
            ],
        }
    )
    out: list[UserTodoProjection] = []
    async for doc in cursor:
        subtasks = [
            {
                "id": s.get("id"),
                "title": s.get("title"),
                "completed": bool(s.get("completed", False)),
            }
            for s in (doc.get("subtasks") or [])
        ]
        out.append(
            {
                "id": str(doc["_id"]),
                "meta": {
                    "title": doc.get("title"),
                    "description": doc.get("description"),
                    "completed": bool(doc.get("completed", False)),
                    "completed_at": doc.get("completed_at"),
                    "priority": doc.get("priority"),
                    "due_date": doc.get("due_date"),
                    "due_date_timezone": doc.get("due_date_timezone"),
                    "labels": doc.get("labels", []),
                    "project_id": doc.get("project_id"),
                    "subtasks": subtasks,
                    "workflow_id": doc.get("workflow_id"),
                    "created_at": doc.get("created_at"),
                    "updated_at": doc.get("updated_at"),
                },
            }
        )
    return out
