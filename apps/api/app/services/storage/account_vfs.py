"""Account-center VFS materialization for ``/workspace/account/``.

Projects the user's account state (subscription, usage, settings, linked
platforms) as read-only JSON files. Every file is written 0444 and only when
its content actually changed (``matches_text``), so steady-state syncs do zero
I/O — same contract as the integrations catalog materializer.

The GUIDE.md docs under ``account/`` are NOT written here: they are static
system files (``system_files._STATIC_DOCS``), served by the read tool's memory
fast-path and symlinked from the shared ``_system`` subtree.

Layout::

    account/
        subscription.json  usage.json  notifications.json
        preferences.json   custom-instructions.json
        voices/catalog.json          voices/selected.json
        linked-accounts/<platform>.json
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from app.constants.account import ACCOUNT_DIR
from app.services.storage._vfs_common import matches_text, write_readonly_body


class AccountFileProjection(TypedDict):
    """One projected file: workspace-relative path + serialized JSON body."""

    id: str
    path: str
    body: str


def materialize_account_files(
    user_root: Path,
    files: list[AccountFileProjection],
    preserve_paths: set[str] | None = None,
) -> int:
    """Project ``files`` under ``<user_root>/account/``, pruning stale views.

    ``preserve_paths`` are workspace-relative paths whose source could not be
    read this pass (provider outage): their previous on-disk projection is kept
    instead of being pruned as stale — a stale view beats a missing one, and
    the failure is logged by the caller.
    """
    account_root = user_root / ACCOUNT_DIR
    expected: set[str] = set()
    written = 0
    for doc in files:
        rel = doc["path"]
        expected.add(rel)
        target = user_root / rel
        if matches_text(target, doc["body"]):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        write_readonly_body(target, doc["body"])
        written += 1

    _prune_stale_json(account_root, expected, preserve_paths or set())
    return written


def _prune_stale_json(account_root: Path, expected: set[str], preserve: set[str]) -> None:
    """Remove *.json projections under ``account/`` that left the manifest.

    Only data files are pruned — markdown guides belong to the system-file
    linker and are never touched here. Platform files are always re-projected
    (connected or not), so this fires only when the manifest itself shrinks.
    Paths in ``preserve`` (a source that failed this pass) survive the prune.
    """
    if not account_root.is_dir():
        return
    prefix = f"{ACCOUNT_DIR}/"
    for existing in account_root.rglob("*.json"):
        rel = existing.relative_to(account_root).as_posix()
        full = f"{prefix}{rel}"
        if full in expected or full in preserve:
            continue
        existing.chmod(0o644)
        existing.unlink(missing_ok=True)


__all__ = [
    "AccountFileProjection",
    "materialize_account_files",
]
