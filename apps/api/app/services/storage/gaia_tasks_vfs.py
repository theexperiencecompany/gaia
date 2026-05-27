"""Gaia-tasks VFS catalog materialization for /workspace/gaia-tasks/.

Source of truth is MongoDB. This module is hash-gated: it rewrites
nothing when ``.gaia/gaia-tasks.v`` matches the expected catalog
signature AND every per-doc ``.gaia/gaia-tasks/<id>.v`` matches its
body signature. Steady-state turns do zero I/O.

Layout produced under ``<user_root>/gaia-tasks/``::

    GUIDE.md                                hand-authored, mode 0644
    index.md                                generated summary, mode 0644
    <slug>-<shortid>/
        canvas.md                           mode 0444
        log.md                              mode 0444
        meta.json                           mode 0444

Markers under ``<user_root>/.gaia/``::

    gaia-tasks.v                            sha256 of (id, per_doc_sig) pairs
    gaia-tasks/<todo_id>.v                  sha256 of body (canvas + log + meta)

Folder names are ``<slug>-<shortid>``. ``slug`` is a kebab-case form of
the title (max 40 chars); ``shortid`` is the first 8 hex chars of the
Mongo ObjectId. The mapping is recomputed on every sync — if a title
changes, the stale folder is removed and a fresh one written.

Migration from the prior release (``/workspace/todos/`` + ``.gaia/todos.v``)
is handled by :func:`cleanup_legacy_todos_dir`, invoked at the top of
:func:`materialize_gaia_tasks`.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, TypedDict

GAIA_TASKS_DIRNAME = "gaia-tasks"
GAIA_TASKS_MARKER = ".gaia/gaia-tasks.v"
GAIA_TASKS_PER_DOC_MARKER_DIR = ".gaia/gaia-tasks"

# Legacy paths from the prior release (when these were called "todos").
# Kept for one-shot cleanup; safe to remove after a release or two.
LEGACY_TODOS_DIRNAME = "todos"
LEGACY_TODOS_MARKER = ".gaia/todos.v"
LEGACY_TODOS_PER_DOC_MARKER_DIR = ".gaia/todos"

CANVAS_FILENAME = "canvas.md"
LOG_FILENAME = "log.md"
META_FILENAME = "meta.json"
INDEX_FILENAME = "index.md"
GUIDE_FILENAME = "GUIDE.md"
READONLY_MODE = 0o444
RW_MODE = 0o644

SLUG_MAX_LEN = 40
SHORTID_LEN = 8
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")


class GaiaTaskProjection(TypedDict):
    """In-memory shape passed from the Mongo glue to the materializer."""

    id: str
    canvas: str
    log: str
    meta: dict[str, Any]


def slugify(title: str | None) -> str:
    """Lowercase, alphanumeric + dashes, max 40 chars; ``"untitled"`` on empty."""
    if not title:
        return "untitled"
    lowered = title.lower().strip()
    cleaned = _SLUG_INVALID_RE.sub("-", lowered).strip("-")
    if not cleaned:
        return "untitled"
    return cleaned[:SLUG_MAX_LEN].rstrip("-") or "untitled"


def short_id(todo_id: str) -> str:
    """First 8 hex chars of the ObjectId — sufficient within a user's set."""
    return todo_id[:SHORTID_LEN]


def folder_name(doc: GaiaTaskProjection) -> str:
    """Human-readable ``<slug>-<shortid>`` for the on-disk folder."""
    return f"{slugify(doc['meta'].get('title'))}-{short_id(doc['id'])}"


def per_doc_signature(doc: GaiaTaskProjection) -> str:
    """Stable hash of canvas + log + serialized meta."""
    payload = (
        doc["canvas"].encode("utf-8")
        + b"\x00"
        + doc["log"].encode("utf-8")
        + b"\x00"
        + json.dumps(doc["meta"], sort_keys=True, default=str).encode("utf-8")
    )
    return hashlib.sha256(payload).hexdigest()


