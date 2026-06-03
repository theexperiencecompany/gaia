"""Gaia-tasks VFS catalog materialization for ``/workspace/gaia-tasks/``.

MongoDB is the source of truth. The on-disk tree is a hash-gated
projection — steady-state turns do zero I/O because both the catalog
marker (``.gaia/gaia-tasks.v``) and per-doc markers
(``.gaia/gaia-tasks/<id>.v``) short-circuit unchanged content.

Layout under ``<user_root>/gaia-tasks/``::

    GUIDE.md                          hand-authored, mode 0644
    index.md                          generated summary, mode 0644
    <slug>-<shortid>/
        canvas.md                     mode 0444
        log.md                        mode 0444
        meta.json                     mode 0444

Folder names are ``<slug>-<shortid>``: kebab-case title (≤ 40 chars) +
first 8 hex chars of the Mongo ObjectId. Title rename → stale folder
removed, fresh folder written under the new slug on next sync.

This module reuses shared FS/marker/slug helpers from
:mod:`app.services.storage._vfs_common`. The Mongo glue lives in
:mod:`app.services.gaia_tasks_fs`.

A one-shot migration step (:func:`cleanup_legacy_todos_dir`) removes
the prior release's ``/workspace/todos/`` projection on the first sync
per user — kept for a release or two and then safe to delete along with
the legacy constants below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from app.services.storage._vfs_common import (
    GUIDE_FILENAME,
    INDEX_FILENAME,
    META_FILENAME,
    folder_name as common_folder_name,
    hash_body_with_meta,
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

GAIA_TASKS_DIRNAME = "gaia-tasks"
GAIA_TASKS_MARKER = ".gaia/gaia-tasks.v"
GAIA_TASKS_PER_DOC_MARKER_DIR = ".gaia/gaia-tasks"
CANVAS_FILENAME = "canvas.md"
LOG_FILENAME = "log.md"

# --- Legacy paths (one-shot migration from the prior release) ---------------

LEGACY_TODOS_DIRNAME = "todos"
LEGACY_TODOS_MARKER = ".gaia/todos.v"
LEGACY_TODOS_PER_DOC_MARKER_DIR = ".gaia/todos"


class GaiaTaskProjection(TypedDict):
    """In-memory shape passed from the Mongo glue to the materializer."""

    id: str
    canvas: str
    log: str
    meta: dict[str, Any]


# ====================================================================
# signatures (per-doc body shape is canvas + log + meta)
# ====================================================================


def per_doc_signature(doc: GaiaTaskProjection) -> str:
    """sha256 of canvas + log + serialized meta — gates per-folder rewrite."""
    return hash_body_with_meta(doc["canvas"], doc["log"], doc["meta"])


# ====================================================================
# marker accessors (re-exported as named public API for the Mongo glue)
# ====================================================================


def gaia_tasks_marker_path(user_root: Path) -> Path:
    return user_root / GAIA_TASKS_MARKER


def gaia_tasks_per_doc_dir(user_root: Path) -> Path:
    return user_root / GAIA_TASKS_PER_DOC_MARKER_DIR


def read_gaia_tasks_marker(user_root: Path) -> str | None:
    """Catalog marker reader — kept for backwards-compatible imports."""
    return read_marker(gaia_tasks_marker_path(user_root))


def write_gaia_tasks_marker(user_root: Path, value: str) -> None:
    """Catalog marker writer — kept for backwards-compatible imports."""
    write_marker(gaia_tasks_marker_path(user_root), value)


# ====================================================================
# migration cleanup (one-shot)
# ====================================================================


def cleanup_legacy_todos_dir(user_root: Path) -> bool:
    """Remove the prior release's ``/todos/`` projection if present.

    Detection rule: presence of ``.gaia/todos.v`` (the legacy marker
    only the prior release wrote). We do NOT touch ``/todos/`` without
    the marker present, because in the new layout that path belongs to
    the user-todos materializer.

    Returns ``True`` if anything was deleted (useful for telemetry).
    Idempotent — subsequent calls return ``False``.
    """
    legacy_marker = user_root / LEGACY_TODOS_MARKER
    if not legacy_marker.exists():
        return False
    remove_tree(user_root / LEGACY_TODOS_DIRNAME)
    remove_tree(user_root / LEGACY_TODOS_PER_DOC_MARKER_DIR)
    legacy_marker.unlink(missing_ok=True)
    return True


# ====================================================================
# index.md rendering
# ====================================================================


def _glyph(meta: dict[str, Any]) -> str:
    return "DONE" if meta.get("completed") else "OPEN"


def _folder_name(doc: GaiaTaskProjection) -> str:
    return common_folder_name(doc["id"], doc["meta"].get("title"))


def _index_lines(docs: list[GaiaTaskProjection]) -> str:
    header = (
        "<!-- Generated index of active gaia-tasks. Sorted by "
        "last-updated, newest first. Do not edit — regenerated on every "
        "sync. -->\n"
    )
    sorted_docs = sorted(docs, key=lambda d: updated_at_key(d["meta"]), reverse=True)
    if not sorted_docs:
        return header + "\n# No active gaia-tasks.\n"
    body = []
    for d in sorted_docs:
        meta = d["meta"]
        title = (meta.get("title") or "(untitled)").replace("\n", " ").strip()
        updated = updated_at_key(meta) or "—"
        body.append(f"- [{_glyph(meta)}] `{_folder_name(d)}`  {title}  _(updated {updated})_")
    return "\n".join([header, "", *body]) + "\n"


# ====================================================================
# materialize — split into named steps for readability
# ====================================================================


def materialize_gaia_tasks(user_root: Path, docs: list[GaiaTaskProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/gaia-tasks/``.

    Returns the number of task bodies rewritten (excluding GUIDE / index).
    """
    cleanup_legacy_todos_dir(user_root)

    tasks_root = user_root / GAIA_TASKS_DIRNAME
    tasks_root.mkdir(parents=True, exist_ok=True)
    write_rw_if_changed(tasks_root / GUIDE_FILENAME, guide_md)

    written, expected_folders = _write_changed_docs(user_root, tasks_root, docs)
    _remove_stale_folders(tasks_root, expected_folders)
    prune_per_doc_markers(gaia_tasks_per_doc_dir(user_root), {d["id"] for d in docs})
    write_rw_body(tasks_root / INDEX_FILENAME, _index_lines(docs))
    return written


