"""MongoDB-backed canvas/log storage for tracked todos.

Canvas (`canvas.md`) and log (`log.md`) content live as fields on the
todo document itself: ``canvas_content`` and ``log_content``. Reading,
writing, and appending are atomic MongoDB updates — no FUSE mount or
JuiceFS required, so tracked todos work in every dev mode.

The legacy ``vfs_path`` field on the todo doc is retained as a stable
display label (``/users/{user_id}/todos/{todo_id}``) but is no longer a
real filesystem path.
"""

from datetime import UTC, datetime

from bson import ObjectId

from app.db.mongodb.collections import todos_collection
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from shared.py.wide_events import log


def build_vfs_label(user_id: str, todo_id: str) -> str:
    """Stable label used wherever the old VFS path was surfaced for display."""
    return f"/users/{user_id}/todos/{todo_id}"


async def read_canvas(todo_id: str, user_id: str) -> str | None:
    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"canvas_content": 1},
    )
    if not doc:
        return None
    return doc.get("canvas_content") or ""


async def write_canvas(todo_id: str, user_id: str, content: str) -> bool:
    result = await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": {"canvas_content": content, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count > 0:
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
    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"log_content": 1},
    )
    if not doc:
        return None
    return doc.get("log_content") or ""


async def write_log(todo_id: str, user_id: str, content: str) -> bool:
    result = await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": {"log_content": content, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count > 0:
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
