"""User-todos VFS catalog materialization for ``/workspace/todos/``.

This is the USER's own todo list (the one in the UI) — NOT GAIA's
institutional memory (which lives at ``/workspace/gaia-tasks/``).

Lighter than the gaia-tasks materializer:

* Only ``meta.json`` per todo (no canvas / log).
* 7-day completion window (vs 30 for gaia-tasks) — user todos are
  high-churn, completed items rarely need re-reading.
* ``index.md`` carries a due-date suffix + a priority glyph because
  the agent uses this view as a quick "what's on the user's plate".

Layout under ``<user_root>/todos/``::

    GUIDE.md                          hand-authored, mode 0644
    index.md                          generated summary, mode 0644
    <slug>-<shortid>/
        meta.json                     mode 0444

Marker scheme + folder naming mirror :mod:`gaia_tasks_vfs` — same
``<slug>-<shortid>`` shape so the agent reads the two areas the same
way. Shared FS / hashing / slug helpers live in
:mod:`app.services.storage._vfs_common`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from app.services.storage._vfs_common import (
    GUIDE_FILENAME,
    INDEX_FILENAME,
    META_FILENAME,
    folder_name as common_folder_name,
    hash_meta_only,
    meta_body,
    per_doc_marker_path,
    prune_per_doc_markers,
    read_marker,
    remove_tree,
    updated_at_key,
    write_marker,
    write_readonly_body,
    write_rw_body,
    write_rw_if_changed,
)

# --- Path constants ---------------------------------------------------------

USER_TODOS_DIRNAME = "todos"
USER_TODOS_MARKER = ".gaia/user-todos.v"
USER_TODOS_PER_DOC_MARKER_DIR = ".gaia/user-todos"


class UserTodoProjection(TypedDict):
    """In-memory shape passed from the Mongo glue to the materializer."""

    id: str
    meta: dict[str, Any]


# ====================================================================
# signatures (per-doc body is just meta — no canvas/log)
# ====================================================================


def per_doc_signature(doc: UserTodoProjection) -> str:
    """sha256 of canonical meta JSON — gates per-folder rewrite."""
    return hash_meta_only(doc["meta"])


# ====================================================================
# marker accessors (re-exported for the Mongo glue)
# ====================================================================


def user_todos_marker_path(user_root: Path) -> Path:
    return user_root / USER_TODOS_MARKER


def user_todos_per_doc_dir(user_root: Path) -> Path:
    return user_root / USER_TODOS_PER_DOC_MARKER_DIR


def read_user_todos_marker(user_root: Path) -> str | None:
    """Catalog marker reader — kept for backwards-compatible imports."""
    return read_marker(user_todos_marker_path(user_root))


def write_user_todos_marker(user_root: Path, value: str) -> None:
    """Catalog marker writer — kept for backwards-compatible imports."""
    write_marker(user_todos_marker_path(user_root), value)


# ====================================================================
# index.md rendering
# ====================================================================


def _glyph(meta: dict[str, Any]) -> str:
    if meta.get("completed"):
        return "DONE"
    if meta.get("priority") == "high":
        return "!!  "
    return "OPEN"


def _folder_name(doc: UserTodoProjection) -> str:
    return common_folder_name(doc["id"], doc["meta"].get("title"))


def _index_line(doc: UserTodoProjection) -> str:
    meta = doc["meta"]
    title = (meta.get("title") or "(untitled)").replace("\n", " ").strip()
    updated = updated_at_key(meta) or "—"
    due = meta.get("due_date")
    due_suffix = f"  due={due}" if due else ""
    return f"- [{_glyph(meta)}] `{_folder_name(doc)}`  {title}{due_suffix}  _(updated {updated})_"


def _index_lines(docs: list[UserTodoProjection]) -> str:
    header = (
        "<!-- Generated index of the user's active todos. Sorted by "
        "last-updated, newest first. Do not edit — regenerated on every "
        "sync. -->\n"
    )
    sorted_docs = sorted(docs, key=lambda d: updated_at_key(d["meta"]), reverse=True)
    if not sorted_docs:
        return header + "\n# No active user todos.\n"
    return "\n".join([header, "", *(_index_line(d) for d in sorted_docs)]) + "\n"


# ====================================================================
# materialize — split into named steps for readability
# ====================================================================


def materialize_user_todos(user_root: Path, docs: list[UserTodoProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/todos/``.

    Returns the number of meta bodies rewritten (excluding GUIDE / index).
    """
    todos_root = user_root / USER_TODOS_DIRNAME
    todos_root.mkdir(parents=True, exist_ok=True)
    write_rw_if_changed(todos_root / GUIDE_FILENAME, guide_md)

    written, expected_folders = _write_changed_docs(user_root, todos_root, docs)
    _remove_stale_folders(todos_root, expected_folders)
    prune_per_doc_markers(user_todos_per_doc_dir(user_root), {d["id"] for d in docs})
    write_rw_body(todos_root / INDEX_FILENAME, _index_lines(docs))
    return written


def _write_changed_docs(
    user_root: Path, todos_root: Path, docs: list[UserTodoProjection]
) -> tuple[int, set[str]]:
    """Write the per-doc bodies that changed; return (count, expected folder names)."""
    expected: set[str] = set()
    written = 0
    per_doc_dir = user_todos_per_doc_dir(user_root)
    for doc in docs:
        fname = _folder_name(doc)
        expected.add(fname)
        sig = per_doc_signature(doc)
        folder = todos_root / fname
        marker_path = per_doc_marker_path(per_doc_dir, doc["id"])
        if read_marker(marker_path) == sig and folder.is_dir():
            continue

        folder.mkdir(parents=True, exist_ok=True)
        write_readonly_body(folder / META_FILENAME, meta_body(doc["meta"]))
        write_marker(marker_path, sig)
        written += 1
    return written, expected


def _remove_stale_folders(todos_root: Path, expected: set[str]) -> None:
    """Remove subdirectories of ``todos_root`` not in ``expected``."""
    for child in todos_root.iterdir():
        if child.is_dir() and child.name not in expected:
            remove_tree(child)


# Public surface used by :mod:`app.services.user_todos_fs`. Generic
# helpers live in ``_vfs_common`` — import them from there in the
# Mongo glue, not via this module.
__all__ = [
    "USER_TODOS_DIRNAME",
    "USER_TODOS_MARKER",
    "USER_TODOS_PER_DOC_MARKER_DIR",
    "UserTodoProjection",
    "materialize_user_todos",
    "per_doc_signature",
    "read_user_todos_marker",
    "user_todos_marker_path",
    "write_user_todos_marker",
]
