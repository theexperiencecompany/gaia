"""MongoDB-backed facet storage for tracked todos.

A tracked todo's content lives as distinct facets — ``deliverable``, ``notes``,
and ``log`` — each a field on the todo document itself (``deliverable_content``,
``notes_content``, ``log_content``). Reading, writing, and appending go through
the todos repository — no FUSE mount or JuiceFS required, so tracked todos work
in every dev mode.

The legacy ``vfs_path`` field on the todo doc is retained as a stable
display label (``/workspace/gaia-tasks/{todo_id}``) but is no longer a
real filesystem path. It never carries the host-side ``/users/<uid>``
prefix — the LLM only ever sees the sandbox-visible workspace path.
"""

from typing import Any

from app.constants.todos import FACET_FIELDS, facet_from_doc
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExecutionStatus, TodoUpdate
from app.services.gaia_tasks_fs import schedule_gaia_tasks_sync
from shared.py.wide_events import log


def build_vfs_label(todo_id: str, *, archived: bool = False) -> str:
    """Stable label used wherever the old VFS path was surfaced for display."""
    if archived:
        return f"/workspace/gaia-tasks/archive/{todo_id}"
    return f"/workspace/gaia-tasks/{todo_id}"


def _facet_field(facet: str) -> str:
    """Mongo field name for a facet; raises on an unknown facet (never user input)."""
    try:
        return FACET_FIELDS[facet]
    except KeyError:
        raise ValueError(
            f"Unknown facet {facet!r}; expected one of {sorted(FACET_FIELDS)}"
        ) from None


async def read_facet(todo_id: str, user_id: str, facet: str) -> str | None:
    """Read a facet's content, applying the migration dual-read fallback.

    Returns ``None`` only when the todo does not exist; a todo with an empty
    facet returns ``""``.
    """
    _facet_field(facet)  # validates the facet name
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if doc is None:
        return None
    allow_canvas_fallback = doc.execution_status == ExecutionStatus.PROPOSED
    return facet_from_doc(doc.model_dump(), facet, allow_canvas_fallback=allow_canvas_fallback)


async def write_facet(todo_id: str, user_id: str, facet: str, content: str) -> bool:
    """Overwrite a facet's content. Returns False if the todo was not found."""
    field = _facet_field(facet)
    fields: dict[str, Any] = {field: content}
    updated = await todo_repository.update(todo_id, user_id=user_id, update=TodoUpdate(**fields))
    if updated is not None:
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


async def read_artifacts(todo_id: str, user_id: str) -> list[dict[str, Any]] | None:
    """Read the todo's artifacts list. Returns None only when the todo is missing."""
    doc = await todo_repository.get(todo_id, user_id=user_id)
    if doc is None:
        return None
    return [artifact.model_dump() for artifact in doc.artifacts]