def catalog_signature(per_doc: dict[str, str]) -> str:
    """Hash of the sorted ``(id, per_doc_sig)`` pairs — gates the full sync."""
    joined = "\n".join(f"{tid}:{sig}" for tid, sig in sorted(per_doc.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def read_gaia_tasks_marker(user_root: Path) -> str | None:
    """Return the recorded catalog hash, or ``None`` if missing/unreadable."""
    marker = user_root / GAIA_TASKS_MARKER
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_gaia_tasks_marker(user_root: Path, value: str) -> None:
    """Stamp the catalog hash. Creates parent dirs as needed."""
    marker = user_root / GAIA_TASKS_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def read_per_doc_marker(user_root: Path, todo_id: str) -> str | None:
    """Return the recorded per-todo body hash, or ``None`` if missing."""
    marker = user_root / GAIA_TASKS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_per_doc_marker(user_root: Path, todo_id: str, value: str) -> None:
    """Stamp a per-todo body hash. Creates parent dirs as needed."""
    marker = user_root / GAIA_TASKS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def cleanup_legacy_todos_dir(user_root: Path) -> bool:
    """One-shot cleanup of the prior release's ``/todos/`` projection.

    Returns ``True`` if anything was deleted (useful for telemetry).
    Idempotent — subsequent calls return ``False``.

    Detection rule: presence of ``.gaia/todos.v`` (the legacy marker the
    prior release wrote). We do NOT touch ``/todos/`` without the marker
    present, because in the new layout ``/todos/`` belongs to the
    user-todos materializer.
    """
    legacy_marker = user_root / LEGACY_TODOS_MARKER
    if not legacy_marker.exists():
        return False

    legacy_dir = user_root / LEGACY_TODOS_DIRNAME
    legacy_per_doc_dir = user_root / LEGACY_TODOS_PER_DOC_MARKER_DIR

    if legacy_dir.exists() and legacy_dir.is_dir():
        shutil.rmtree(legacy_dir, onerror=_force_remove)
    if legacy_per_doc_dir.exists() and legacy_per_doc_dir.is_dir():
        shutil.rmtree(legacy_per_doc_dir, ignore_errors=True)
    legacy_marker.unlink(missing_ok=True)
    return True


def _force_remove(func: Any, path: str, exc_info: Any) -> None:
    """``shutil.rmtree`` ``onerror`` hook: chmod target writable then retry."""
    try:
        Path(path).chmod(RW_MODE)
        func(path)
    except OSError:
        pass


def _matches_text(path: Path, expected: str) -> bool:
    """Cheap "do we need to rewrite this file?" check.

    Treats decode errors as "doesn't match" so corrupted bytes get
    rewritten rather than silently kept.
    """
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def _write_readonly(target: Path, content: str) -> None:
    """Write a projected body and chmod it to 0444.

    Unlinks the target first so a previous 0444 mode does not block the
    overwrite — POSIX ``open(O_TRUNC | O_WRONLY)`` honours the file mode
    bits even for the owner.
    """
    target.unlink(missing_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(READONLY_MODE)


def _meta_body(meta: dict[str, Any]) -> str:
    """Serialize ``meta`` to canonical JSON for on-disk storage."""
    return json.dumps(meta, sort_keys=True, default=str, indent=2) + "\n"


def _status_glyph(meta: dict[str, Any]) -> str:
    """Single-token glyph for the ``index.md`` line."""
    if meta.get("completed"):
        return "DONE"
    return "OPEN"


def _index_lines(docs: list[GaiaTaskProjection]) -> str:
    """Build ``index.md``: one line per task, sorted by ``updated_at`` desc."""

    def _updated_at(d: GaiaTaskProjection) -> str:
        v = d["meta"].get("updated_at") or d["meta"].get("created_at") or ""
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    sorted_docs = sorted(docs, key=_updated_at, reverse=True)
    header = (
        "<!-- Generated index of active gaia-tasks. Sorted by last-updated, "
        "newest first. Do not edit — regenerated on every sync. -->\n"
    )
    if not sorted_docs:
        return header + "\n# No active gaia-tasks.\n"

    lines = [header, ""]
    for d in sorted_docs:
        meta = d["meta"]
        glyph = _status_glyph(meta)
        title = (meta.get("title") or "(untitled)").replace("\n", " ").strip()
        updated = _updated_at(d) or "—"
        slug = folder_name(d)
        lines.append(f"- [{glyph}] `{slug}`  {title}  _(updated {updated})_")
    return "\n".join(lines) + "\n"


def materialize_gaia_tasks(user_root: Path, docs: list[GaiaTaskProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/gaia-tasks/``.

    Returns the number of task bodies rewritten (not counting GUIDE.md /
    index.md). Folders are named ``<slug>-<shortid>``. Runs the legacy
    ``/todos/`` cleanup before doing anything else.
    """
    cleanup_legacy_todos_dir(user_root)

    tasks_root = user_root / GAIA_TASKS_DIRNAME
    tasks_root.mkdir(parents=True, exist_ok=True)

    guide_path = tasks_root / GUIDE_FILENAME
    if not _matches_text(guide_path, guide_md):
        guide_path.write_text(guide_md, encoding="utf-8")
        guide_path.chmod(RW_MODE)

    written = 0
    expected_folders: dict[str, str] = {}
    for doc in docs:
        fname = folder_name(doc)
        expected_folders[fname] = doc["id"]
        sig = per_doc_signature(doc)
        folder = tasks_root / fname
        if read_per_doc_marker(user_root, doc["id"]) == sig and folder.is_dir():
            continue

        folder.mkdir(parents=True, exist_ok=True)
        _write_readonly(folder / CANVAS_FILENAME, doc["canvas"])
        _write_readonly(folder / LOG_FILENAME, doc["log"])
        _write_readonly(folder / META_FILENAME, _meta_body(doc["meta"]))
        write_per_doc_marker(user_root, doc["id"], sig)
        written += 1

    seen_names = set(expected_folders.keys())
    for child in tasks_root.iterdir():
        if child.is_dir() and child.name not in seen_names:
            shutil.rmtree(child, onerror=_force_remove)
    _cleanup_stale_per_doc_markers(user_root, {d["id"] for d in docs})

    index_path = tasks_root / INDEX_FILENAME
    index_path.write_text(_index_lines(docs), encoding="utf-8")
    index_path.chmod(RW_MODE)

    return written


def _cleanup_stale_per_doc_markers(user_root: Path, active_ids: set[str]) -> None:
    """Remove per-doc markers whose id is no longer in the active set."""
    marker_dir = user_root / GAIA_TASKS_PER_DOC_MARKER_DIR
    if not marker_dir.is_dir():
        return
    for marker in marker_dir.iterdir():
        if marker.is_file() and marker.suffix == ".v":
            if marker.stem not in active_ids:
                marker.unlink(missing_ok=True)
