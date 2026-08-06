"""Mongo → VFS glue for ``/workspace/todos/`` (the USER's todo list).

The Mongo side: ``todos`` collection, ``assignee != "gaia"``,
7-day completion window.

The VFS side: :mod:`app.services.storage.user_todos_vfs`.

The shared orchestration (mount check, hash gate, fire-and-forget
scheduler, structured logging) lives in
:mod:`app.services._vfs_scheduler`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.workspace.system_docs import USER_TODOS_GUIDE_MD
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
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
    """Pull the user's active non-GAIA todos from Mongo.

    Filter: ``assignee != "gaia"`` AND (open OR completed within the last
    7 days).
    """
    cutoff = datetime.now(UTC) - timedelta(days=ACTIVE_WINDOW_DAYS)
    docs = await todo_repository.list_active_user_todos_since(user_id, completed_since=cutoff)
    return [_project(doc) for doc in docs]


def _project(doc: TodoDocument) -> UserTodoProjection:
    """Typed document → ``UserTodoProjection`` (no canvas/log here)."""
    subtasks = [
        {
            "id": s.id,
            "title": s.title,
            "completed": s.completed,
        }
        for s in doc.subtasks
    ]
    return {
        "id": doc.id,
        "meta": {
            "title": doc.title,
            "description": doc.description,
            "completed": doc.completed,
            "completed_at": doc.completed_at,
            "priority": doc.priority,
            "due_date": doc.due_date,
            "due_date_timezone": doc.due_date_timezone,
            "labels": doc.labels,
            "project_id": doc.project_id,
            "subtasks": subtasks,
            "workflow_id": doc.workflow_id,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
        },
    }
