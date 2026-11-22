"""The user's tasks as files under /workspace/tasks/, for the read, write and edit tools.

One folder per task, <slug>-<task id> (the bare task id works too), plus a generated
index.md. Every task has a read-only meta.json; a GAIA task also has notes.md and
observations.md, which GAIA rewrites, and its read-only log.md. The user's own to-dos are
read-only here: GAIA changes them with the task tools. Nothing is on disk: every read and
write goes to the task itself, so the files read the same in the sandbox and in native dev.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import json

from app.constants.tasks import Assignee
from app.constants.todos import CANVAS_SECTIONS, OBSERVATIONS_MAX_CHARS
from app.db.repositories.tasks import task_repository
from app.models.task_models import TaskDocument, TaskUpdate
from app.services.canvas_markdown import canvas_problems, with_missing_sections
from app.services.storage._vfs_common import INDEX_FILENAME, slugify
from app.services.tasks.search_index import index_task

TASKS_DIRNAME = "tasks"
#: How long a done task stays in the folder, by whose it is.
SHOWN_AFTER_DONE: dict[Assignee, timedelta] = {
    Assignee.GAIA: timedelta(days=30),
    Assignee.USER: timedelta(days=7),
}
#: The fields of a task its meta.json shows.
_META_FIELDS: set[str] = {
    "id",
    "title",
    "body",
    "assignee",
    "priority",
    "completed",
    "completed_at",
    "parent_id",
    "when",
    "next_check_at",
    "waiting",
    "subtasks",
    "status_flags",
    "references",
    "expires_at",
    "active",
    "pause_reason",
    "created_at",
    "updated_at",
}


class TaskFileName(StrEnum):
    NOTES = "notes.md"
    OBSERVATIONS = "observations.md"
    LOG = "log.md"
    META = "meta.json"


WRITABLE_FILES = (TaskFileName.NOTES, TaskFileName.OBSERVATIONS)
#: The files a to-do has; GAIA keeps no notes on the user's own to-dos.
_TO_DO_FILES = frozenset({TaskFileName.META})
# Refuses a write the router does not own, from every file tool; {rel} is the path tried.
NOT_A_NOTES_FILE = (
    "Error: {rel} is not an editable notes file. Only "
    f"{', '.join(WRITABLE_FILES)} under /workspace/{TASKS_DIRNAME}/<task>/ of a GAIA task "
    "can be edited."
)


@dataclass(frozen=True)
class IndexFile:
    """The generated index.md at the folder's root."""


@dataclass(frozen=True)
class TaskFile:
    task: TaskDocument
    name: TaskFileName


TaskPath = IndexFile | TaskFile


class TaskPathError(ValueError):
    """A tasks path that names a task or a file that does not exist."""


class NoteConflictError(Exception):
    """A notes write lost a revision race against a concurrent writer.

    Callers holding a re-appliable patch re-resolve and retry; full-body writers report.
    """


def file_path(task_id: str, name: TaskFileName) -> str:
    """Return the absolute path GAIA's file tools reach one of the task's files at."""
    return f"/workspace/{TASKS_DIRNAME}/{task_id}/{name.value}"


def folder_name(task: TaskDocument) -> str:
    """Name the task's folder: its title for a reader, its id for the router."""
    return f"{slugify(task.title)}-{task.id}"


async def resolve(rel: str, user_id: str) -> TaskPath | None:
    """Map a workspace-relative path to a task file, None for a path outside tasks/.

    Raises TaskPathError for a folder or file under tasks/ that does not exist.
    """
    parts = rel.split("/")
    if parts[0] != TASKS_DIRNAME:
        # A relative "tasks/..." resolves into the session scratch dir; name the right path.
        if TASKS_DIRNAME in parts[1:]:
            tail = "/".join(parts[parts.index(TASKS_DIRNAME) :])
            raise TaskPathError(
                f"task files live at /workspace/{TASKS_DIRNAME}/ (absolute path); "
                f"use /workspace/{tail}"
            )
        return None
    if len(parts) == 2 and parts[1] == INDEX_FILENAME:
        return IndexFile()
    if len(parts) != 3 or parts[2] not in TaskFileName:
        return None
    task = await _task_of_folder(parts[1], user_id)
    name = TaskFileName(parts[2])
    if task.assignee is Assignee.USER and name not in _TO_DO_FILES:
        raise TaskPathError(f"{task.id} is the user's own to-do: its folder holds only meta.json")
    return TaskFile(task=task, name=name)


