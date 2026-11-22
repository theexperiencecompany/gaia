"""Shared building blocks for VFS materializers under /workspace/.

The projected areas (memory, account, integrations) write MongoDB state into
JuiceFS as hash-gated files; the slug naming, marker read/write, the
shutil.rmtree chmod-and-retry hook and the "only rewrite if changed" guard live
here. Keep this module dependency-free (no app imports) so it stays cheap to
load and safe to reference from anywhere in app.services.storage.
"""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
import re
import shutil
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from _typeshed import ExcInfo

# --- Filenames every materializer agrees on ---------------------------------

INDEX_FILENAME = "index.md"
GUIDE_FILENAME = "GUIDE.md"

# --- File modes ---------------------------------------------------------
# Read-only bodies make a raw `Edit` fail loudly instead of desyncing the
# projection; GUIDE/index are writable since we rewrite them each sync.

READONLY_MODE = 0o444
RW_MODE = 0o644
RW_DIR_MODE = 0o755

# --- Slug policy ----------------------------------------------------------

SLUG_MAX_LEN = 40
_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")
_UNTITLED = "untitled"


class VfsProjection(TypedDict):
    """What every VFS area's projection carries: the stable id its signature is keyed by."""

    id: str


# ====================================================================
# naming
# ====================================================================


def slugify(title: str | None) -> str:
    """Lowercase, alphanumeric + dashes, ≤ 40 chars; "untitled" on empty."""
    if not title:
        return _UNTITLED
    cleaned = _SLUG_INVALID_RE.sub("-", title.lower().strip()).strip("-")
    if not cleaned:
        return _UNTITLED
    return cleaned[:SLUG_MAX_LEN].rstrip("-") or _UNTITLED


# ====================================================================
# hashing
# ====================================================================


def catalog_signature(per_doc: dict[str, str]) -> str:
    """Stable hash of sorted id:sig pairs — gates the full sync."""
    joined = "\n".join(f"{tid}:{sig}" for tid, sig in sorted(per_doc.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# ====================================================================
# markers
# ====================================================================


def read_marker(path: Path) -> str | None:
    """Return marker contents (stripped), or None if missing/unreadable."""
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


# ====================================================================
# filesystem
# ====================================================================


def _force_remove(func: Callable[[str], object], path: str, _exc_info: ExcInfo) -> None:
    """shutil.rmtree onerror hook: chmod target writable then retry.

    POSIX requires write permission on the file itself (not just the
    directory) to unlink. Our projected bodies are 0444, so naïve
    rmtree would fail mid-tree.
    """
    try:
        Path(path).chmod(RW_MODE)
        func(path)
    except OSError:
        pass


def remove_tree(path: Path) -> None:
    """Recursively remove path; tolerate 0444 children and 0555 folders."""
    if path.exists() and path.is_dir():
        path.chmod(RW_DIR_MODE)
        # rglob(None) yields every directory recursively and the body only
        # chmods `child.is_dir()` entries, so it is equivalent to "*" here
        # (files are handled by _force_remove).
        for child in path.rglob("*"):  # pragma: no mutate — see note above
            if child.is_dir():
                child.chmod(RW_DIR_MODE)
        shutil.rmtree(path, onerror=_force_remove)


def matches_text(path: Path, expected: str) -> bool:
    """Cheap "do we need to rewrite this file?" check.

    Treats decode errors as "doesn't match" so corrupted bytes get
    rewritten rather than silently kept. A symlink is treated as "matches"
    so the de-duplicated system-file symlinks (which point at the read-only
    _system mount and don't resolve host-side) are never clobbered.
    """
    if path.is_symlink():
        return True
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def write_readonly_body(target: Path, content: str) -> None:
    """Write a projected body and chmod it to 0444.

    Unlinks first so an existing 0444 file does not block the overwrite —
    open(O_TRUNC | O_WRONLY) honours mode bits even for the owner.
    """
    target.unlink(missing_ok=True)
    target.write_text(content, encoding="utf-8")
    target.chmod(READONLY_MODE)


def write_rw_if_changed(target: Path, content: str) -> bool:
    """Write to target (mode 0644) only if content differs; return True if it wrote."""
    if matches_text(target, content):
        return False
    target.write_text(content, encoding="utf-8")
    target.chmod(RW_MODE)
    return True
