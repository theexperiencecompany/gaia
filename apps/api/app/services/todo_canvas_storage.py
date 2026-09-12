"""MongoDB-backed canvas/activity/log storage for tracked todos.

Canvas (`canvas.md`), activity (`activity.md`) and log (`log.md`) content live
as fields on the todo document itself: ``canvas_content``, ``activity_content``
and ``log_content``. Reading, writing, and appending go through the todos
repository — no FUSE mount or JuiceFS required, so tracked todos work in every
dev mode.

Every successful canvas/activity write re-embeds the todo in ChromaDB here, so
all writers (agent file tools, code-written run markers) keep search fresh.

The legacy ``vfs_path`` field on the todo doc is retained as a stable
display label (``/workspace/gaia-tasks/{todo_id}``) but is no longer a
real filesystem path. It never carries the host-side ``/users/<uid>``
prefix — the LLM only ever sees the sandbox-visible workspace path.
"""

from datetime import datetime

from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from app.utils.canvas_vector_utils import delete_canvas_embedding, update_canvas_embedding
from shared.py.wide_events import log, spawn_logged_task


def build_vfs_label(todo_id: str, *, archived: bool = False) -> str:
    """Stable label used wherever the old VFS path was surfaced for display."""
    if archived:
        return f"/workspace/gaia-tasks/archive/{todo_id}"
    return f"/workspace/gaia-tasks/{todo_id}"


def embedding_text(doc: TodoDocument) -> str:
    """The text embedded for canvas search: canvas + activity, skipping empties."""
    parts = [p for p in (doc.canvas_content, doc.activity_content) if p]
    return "\n\n".join(parts)


def _schedule_reindex(doc: TodoDocument) -> None:
    text = embedding_text(doc)
    if not text:
        spawn_logged_task("canvas_reindex_delete", delete_canvas_embedding(doc.id))
        return
    spawn_logged_task(
        "canvas_reindex",
        update_canvas_embedding(
            todo_id=doc.id,
            canvas_content=text,
            user_id=doc.user_id,
            title=doc.title,
            labels=doc.labels,
            revision=doc.updated_at.isoformat() if doc.updated_at is not None else None,
        ),
    )


async def read_canvas(todo_id: str, user_id: str) -> str | None:
    """Return the todo's canvas body, or None when the todo does not exist."""
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return None
    return doc.canvas_content or ""


async def write_canvas(
    todo_id: str, user_id: str, content: str, *, expected_updated_at: datetime | None = None
) -> bool:
    """Replace the canvas body; schedules VFS sync + Chroma reindex on success."""
    updated = await todo_repository.replace_note_fields(
        todo_id,
        user_id,
        update=TodoUpdate(canvas_content=content),
        expected_updated_at=expected_updated_at,
    )
    if updated is not None:
        schedule_gaia_tasks_sync(user_id)
        _schedule_reindex(updated)
        return True
    return False


async def write_canvas_and_activity(
    todo_id: str,
    user_id: str,
    *,
    canvas: str,
    activity: str,
    expected_updated_at: datetime | None = None,
) -> bool:
    """Replace both bodies in one update (the legacy-canvas migration path)."""
    updated = await todo_repository.replace_note_fields(
        todo_id,
        user_id,
        update=TodoUpdate(canvas_content=canvas, activity_content=activity),
        expected_updated_at=expected_updated_at,
    )
    if updated is not None:
        schedule_gaia_tasks_sync(user_id)
        _schedule_reindex(updated)
        return True
    return False


async def read_activity(todo_id: str, user_id: str) -> str | None:
    """Return the todo's activity body, or None when the todo does not exist."""
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return None
    return doc.activity_content or ""


async def write_activity(
    todo_id: str, user_id: str, content: str, *, expected_updated_at: datetime | None = None
) -> bool:
    """Replace the activity body; schedules VFS sync + Chroma reindex on success."""
    updated = await todo_repository.replace_note_fields(
        todo_id,
        user_id,
        update=TodoUpdate(activity_content=content),
        expected_updated_at=expected_updated_at,
    )
    if updated is not None:
        schedule_gaia_tasks_sync(user_id)
        _schedule_reindex(updated)
        return True
    return False


async def append_activity(todo_id: str, user_id: str, entry: str) -> bool:
    """Append an entry at the end of the activity log (chronological order)."""
    suffix = entry if entry.startswith("\n") else f"\n{entry}"
    updated = await todo_repository.append_text_field(
        todo_id, user_id, field="activity_content", suffix=suffix
    )
    if updated is None:
        log.warning("todo_canvas.activity_append_missing_todo", todo_id=todo_id)
        return False
    schedule_gaia_tasks_sync(user_id)
    _schedule_reindex(updated)
    return True


async def append_log(todo_id: str, user_id: str, content: str) -> bool:
    """Append to the system-log body, ensuring a leading newline separator."""
    suffix = content if content.startswith("\n") else f"\n{content}"
    updated = await todo_repository.append_text_field(
        todo_id, user_id, field="log_content", suffix=suffix
    )
    if updated is None:
        log.warning("todo_canvas.log_append_missing_todo", todo_id=todo_id)
        return False
    schedule_gaia_tasks_sync(user_id)
    return True