async def _task_of_folder(folder: str, user_id: str) -> TaskDocument:
    task_id = folder.rpartition("-")[2]
    task = await task_repository.get(task_id, user_id=user_id)
    if task is None:
        raise TaskPathError(
            f"no task matches folder '{folder}'; read /workspace/{TASKS_DIRNAME}/{INDEX_FILENAME} "
            "for the folder names"
        )
    return task


async def read_file(ref: TaskPath, user_id: str) -> str:
    if isinstance(ref, IndexFile):
        return await _render_index(user_id)
    task = ref.task
    match ref.name:
        case TaskFileName.NOTES:
            return task.notes or ""
        case TaskFileName.OBSERVATIONS:
            return task.observations or ""
        case TaskFileName.LOG:
            return task.log or ""
        case TaskFileName.META:
            return json.dumps(task.model_dump(mode="json", include=_META_FIELDS), indent=2) + "\n"


async def _render_index(user_id: str) -> str:
    now = datetime.now(UTC)
    sections = [
        "<!-- Generated from your tasks on every read; do not edit. -->\n",
    ]
    for assignee, heading in (
        (Assignee.GAIA, "GAIA's tasks"),
        (Assignee.USER, "The user's to-dos"),
    ):
        window = SHOWN_AFTER_DONE[assignee]
        tasks = await task_repository.list_since(
            user_id, assignee=assignee, completed_since=now - window
        )
        tasks.sort(key=lambda task: task.updated_at, reverse=True)
        lines = [
            f"- {'DONE' if task.completed else 'OPEN'} {folder_name(task)}/  {task.title}"
            for task in tasks
        ]
        sections.append(
            f"# {heading} (open, and done in the last {window.days} days)\n"
            + ("\n".join(lines) if lines else "None.")
            + "\n"
        )
    return "\n".join(sections)


def write_refusal(ref: TaskPath) -> str | None:
    """Why this path cannot be written, or None when it can."""
    if isinstance(ref, IndexFile):
        return f"Error: {INDEX_FILENAME} is generated from the tasks and cannot be edited."
    if ref.task.assignee is Assignee.USER:
        return (
            f"Error: {ref.task.id} is the user's own to-do; change it with update_task, "
            "never by editing its file."
        )
    if ref.name not in WRITABLE_FILES:
        return (
            f"Error: {ref.name.value} is written by GAIA itself. Only "
            f"{', '.join(WRITABLE_FILES)} are editable under {TASKS_DIRNAME}/."
        )
    return None


def _content_refusal(ref: TaskFile, content: str) -> str | None:
    """Why this body breaks its file's shape, or None when it may be saved."""
    if ref.name is TaskFileName.OBSERVATIONS:
        if len(content) <= OBSERVATIONS_MAX_CHARS:
            return None
        return (
            f"Error: observations.md was not saved: {len(content)} characters, over its "
            f"{OBSERVATIONS_MAX_CHARS}. Fold the oldest daily counts into earlier and drop "
            "the entries seen least recently."
        )
    if problems := canvas_problems(content):
        return (
            f"Error: notes.md was not saved: {'; '.join(problems)}. The notes keep one "
            f"section each for {', '.join(CANVAS_SECTIONS)} (plus any of your own); "
            "what happened when belongs in the task's log, which GAIA writes."
        )
    return None


async def write_file(ref: TaskPath, user_id: str, content: str) -> str | None:
    """Save a write to GAIA's notes or observations; the refusal message, or None once saved."""
    refusal = write_refusal(ref)
    if refusal is not None or not isinstance(ref, TaskFile):
        return refusal
    if refusal := _content_refusal(ref, content):
        return refusal
    update = (
        TaskUpdate(notes=with_missing_sections(content))
        if ref.name is TaskFileName.NOTES
        else TaskUpdate(observations=content)
    )
    written = await task_repository.replace_notes(
        ref.task.id, user_id, update=update, expected_updated_at=ref.task.updated_at
    )
    if written is None:
        # The guarded write matched nothing: the task is gone, or a concurrent writer
        # moved its revision. Re-read to tell them apart.
        if await task_repository.get(ref.task.id, user_id=user_id) is None:
            return f"Error: task {ref.task.id} no longer exists."
        raise NoteConflictError(ref.task.id)
    await index_task(written)
    return None
