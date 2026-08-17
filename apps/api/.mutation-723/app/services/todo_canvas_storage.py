"""MongoDB-backed canvas/log storage for tracked todos.

Canvas (`canvas.md`) and log (`log.md`) content live as fields on the
todo document itself: ``canvas_content`` and ``log_content``. Reading,
writing, and appending go through the todos repository — no FUSE mount or
JuiceFS required, so tracked todos work in every dev mode.

The legacy ``vfs_path`` field on the todo doc is retained as a stable
display label (``/users/{user_id}/todos/{todo_id}``) but is no longer a
real filesystem path.
"""

from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoUpdate
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from shared.py.wide_events import log


def build_vfs_label(user_id: str, todo_id: str) -> str:
    """Stable label used wherever the old VFS path was surfaced for display."""
    return f"/users/{user_id}/todos/{todo_id}"


async def read_canvas(todo_id: str, user_id: str) -> str | None:
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return None
    return doc.canvas_content or ""


async def write_canvas(todo_id: str, user_id: str, content: str) -> bool:
    updated = await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate(canvas_content=content)
    )
    if updated is not None:
        schedule_gaia_tasks_sync(user_id)
        return True
    return False


async def append_canvas(todo_id: str, user_id: str, content: str) -> bool:
    current = await read_canvas(todo_id, user_id)
    if current is None:
        log.warning("todo_canvas.append_missing_todo", todo_id=todo_id)
        return False
    suffix = content if content.startswith("\n") else f"\n{content}"
    return await write_canvas(todo_id, user_id, current + suffix)


async def read_log(todo_id: str, user_id: str) -> str | None:
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if not doc:
        return None
    return doc.log_content or ""


async def write_log(todo_id: str, user_id: str, content: str) -> bool:
    updated = await todo_repository.update(
        todo_id, user_id=user_id, update=TodoUpdate(log_content=content)
    )
    if updated is not None:
        schedule_gaia_tasks_sync(user_id)
        return True
    return False


async def append_log(todo_id: str, user_id: str, content: str) -> bool:
    current = await read_log(todo_id, user_id)
    if current is None:
        log.warning("todo_canvas.log_append_missing_todo", todo_id=todo_id)
        return False
    suffix = content if content.startswith("\n") else f"\n{content}"
    return await write_log(todo_id, user_id, current + suffix)
