"""Tracked-todo VFS catalog materialization for /workspace/todos/.

Source of truth is MongoDB. This module is hash-gated: it rewrites
nothing when ``.gaia/todos.v`` matches the expected catalog signature
AND every per-todo ``.gaia/todos/<id>.v`` matches its body signature.
Steady-state turns do zero I/O.

Layout produced under ``<user_root>/todos/``::

    GUIDE.md                  hand-authored, mode 0644
    index.md                  generated summary, mode 0644
    <todo_id>/
        canvas.md             mode 0444
        log.md                mode 0444
        meta.json             mode 0444

Markers under ``<user_root>/.gaia/``::

    todos.v                   sha256 of (id, per_doc_sig) pairs
    todos/<todo_id>.v         sha256 of body (canvas + log + meta)

The agent does not look under ``.gaia/``. Markers live there because
``.gaia/skills.v`` already does.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, TypedDict

TODOS_DIRNAME = "todos"
TODOS_MARKER = ".gaia/todos.v"
TODOS_PER_DOC_MARKER_DIR = ".gaia/todos"
CANVAS_FILENAME = "canvas.md"
LOG_FILENAME = "log.md"
META_FILENAME = "meta.json"
INDEX_FILENAME = "index.md"
GUIDE_FILENAME = "GUIDE.md"
READONLY_MODE = 0o444
RW_MODE = 0o644


class TodoProjection(TypedDict):
    """In-memory shape passed from the Mongo glue to the materializer."""

    id: str
    canvas: str
    log: str
    meta: dict[str, Any]


def per_doc_signature(doc: TodoProjection) -> str:
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
    """Hash of the sorted (id, per_doc_sig) pairs — gates the full sync."""
    joined = "\n".join(f"{tid}:{sig}" for tid, sig in sorted(per_doc.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def read_todos_marker(user_root: Path) -> str | None:
    """Return the recorded catalog hash, or ``None`` if missing/unreadable."""
    marker = user_root / TODOS_MARKER
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_todos_marker(user_root: Path, value: str) -> None:
    """Stamp the catalog hash. Creates parent dirs as needed."""
    marker = user_root / TODOS_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def read_per_doc_marker(user_root: Path, todo_id: str) -> str | None:
    """Return the recorded per-todo body hash, or ``None`` if missing."""
    marker = user_root / TODOS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_per_doc_marker(user_root: Path, todo_id: str, value: str) -> None:
    """Stamp a per-todo body hash. Creates parent dirs as needed."""
    marker = user_root / TODOS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


def _delete_per_doc_marker(user_root: Path, todo_id: str) -> None:
    """Remove a per-todo marker if present. Idempotent."""
    marker = user_root / TODOS_PER_DOC_MARKER_DIR / f"{todo_id}.v"
    marker.unlink(missing_ok=True)


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
    """Single-char glyph for the ``index.md`` line."""
    if meta.get("completed"):
        return "DONE"
    return "OPEN"


def _index_lines(docs: list[TodoProjection]) -> str:
    """Build ``index.md``: one line per todo, sorted by updated_at desc."""

    def _updated_at(d: TodoProjection) -> str:
        v = d["meta"].get("updated_at") or d["meta"].get("created_at") or ""
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)

    sorted_docs = sorted(docs, key=_updated_at, reverse=True)
    header = (
        "<!-- Generated index of active tracked todos. Sorted by last-updated, "
        "newest first. Do not edit — regenerated on every sync. -->\n"
    )
    if not sorted_docs:
        return header + "\n# No active tracked todos.\n"

    lines = [header, ""]
    for d in sorted_docs:
        meta = d["meta"]
        glyph = _status_glyph(meta)
        title = (meta.get("title") or "(untitled)").replace("\n", " ").strip()
        updated = _updated_at(d) or "—"
        lines.append(f"- [{glyph}] `{d['id']}`  {title}  _(updated {updated})_")
    return "\n".join(lines) + "\n"


def materialize_todos(user_root: Path, docs: list[TodoProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/todos/``.

    Returns the number of todo bodies (canvas/log/meta triples) rewritten,
    not counting GUIDE.md / index.md. Callers can use it as a "did
    anything change?" signal for telemetry.

    Algorithm:

    1. Ensure ``todos/`` exists.
    2. Rewrite ``GUIDE.md`` only if its content differs.
    3. For each doc, compare per-doc signature; on mismatch, rewrite
       the three body files (mode 0444) and update the per-doc marker.
    4. Remove any on-disk folder whose id is not in ``docs``.
    5. Always rewrite ``index.md`` (small; not worth hashing).
    """
    todos_root = user_root / TODOS_DIRNAME
    todos_root.mkdir(parents=True, exist_ok=True)

    guide_path = todos_root / GUIDE_FILENAME
    if not _matches_text(guide_path, guide_md):
        guide_path.write_text(guide_md, encoding="utf-8")
        guide_path.chmod(RW_MODE)

    written = 0
    seen_ids: set[str] = set()
    for doc in docs:
        seen_ids.add(doc["id"])
        sig = per_doc_signature(doc)
        if read_per_doc_marker(user_root, doc["id"]) == sig:
            continue

        folder = todos_root / doc["id"]
        folder.mkdir(parents=True, exist_ok=True)
        _write_readonly(folder / CANVAS_FILENAME, doc["canvas"])
        _write_readonly(folder / LOG_FILENAME, doc["log"])
        _write_readonly(folder / META_FILENAME, _meta_body(doc["meta"]))
        write_per_doc_marker(user_root, doc["id"], sig)
        written += 1

    for child in todos_root.iterdir():
        if child.is_dir() and child.name not in seen_ids:
            shutil.rmtree(child, ignore_errors=True)
            _delete_per_doc_marker(user_root, child.name)

    index_path = todos_root / INDEX_FILENAME
    index_path.write_text(_index_lines(docs), encoding="utf-8")
    index_path.chmod(RW_MODE)

    return written
