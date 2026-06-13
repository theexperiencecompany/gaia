"""Shared ``_system`` subtree + per-user symlinks (de-duplicated system files).

System-owned files (INDEX.md, the GUIDE.md docs, builtin skill bodies) are
identical for every user. Instead of materializing a copy into each user's
workspace, we keep ONE copy under ``/mnt/jfs/_system`` and point each user's
workspace at it with symlinks — so per user we store a few bytes of pointer, not
the bodies.

Two halves:
  - ``ensure_system_subtree()`` writes the single ``_system`` copy host-side
    (idempotent, hash-gated). Safe to call on every bootstrap.
  - ``link_system_files_into_workspace()`` replaces the per-user copies with
    symlinks into the in-sandbox ``_system`` mount.

In-sandbox, ``mount_juicefs.sh`` bind-mounts ``/_system`` read-only at
``/workspace/.system`` (best-effort). The symlink targets are the absolute
in-sandbox path ``/workspace/.system/<rel>`` — they resolve inside the sandbox
(where ``.system`` is mounted) and are deliberately "broken" on the host (which
has no ``/workspace``). That is fine: the ``read`` tool serves these files from
memory (``system_files``) and never follows the symlink — the symlink exists
only so in-sandbox ``bash`` (``cat``/``ls``/``grep``) can reach the one copy.

No feature flag: ``ensure_system_subtree`` runs every bootstrap and
``link_system_files`` replaces copies with symlinks once the subtree exists.
The copy-writers are symlink-aware (``matches_text`` treats a symlink as
"matches"), so they never clobber the links — and if the shared subtree is ever
unavailable, ``link_system_files`` no-ops and the copy-writers transparently
write per-user copies instead. The in-sandbox ``_system`` mount ships with the
E2B template, so the symlinks resolve there as soon as the template is rebuilt.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from app.agents.workspace.system_files import SystemFile, system_files
from app.services.storage.juicefs import (
    JuiceFSUnavailable,
    _host_base_and_rel,
    _mount_root,
    _require_mount,
)
from shared.py.wide_events import log

# Subdir under the JuiceFS root that holds the single shared copy.
SYSTEM_SUBDIR = "_system"
# In-sandbox mount point for the shared copy (see mount_juicefs.sh).
SANDBOX_SYSTEM_DIR = "/workspace/.system"

_SYSTEM_HASH_MARKER = ".gaia_system.v"


def _library_signature(files: list[SystemFile]) -> str:
    digest = hashlib.sha256()
    for f in sorted(files, key=lambda x: x.rel_path):
        digest.update(f.rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(f.body.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:32]


def _write_system_files(root: Path, files: list[SystemFile]) -> None:
    """Write each manifest file under ``root`` if its body changed."""
    for f in files:
        target = root / f.rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.is_file() and target.read_text(encoding="utf-8") == f.body):
            target.write_text(f.body, encoding="utf-8")


def _prune_orphan_system_files(root: Path, files: list[SystemFile]) -> None:
    """Drop files under ``root`` no longer present in the manifest.

    ``system_files()`` is the authoritative complete set, so stale bodies (e.g.
    a removed builtin skill) must not linger once the signature says it's current.
    """
    expected = {f.rel_path for f in files}
    for existing in root.rglob("*"):
        if not existing.is_file():
            continue
        rel = existing.relative_to(root).as_posix()
        if rel != _SYSTEM_HASH_MARKER and rel not in expected:
            existing.unlink(missing_ok=True)


async def ensure_system_subtree() -> bool:
    """Write the single shared ``_system`` copy host-side. Idempotent + hash-gated.

    Returns True if the subtree is present/written, False if the mount is
    unavailable (native dev). Safe to call on every bootstrap — steady-state
    calls do zero I/O once the signature marker matches.
    """

    def _write() -> bool:
        try:
            root = _require_mount() / SYSTEM_SUBDIR
        except JuiceFSUnavailable:
            return False
        files = system_files()
        signature = _library_signature(files)
        marker = root / _SYSTEM_HASH_MARKER
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == signature:
            return True
        root.mkdir(parents=True, exist_ok=True)
        _write_system_files(root, files)
        _prune_orphan_system_files(root, files)
        marker.write_text(signature, encoding="utf-8")
        return True

    return await asyncio.to_thread(_write)


def system_subtree_available() -> bool:
    """Whether the shared ``_system`` subtree exists on the host mount."""
    try:
        return (_mount_root() / SYSTEM_SUBDIR).is_dir()
    except Exception:
        return False


def _link_target(rel_path: str) -> str:
    # Absolute in-sandbox path under the read-only _system mount.
    return f"{SANDBOX_SYSTEM_DIR}/{rel_path}"


def _link_location(user_id: str, rel_path: str) -> Path:
    """Host path where the per-user symlink for ``rel_path`` must be written.

    Reuses ``_host_base_and_rel`` — the single source of the workspace-rel →
    host-path routing (skill bodies live in the /skills/<uid> overlay subtree,
    everything else under /users/<uid>) — so the symlink placement can never
    disagree with where the read fast-path looks for the same file.
    """
    base, rel = _host_base_and_rel(user_id, rel_path)
    return base / rel


def _place_symlink(link: Path, target: str) -> bool:
    """Create/refresh ``link`` -> ``target`` symlink, replacing any stale copy.

    Returns True if it created or changed the link, False if already correct.
    """
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.readlink() == Path(target):
            return False
        link.unlink()
    elif link.exists():
        # A real per-user copy from the old (pre-symlink) materializer — drop it.
        link.unlink()
    link.symlink_to(target)
    return True


async def link_system_files_into_workspace(user_id: str) -> int:
    """Replace per-user copies of system files with symlinks into ``_system``.

    Returns the number of links created/changed. No-op safe: steady-state calls
    return 0, and if the shared subtree isn't present it returns 0 so the
    copy-writers transparently fall back to per-user copies.
    """
    if not system_subtree_available():
        return 0

    def _link() -> int:
        _require_mount()
        changed = 0
        for f in system_files():
            link = _link_location(user_id, f.rel_path)
            if _place_symlink(link, _link_target(f.rel_path)):
                changed += 1
        return changed

    count = await asyncio.to_thread(_link)
    if count:
        log.info(f"linked {count} system files for {user_id}")
    return count


__all__ = [
    "SANDBOX_SYSTEM_DIR",
    "SYSTEM_SUBDIR",
    "ensure_system_subtree",
    "link_system_files_into_workspace",
    "system_subtree_available",
]
