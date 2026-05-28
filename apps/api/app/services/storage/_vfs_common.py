"""Shared building blocks for VFS materializers under ``/workspace/``.

The two materializers (``gaia_tasks_vfs``, ``user_todos_vfs``) project
MongoDB state into JuiceFS as a hash-gated tree of folders. They differ
only in:

* what fields make up the per-doc body (canvas+log+meta vs meta-only),
* the active-set Mongo filter,
* the on-disk path constants,
* the prose in ``GUIDE.md`` and the glyphs in ``index.md``.

Everything else — slug/shortid naming, marker read/write, the
``shutil.rmtree`` chmod-and-retry hook, the meta-JSON encoding, the
"only rewrite if changed" guard — is identical and lives here. Keep
this module dependency-free (no app imports) so it stays cheap to load
and safe to reference from anywhere in ``app.services.storage``.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any

# --- Filenames every materializer agrees on ---------------------------------

META_FILENAME = "meta.json"
INDEX_FILENAME = "index.md"
GUIDE_FILENAME = "GUIDE.md"

# --- File modes -------------------------------------------------------------
#
# Projected bodies (canvas / log / meta) are read-only so raw `Edit` from
# the agent fails loudly instead of silently desyncing the projection.
# GUIDE / index are author-writable because we rewrite them on every sync.

READONLY_MODE = 0o444
RW_MODE = 0o644

# --- Slug / shortid policy --------------------------------------------------

SLUG_MAX_LEN = 40
SHORTID_LEN = 8
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_UNTITLED = "untitled"


# ====================================================================
# naming
# ====================================================================


def slugify(title: str | None) -> str:
    """Lowercase, alphanumeric + dashes, ≤ 40 chars; ``"untitled"`` on empty."""
    if not title:
        return _UNTITLED
    cleaned = _SLUG_INVALID_RE.sub("-", title.lower().strip()).strip("-")
    if not cleaned:
        return _UNTITLED
    return cleaned[:SLUG_MAX_LEN].rstrip("-") or _UNTITLED


def short_id(doc_id: str) -> str:
    """First 8 hex chars of the ObjectId — sufficient within a user's set."""
    return doc_id[:SHORTID_LEN]


def folder_name(doc_id: str, title: str | None) -> str:
    """Human-readable ``<slug>-<shortid>`` folder name."""
    return f"{slugify(title)}-{short_id(doc_id)}"


# ====================================================================
# hashing
# ====================================================================


def hash_meta_only(meta: dict[str, Any]) -> str:
    """sha256 of the canonical JSON encoding of ``meta``."""
    payload = json.dumps(meta, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_body_with_meta(canvas: str, log_text: str, meta: dict[str, Any]) -> str:
    """sha256 of canvas + log + meta, NUL-separated.

    Used by materializers that project a body bigger than just the
    metadata (currently only ``gaia_tasks_vfs``).
    """
    h = hashlib.sha256()
    h.update(canvas.encode("utf-8"))
    h.update(b"\x00")
    h.update(log_text.encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(meta, sort_keys=True, default=str).encode("utf-8"))
    return h.hexdigest()


def catalog_signature(per_doc: dict[str, str]) -> str:
    """Stable hash of sorted ``id:sig`` pairs — gates the full sync."""
    joined = "\n".join(f"{tid}:{sig}" for tid, sig in sorted(per_doc.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ====================================================================
# markers
# ====================================================================


def read_marker(path: Path) -> str | None:
    """Return marker contents (stripped), or ``None`` if missing/unreadable."""
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def write_marker(path: Path, value: str) -> None:
    """Stamp the marker. Creates parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def per_doc_marker_path(per_doc_dir: Path, doc_id: str) -> Path:
    """Conventional path for a per-doc marker file inside ``per_doc_dir``."""
    return per_doc_dir / f"{doc_id}.v"


def prune_per_doc_markers(per_doc_dir: Path, active_ids: set[str]) -> None:
    """Remove per-doc markers whose id is no longer in ``active_ids``."""
    if not per_doc_dir.is_dir():
        return
    for marker in per_doc_dir.iterdir():
        if marker.is_file() and marker.suffix == ".v" and marker.stem not in active_ids:
            marker.unlink(missing_ok=True)


# ====================================================================
# filesystem
# ====================================================================


def _force_remove(func: Any, path: str, _exc_info: Any) -> None:
    """``shutil.rmtree`` ``onerror`` hook: chmod target writable then retry.

    POSIX requires write permission on the file itself (not just the
    directory) to ``unlink``. Our projected bodies are 0444, so naïve
    ``rmtree`` would fail mid-tree.
    """
    try:
        Path(path).chmod(RW_MODE)
        func(path)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    """Recursively remove ``path``; tolerate 0444 children. No-op if missing."""
    if path.exists() and path.is_dir():
        shutil.rmtree(path, onerror=_force_remove)


def matches_text(path: Path, expected: str) -> bool:
    """Cheap "do we need to rewrite this file?" check.

    Treats decode errors as "doesn't match" so corrupted bytes get
    rewritten rather than silently kept.
    """
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def write_readonly_body(target: Path, content: str) -> None:
    """Write a projected body and chmod it to 0444.

    Unlinks first so an existing 0444 file does not block the overwrite —
    ``open(O_TRUNC | O_WRONLY)`` honours mode bits even for the owner.
    """
    target.unlink(missing_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(READONLY_MODE)


def write_rw_if_changed(target: Path, content: str) -> bool:
    """Write to ``target`` (mode 0644) only if its content differs. Returns
    ``True`` iff a write happened — useful for telemetry/skip-counts.
    """
    if matches_text(target, content):
        return False
    target.write_text(content, encoding="utf-8")
    target.chmod(RW_MODE)
    return True


def write_rw_body(target: Path, content: str) -> None:
    """Unconditionally write to ``target`` and chmod 0644.

    Used for ``index.md``, which is small and cheaper to rewrite than to
    hash-compare on every sync.
    """
    target.write_text(content, encoding="utf-8")
    target.chmod(RW_MODE)


def meta_body(meta: dict[str, Any]) -> str:
    """Serialize ``meta`` to canonical JSON for on-disk storage."""
    return json.dumps(meta, sort_keys=True, default=str, indent=2) + "\n"


# ====================================================================
# index rendering
# ====================================================================


def updated_at_key(meta: dict[str, Any]) -> str:
    """Sort key for ``index.md`` — ``updated_at``, then ``created_at``, then ``""``."""
    v = meta.get("updated_at") or meta.get("created_at") or ""
    return v.isoformat() if isinstance(v, datetime) else str(v)