def _write_changed_docs(
    user_root: Path, tasks_root: Path, docs: list[GaiaTaskProjection]
) -> tuple[int, set[str]]:
    """Write the per-doc bodies that changed; return (count, expected folder names)."""
    expected: set[str] = set()
    written = 0
    per_doc_dir = gaia_tasks_per_doc_dir(user_root)
    for doc in docs:
        fname = _folder_name(doc)
        expected.add(fname)
        sig = per_doc_signature(doc)
        folder = tasks_root / fname
        marker_path = per_doc_marker_path(per_doc_dir, doc["id"])
        if read_marker(marker_path) == sig and folder.is_dir():
            continue

        folder.mkdir(parents=True, exist_ok=True)
        write_readonly_body(folder / CANVAS_FILENAME, doc["canvas"])
        write_readonly_body(folder / LOG_FILENAME, doc["log"])
        write_readonly_body(folder / META_FILENAME, meta_body(doc["meta"]))
        write_marker(marker_path, sig)
        written += 1
    return written, expected


def _remove_stale_folders(tasks_root: Path, expected: set[str]) -> None:
    """Remove subdirectories of ``tasks_root`` not in ``expected``."""
    for child in tasks_root.iterdir():
        if child.is_dir() and child.name not in expected:
            remove_tree(child)


# Public surface used by :mod:`app.services.gaia_tasks_fs`. Generic
# helpers (``catalog_signature``, ``read_marker``, ``write_marker``)
# live in ``_vfs_common`` — import them from there in the Mongo glue,
# not via this module.
__all__ = [
    "GAIA_TASKS_DIRNAME",
    "GAIA_TASKS_MARKER",
    "GAIA_TASKS_PER_DOC_MARKER_DIR",
    "GaiaTaskProjection",
    "cleanup_legacy_todos_dir",
    "gaia_tasks_marker_path",
    "materialize_gaia_tasks",
    "per_doc_signature",
    "read_gaia_tasks_marker",
    "write_gaia_tasks_marker",
]
