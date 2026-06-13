"""Mongo → VFS glue for ``/workspace/gaia-tasks/``.

The Mongo side: ``todos`` collection, ``gaia-tracked`` label, 30-day
completion window.

The VFS side: :mod:`app.services.storage.gaia_tasks_vfs`.

The shared orchestration (mount check, hash gate, fire-and-forget
scheduler, structured logging) lives in
:mod:`app.services._vfs_scheduler`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import GAIA_TASKS_GUIDE_MD
from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.mongodb.collections import todos_collection
from app.services._vfs_scheduler import make_scheduler, run_hashed_sync
from app.services.storage.gaia_tasks_vfs import (
    GaiaTaskProjection,
    gaia_tasks_marker_path,
    materialize_gaia_tasks,
    per_doc_signature,
)
from app.services.storage.metrics import FsOps

ACTIVE_WINDOW_DAYS = 30


async def sync_user_gaia_tasks(user_id: str) -> int:
    """Materialize the user's active gaia-tasks to JuiceFS.

    Returns the number of task bodies rewritten. ``0`` means either the
    mount is missing (native dev) or the on-disk catalog signature
    already matched Mongo — both are no-ops from the caller's POV.
    """
    return await run_hashed_sync(
        user_id,
        fs_op=FsOps.SYNC_GAIA_TASKS_VFS,
        fetch_fn=_fetch_active_projections,
        per_doc_sig_fn=per_doc_signature,
        materialize_fn=materialize_gaia_tasks,
        guide_md=GAIA_TASKS_GUIDE_MD,
        catalog_marker_path_fn=gaia_tasks_marker_path,
        log_name="gaia_tasks_vfs",
    )


# Fire-and-forget wrapper for tracked-todo / canvas / log write paths.
# See the docstring on :func:`make_scheduler` for the contract.
schedule_gaia_tasks_sync = make_scheduler(sync_user_gaia_tasks, log_name="gaia_tasks_vfs")


async def _fetch_active_projections(user_id: str) -> list[GaiaTaskProjection]:
    """Pull the user's active gaia-tasks from Mongo.

    Filter: carries the ``gaia-tracked`` label AND (open OR completed
    within the last 30 days).
    """
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
    return [_project(doc) async for doc in cursor]


def _project(doc: dict) -> GaiaTaskProjection:
    """Mongo doc → ``GaiaTaskProjection`` (preserve every field the agent uses)."""
    return {
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
