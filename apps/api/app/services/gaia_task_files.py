"""Path router for ``/workspace/gaia-tasks/`` inside the coding tools.

The agent reads and edits a tracked todo's working notes with the ordinary
``read`` / ``write`` / ``edit`` tools at
``/workspace/gaia-tasks/<slug>-<shortid>/{canvas.md,activity.md}``. Those
bodies live on the todo document (see ``todo_canvas_storage``), and the disk
tree is a read-only projection, so the tools route these paths here instead
of touching the filesystem — which also makes them work in native dev, where
the projection does not exist at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
from app.services.gaia_tasks_fs import fetch_active_projections, project_gaia_task
from app.services.storage._vfs_common import INDEX_FILENAME, meta_body
from app.services.storage.gaia_tasks_vfs import GAIA_TASKS_DIRNAME, render_index
from app.services.todo_canvas_storage import write_activity, write_canvas
from app.services.tracked_todo_service import tracked_todo_service
from shared.py.wide_events import log


class GaiaTaskFile(StrEnum):
    CANVAS = "canvas.md"
    ACTIVITY = "activity.md"
    LOG = "log.md"
    META = "meta.json"


WRITABLE_FILES = frozenset({GaiaTaskFile.CANVAS, GaiaTaskFile.ACTIVITY})


@dataclass(frozen=True)
class RootFile:
    """A generated file at the gaia-tasks root (only ``index.md`` today)."""

    name: str


@dataclass(frozen=True)
class TaskFile:
    todo: TodoDocument
    filename: GaiaTaskFile


GaiaTaskPath = RootFile | TaskFile


class GaiaTaskPathError(ValueError):
    """A gaia-tasks path that names a todo we cannot resolve to exactly one doc."""


class NoteConflictError(Exception):
    """A note write lost a revision race against a concurrent writer.

    Raised by write_file when the todo still exists but its revision moved
    since the caller resolved it. Callers holding a re-appliable patch should
    re-resolve and retry; full-body writers should report and stop.
    """


async def resolve(rel: str, user_id: str) -> GaiaTaskPath | None:
    """Map a workspace-relative path to a virtual gaia-tasks file.

    Returns None for paths this router does not own (not under gaia-tasks/,
    unknown filenames, nested paths) so the caller falls through to disk.
    Raises GaiaTaskPathError when the folder segment cannot be resolved.
    """
    parts = rel.split("/")
    if parts[0] != GAIA_TASKS_DIRNAME:
        # A relative "gaia-tasks/..." resolves into the session scratch dir;
        # hand back the absolute path the caller meant instead of "not found".
        if GAIA_TASKS_DIRNAME in parts[1:]:
            tail = "/".join(parts[parts.index(GAIA_TASKS_DIRNAME) :])
            raise GaiaTaskPathError(
                f"tracked-todo files live at /workspace/{GAIA_TASKS_DIRNAME}/ (absolute path); "
                f"use /workspace/{tail}"
            )
        return None
    if len(parts) == 2:
        return RootFile(name=parts[1]) if parts[1] == INDEX_FILENAME else None
    if len(parts) != 3 or parts[2] not in GaiaTaskFile:
        return None
    todo = await _resolve_folder(parts[1], user_id)
    return TaskFile(todo=todo, filename=GaiaTaskFile(parts[2]))


async def _resolve_folder(folder: str, user_id: str) -> TodoDocument:
    if todo_repository.is_valid_id(folder):
        doc = await todo_repository.get(folder, user_id=user_id)
        if doc is None:
            raise GaiaTaskPathError(f"no tracked todo with id {folder}")
        if GAIA_TRACKED_LABEL not in doc.labels:
            raise GaiaTaskPathError(f"{folder} is not a tracked todo (no canvas)")
        return doc
    suffix = folder.rsplit("-", 1)[-1]
    matches = await todo_repository.find_tracked_by_short_id(user_id, short_id=suffix)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise GaiaTaskPathError(
            f"no tracked todo matches folder '{folder}'; ls /workspace/{GAIA_TASKS_DIRNAME}/ "
            "or read its index.md for the current folder names"
        )
    ids = ", ".join(sorted(m.id for m in matches))
    raise GaiaTaskPathError(
        f"folder '{folder}' matches {len(matches)} tracked todos ({ids}); "
        "use the full todo id as the folder name instead"
    )


async def read_file(ref: GaiaTaskPath, user_id: str) -> str:
    if isinstance(ref, RootFile):
        return render_index(await fetch_active_projections(user_id))
    doc = ref.todo
    match ref.filename:
        case GaiaTaskFile.CANVAS:
            return doc.canvas_content or ""
        case GaiaTaskFile.ACTIVITY:
            return doc.activity_content or ""
        case GaiaTaskFile.LOG:
            return doc.log_content or ""
        case GaiaTaskFile.META:
            return meta_body(project_gaia_task(doc)["meta"])


def write_refusal(ref: GaiaTaskPath) -> str | None:
    """Why this path cannot be written, or None when it can."""
    if isinstance(ref, RootFile):
        return f"Error: {ref.name} is generated from the todos and cannot be edited."
    if ref.filename not in WRITABLE_FILES:
        return (
            f"Error: {ref.filename.value} is system-written. Only canvas.md and "
            "activity.md are editable under gaia-tasks/."
        )
    return None


async def write_file(ref: GaiaTaskPath, user_id: str, content: str) -> str | None:
    """Persist a write to canvas.md / activity.md. Returns a refusal message
    for anything else, None on success."""
    refusal = write_refusal(ref)
    if refusal is not None or not isinstance(ref, TaskFile):
        return refusal
    writer = write_canvas if ref.filename is GaiaTaskFile.CANVAS else write_activity
    if not await writer(ref.todo.id, user_id, content, expected_updated_at=ref.todo.updated_at):
        # The guarded write matched nothing: either the todo is gone or a
        # concurrent writer moved the revision. Re-read to tell them apart.
        if await todo_repository.get(ref.todo.id, user_id=user_id) is None:
            return f"Error: tracked todo {ref.todo.id} no longer exists."
        raise NoteConflictError(ref.todo.id)
    try:
        await tracked_todo_service.system_log(
            todo_id=ref.todo.id,
            user_id=user_id,
            event_type="CANVAS_UPDATED",
            details=f"Agent wrote {ref.filename.value} ({len(content)} chars)",
        )
    except Exception as e:
        log.warning(
            "gaia task audit log failed",
            error_type=type(e).__name__,
            todo_id=ref.todo.id,
            user_id=user_id,
            exc_info=True,
        )
    return None


__all__ = [
    "GaiaTaskFile",
    "GaiaTaskPath",
    "GaiaTaskPathError",
    "NoteConflictError",
    "RootFile",
    "TaskFile",
    "read_file",
    "resolve",
    "write_file",
    "write_refusal",
]
