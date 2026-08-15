"""/workspace/memory materializer — pure filesystem + rendering, no DB.

Postgres is the source of truth. The on-disk tree is a hash-gated read-only
projection (mode 0444 like the gaia-tasks bodies): the agent reads it with
``ls``/``cat``/``grep``; mutations go through the memory tools → engine →
re-projection.

Layout under ``<user_root>/memory/``::

    GUIDE.md                      hand-authored, mode 0644
    user.md  memory.md  agenda.md  people.md  insights.md     mode 0444
    journal/YYYY-MM-DD.md         last 30 days, mode 0444
    facts/<category_path>.md      one file per leaf folder, mode 0444

The Postgres glue lives in :mod:`app.services.memory_fs`.
"""

from __future__ import annotations

from datetime import date as date_type
import hashlib
from pathlib import Path
from typing import TypedDict

from app.services.storage._vfs_common import (
    GUIDE_FILENAME,
    matches_text,
    write_readonly_body,
    write_rw_if_changed,
)

# --- Path constants ---------------------------------------------------------

MEMORY_DIRNAME = "memory"
MEMORY_MARKER = ".gaia/memory.v"
JOURNAL_DIRNAME = "journal"
FACTS_DIRNAME = "facts"


class MemoryFileProjection(TypedDict):
    """One projected file: stable id, path under ``memory/``, full content."""

    id: str
    path: str
    content: str


# ====================================================================
# signatures + marker
# ====================================================================


def per_doc_signature(doc: MemoryFileProjection) -> str:
    """sha256 of path + content — feeds the catalog signature gate."""
    digest = hashlib.sha256()
    digest.update(doc["path"].encode("utf-8"))
    digest.update(b"\x00")
    digest.update(doc["content"].encode("utf-8"))
    return digest.hexdigest()


def memory_marker_path(user_root: Path) -> Path:
    return user_root / MEMORY_MARKER


# ====================================================================
# rendering (pure helpers the Postgres glue feeds with primitives)
# ====================================================================


def render_journal_page(date: date_type, entries: list[dict[str, str]], summary: str | None) -> str:
    """One journal day: timestamped lines plus the rollover summary when set."""
    lines = [f"# {date.isoformat()}", ""]
    lines.extend(f"- {entry.get('time', '')} {entry.get('text', '')}".rstrip() for entry in entries)
    if summary:
        lines.extend(["", "## Summary", "", summary])
    return "\n".join(lines) + "\n"


def render_facts_page(category_path: str, facts: list[tuple[str, str, float]]) -> str:
    """One category leaf: latest facts as bullets with id/importance markers.

    ``facts`` is ``(memory_id, content, importance)`` tuples, newest first.
    """
    lines = [f"# {category_path}", ""]
    lines.extend(
        f"- {content}  <!-- id:{memory_id} importance:{importance:.1f} -->"
        for memory_id, content, importance in facts
    )
    return "\n".join(lines) + "\n"


# ====================================================================
# materialize
# ====================================================================


def materialize_memory(user_root: Path, docs: list[MemoryFileProjection], guide_md: str) -> int:
    """Idempotently project ``docs`` into ``<user_root>/memory/``.

    Returns the number of file bodies rewritten (excluding GUIDE.md). Files
    and journal days that disappeared from the projection are removed, and
    emptied directories pruned.
    """
    memory_root = user_root / MEMORY_DIRNAME
    memory_root.mkdir(parents=True, exist_ok=True)
    write_rw_if_changed(memory_root / GUIDE_FILENAME, guide_md)

    written = 0
    expected = {GUIDE_FILENAME}
    for doc in docs:
        expected.add(doc["path"])
        target = memory_root / doc["path"]
        if matches_text(target, doc["content"]):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        write_readonly_body(target, doc["content"])
        written += 1

    _remove_stale_paths(memory_root, expected)
    return written


def _remove_stale_paths(memory_root: Path, expected: set[str]) -> None:
    """Drop files no longer projected and prune directories they emptied.

    Reverse-sorted ``rglob`` visits children before their parent directory,
    so an emptied folder is removable in the same pass. Symlinks (the
    de-duplicated system GUIDE.md) count as files and are kept via
    ``expected``.
    """
    for path in sorted(memory_root.rglob("*"), reverse=True):
        if path.is_dir() and not path.is_symlink():
            if not any(path.iterdir()):
                path.rmdir()
        elif path.relative_to(memory_root).as_posix() not in expected:
            path.unlink(missing_ok=True)


__all__ = [
    "FACTS_DIRNAME",
    "JOURNAL_DIRNAME",
    "MEMORY_DIRNAME",
    "MEMORY_MARKER",
    "MemoryFileProjection",
    "materialize_memory",
    "memory_marker_path",
    "per_doc_signature",
    "render_facts_page",
    "render_journal_page",
]
