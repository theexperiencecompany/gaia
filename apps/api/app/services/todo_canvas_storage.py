"""MongoDB-backed facet storage for tracked todos.

A tracked todo's content lives as distinct facets — ``deliverable``, ``notes``,
and ``log`` — each a field on the todo document itself (``deliverable_content``,
``notes_content``, ``log_content``). Reading, writing, and appending are atomic
MongoDB updates — no FUSE mount or JuiceFS required, so tracked todos work in
every dev mode.

The legacy ``vfs_path`` field on the todo doc is retained as a stable display
label (``/users/{user_id}/todos/{todo_id}``) but is no longer a real filesystem
path.
"""

from datetime import UTC, datetime

from bson import ObjectId

from app.constants.todos import FACET_FIELDS, facet_from_doc
from app.db.mongodb.collections import todos_collection
from app.models.todo_models import ExecutionStatus
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from shared.py.wide_events import log

ARTIFACTS_FIELD = "artifacts"


def build_vfs_label(user_id: str, todo_id: str) -> str:
    """Stable label used wherever the old VFS path was surfaced for display."""
    return f"/users/{user_id}/todos/{todo_id}"


def _facet_field(facet: str) -> str:
    """Mongo field name for a facet; raises on an unknown facet (never user input)."""
    try:
        return FACET_FIELDS[facet]
    except KeyError:
        raise ValueError(f"Unknown facet {facet!r}; expected one of {sorted(FACET_FIELDS)}")


async def read_facet(todo_id: str, user_id: str, facet: str) -> str | None:
    """Read a facet's content, applying the migration dual-read fallback.

    Returns ``None`` only when the todo does not exist; a todo with an empty
    facet returns ``""``.
    """
    field = _facet_field(facet)
    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {field: 1, "canvas_content": 1, "execution_status": 1},
    )
    if not doc:
        return None
    allow_canvas_fallback = doc.get("execution_status") == ExecutionStatus.PROPOSED.value
    return facet_from_doc(doc, facet, allow_canvas_fallback=allow_canvas_fallback)


async def write_facet(todo_id: str, user_id: str, facet: str, content: str) -> bool:
    """Overwrite a facet's content. Returns False if the todo was not found."""
    field = _facet_field(facet)
    result = await todos_collection.update_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {"$set": {field: content, "updated_at": datetime.now(UTC)}},
    )
    if result.matched_count > 0:
        schedule_gaia_tasks_sync(user_id)
        return True
    return False


async def append_facet(todo_id: str, user_id: str, facet: str, content: str) -> bool:
    """Append to a facet's content (newline-separated). False if todo not found."""
    current = await read_facet(todo_id, user_id, facet)
    if current is None:
        log.warning("todo_facet.append_missing_todo", todo_id=todo_id, facet=facet)
        return False
    suffix = content if content.startswith("\n") else f"\n{content}"
    return await write_facet(todo_id, user_id, facet, current + suffix)


async def read_artifacts(todo_id: str, user_id: str) -> list[dict] | None:
    """Read the todo's artifacts list. Returns None only when the todo is missing."""
    doc = await todos_collection.find_one(
        {"_id": ObjectId(todo_id), "user_id": user_id},
        {ARTIFACTS_FIELD: 1},
    )
    if not doc:
        return None
    return doc.get(ARTIFACTS_FIELD) or []
