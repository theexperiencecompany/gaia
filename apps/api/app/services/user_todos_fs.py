"""Mongo → VFS glue for ``/workspace/todos/`` (the USER's todo list).

The Mongo side: ``todos`` collection, NOT carrying ``gaia-tracked``,
7-day completion window.

The VFS side: :mod:`app.services.storage.user_todos_vfs`.

The shared orchestration (mount check, hash gate, fire-and-forget
scheduler, structured logging) lives in
:mod:`app.services._vfs_scheduler`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import USER_TODOS_GUIDE_MD
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.mongodb.collections import todos_collection
from app.services._vfs_scheduler import make_scheduler, run_hashed_sync
from app.services.storage.metrics import FsOps
from app.services.storage.user_todos_vfs import (
    UserTodoProjection,
    materialize_user_todos,
    per_doc_signature,
    user_todos_marker_path,
)

ACTIVE_WINDOW_DAYS = 7


async def sync_user_todos(user_id: str) -> int:
    """Materialize the user's active todos (UI todo list) to JuiceFS.

    Returns the number of meta bodies rewritten. ``0`` means either the
    mount is missing or the on-disk catalog signature already matched.
    """
    return await run_hashed_sync(
        user_id,
        fs_op=FsOps.SYNC_USER_TODOS_VFS,
        fetch_fn=_fetch_active_projections,
        per_doc_sig_fn=per_doc_signature,
        materialize_fn=materialize_user_todos,
        guide_md=USER_TODOS_GUIDE_MD,
        catalog_marker_path_fn=user_todos_marker_path,
        log_name="user_todos_vfs",
    )


# Fire-and-forget wrapper for the TodoService write paths.
# See the docstring on :func:`make_scheduler` for the contract.
schedule_user_todos_sync = make_scheduler(sync_user_todos, log_name="user_todos_vfs")


async def _fetch_active_projections(user_id: str) -> list[UserTodoProjection]:
    """Pull the user's active non-gaia-tracked todos from Mongo.

    Filter: ``labels`` does NOT contain ``gaia-tracked`` AND (open OR
    completed within the last 7 days).
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
    return [_project(doc) async for doc in cursor]


def _project(doc: dict) -> UserTodoProjection:
    """Mongo doc → ``UserTodoProjection`` (no canvas/log here)."""
    subtasks = [
        {
            "id": s.get("id"),
            "title": s.get("title"),
            "completed": bool(s.get("completed", False)),
        }
        for s in (doc.get("subtasks") or [])
    ]
    return {
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
