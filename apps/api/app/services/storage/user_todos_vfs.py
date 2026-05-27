"""User-todos VFS catalog materialization for /workspace/todos/.

This is the USER's own todo list (the list they see in the UI), NOT
GAIA's institutional memory (which lives at /workspace/gaia-tasks/).

Lighter than the gaia-tasks materializer: only ``meta.json`` per todo,
no ``canvas.md`` / ``log.md``. Active window is 7 days (vs 30 for
gaia-tasks) because the user-todo list is higher-churn — completed
items are less likely to be re-read.

Layout produced under ``<user_root>/todos/``::

    GUIDE.md                                hand-authored, mode 0644
    index.md                                generated summary, mode 0644
    <slug>-<shortid>/
        meta.json                           mode 0444

Markers under ``<user_root>/.gaia/``::

    user-todos.v                            sha256 of (id, per_doc_sig) pairs
    user-todos/<todo_id>.v                  sha256 of meta-only body

Folder name format matches gaia-tasks: ``<slug>-<shortid>`` (kebab-case
title + first 8 hex of ObjectId).
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, TypedDict

from app.services.storage.gaia_tasks_vfs import (
    GUIDE_FILENAME,
    INDEX_FILENAME,
    META_FILENAME,
    READONLY_MODE,
    RW_MODE,
    _force_remove,
    _matches_text,
    _meta_body,
    _write_readonly,
    folder_name as _gaia_folder_name,
    slugify,
)

USER_TODOS_DIRNAME = "todos"
USER_TODOS_MARKER = ".gaia/user-todos.v"
USER_TODOS_PER_DOC_MARKER_DIR = ".gaia/user-todos"


class UserTodoProjection(TypedDict):
    """In-memory shape passed from the Mongo glue to the materializer."""

    id: str
    meta: dict[str, Any]


def folder_name(doc: UserTodoProjection) -> str:
    """``<slug>-<shortid>`` — same shape as gaia-tasks for consistency."""
    return _gaia_folder_name({"id": doc["id"], "canvas": "", "log": "", "meta": doc["meta"]})  # type: ignore[typeddict-item]


def per_doc_signature(doc: UserTodoProjection) -> str:
    """Stable hash of serialized meta (no canvas/log for user todos)."""
    payload = json.dumps(doc["meta"], sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def catalog_signature(per_doc: dict[str, str]) -> str:
    """Hash of the sorted ``(id, per_doc_sig)`` pairs — gates the full sync."""
    joined = "\n".join(f"{tid}:{sig}" for tid, sig in sorted(per_doc.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def read_user_todos_marker(user_root: Path) -> str | None:
    """Return the recorded catalog hash, or ``None`` if missing/unreadable."""
    marker = user_root / USER_TODOS_MARKER
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_user_todos_marker(user_root: Path, value: str) -> None:
    """Stamp the catalog hash. Creates parent dirs as needed."""
    marker = user_root / USER_TODOS_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def read_per_doc_marker(user_root: Path, todo_id: str) -> str | None:
    """Return the recorded per-todo meta hash, or ``None`` if missing."""
    marker = user_root / USER_TODOS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_per_doc_marker(user_root: Path, todo_id: str, value: str) -> None:
    """Stamp a per-todo meta hash. Creates parent dirs as needed."""
    marker = user_root / USER_TODOS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def _status_glyph(meta: dict[str, Any]) -> str:
    """Single-token glyph for the ``index.md`` line."""
    if meta.get("completed"):
        return "DONE"
    if meta.get("priority") == "high":
        return "!!  "
    return "OPEN"


def _index_lines(docs: list[UserTodoProjection]) -> str:
    """Build ``index.md``: one line per todo, sorted by ``updated_at`` desc."""

    def _updated_at(d: UserTodoProjection) -> str:
        v = d["meta"].get("updated_at") or d["meta"].get("created_at") or ""
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    sorted_docs = sorted(docs, key=_updated_at, reverse=True)
    header = (
        "<!-- Generated index of the user's active todos. Sorted by "
        "last-updated, newest first. Do not edit — regenerated on every "
        "sync. -->\n"
    )
    if not sorted_docs:
        return header + "\n# No active user todos.\n"

    lines = [header, ""]
    for d in sorted_docs:
        meta = d["meta"]
        glyph = _status_glyph(meta)
        title = (meta.get("title") or "(untitled)").replace("\n", " ").strip()
        updated = _updated_at(d) or "—"
        slug = folder_name(d)
        due = meta.get("due_date")
        due_suffix = f"  due={due}" if due else ""
        lines.append(f"- [{glyph}] `{slug}`  {title}{due_suffix}  _(updated {updated})_")
    return "\n".join(lines) + "\n"


def materialize_user_todos(user_root: Path, docs: list[UserTodoProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/todos/``.

    Returns the number of meta bodies rewritten (not counting GUIDE.md /
    index.md). Same hash-gated pattern as the gaia-tasks materializer.
    Folder format ``<slug>-<shortid>`` matches gaia-tasks for consistency.
    """
    # Anything sharing a name with a slug folder is ours (the legacy
    # cleanup in gaia_tasks_vfs already nuked the previous release's
    # output at this same path before user-todos ever wrote here).
    _ = slugify  # re-exported import — silence "unused" if any
    tasks_root = user_root / USER_TODOS_DIRNAME
    tasks_root.mkdir(parents=True, exist_ok=True)

    guide_path = tasks_root / GUIDE_FILENAME
    if not _matches_text(guide_path, guide_md):
        guide_path.write_text(guide_md, encoding="utf-8")
        guide_path.chmod(RW_MODE)

    written = 0
    expected_folders: set[str] = set()
    for doc in docs:
        fname = folder_name(doc)
        expected_folders.add(fname)
        sig = per_doc_signature(doc)
        folder = tasks_root / fname
        if read_per_doc_marker(user_root, doc["id"]) == sig and folder.is_dir():
            continue

        folder.mkdir(parents=True, exist_ok=True)
        _write_readonly(folder / META_FILENAME, _meta_body(doc["meta"]))
        write_per_doc_marker(user_root, doc["id"], sig)
        written += 1

    for child in tasks_root.iterdir():
        if child.is_dir() and child.name not in expected_folders:
            shutil.rmtree(child, onerror=_force_remove)
    _cleanup_stale_per_doc_markers(user_root, {d["id"] for d in docs})

    index_path = tasks_root / INDEX_FILENAME
    index_path.write_text(_index_lines(docs), encoding="utf-8")
    index_path.chmod(RW_MODE)

    return written


def _cleanup_stale_per_doc_markers(user_root: Path, active_ids: set[str]) -> None:
    """Remove per-doc markers whose id is no longer in the active set."""
    marker_dir = user_root / USER_TODOS_PER_DOC_MARKER_DIR
    if not marker_dir.is_dir():
        return
    for marker in marker_dir.iterdir():
        if marker.is_file() and marker.suffix == ".v":
            if marker.stem not in active_ids:
                marker.unlink(missing_ok=True)


__all__ = [
    "READONLY_MODE",
    "USER_TODOS_DIRNAME",
    "USER_TODOS_MARKER",
    "USER_TODOS_PER_DOC_MARKER_DIR",
    "UserTodoProjection",
    "catalog_signature",
    "folder_name",
    "materialize_user_todos",
    "per_doc_signature",
    "read_per_doc_marker",
    "read_user_todos_marker",
    "write_per_doc_marker",
    "write_user_todos_marker",
]
