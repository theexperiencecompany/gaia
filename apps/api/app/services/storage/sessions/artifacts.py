"""Artifact + user-uploaded listing, stat, path resolution, pinning.

Covers the read paths driving ``GET /sessions/<id>/artifacts`` and the
artifact watcher's resync. Path resolution goes through ``_contained`` from
the juicefs primitives so a malicious ``rel_path`` cannot escape the
session root.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat as stat_module
from typing import Literal

from app.agents.workspace.paths import (
    ARTIFACTS_DIRNAME,
    USER_UPLOADED_DIRNAME,
    detect_content_type,
)
from app.services.storage.juicefs import _contained, _require_mount
from app.services.storage.metrics import FsOps, fs_timer
from app.services.storage.sessions._paths import session_base

SessionRole = Literal["artifacts", "uploaded"]
_ROLE_DIRNAMES: dict[SessionRole, str] = {
    "artifacts": ARTIFACTS_DIRNAME,
    "uploaded": USER_UPLOADED_DIRNAME,
}


@dataclass(slots=True)
class ArtifactInfo:
    """A single listed artifact/upload: relative path, size, mtime, MIME type."""

    path: str
    size_bytes: int
    mtime: float
    content_type: str | None


def _list_files(base: Path) -> list[ArtifactInfo]:
    """List regular files under ``base``.

    Walks with ``os.scandir`` instead of ``Path.rglob``: every path here lives on
    JuiceFS, where each ``stat``/``lstat``/``resolve`` is a metadata-DB round-trip.
    A ``DirEntry`` carries the directory's ``d_type`` and caches its own ``stat``,
    so ``is_symlink``/``is_dir``/``is_file``/``stat`` cost at most one op per entry
    (often zero — served from ``d_type``). The old ``rglob`` path paid ~3+depth ops
    per file: a separate ``lstat`` + ``is_file`` stat + a redundant second ``stat``
    + a full ``resolve()`` that walks every path component.

    Symlinks are skipped and never followed into directories, so the walk can't be
    redirected outside ``base`` — the same escape protection the old per-file
    ``resolve()`` gave, without its cost. Per-entry errors are skipped so a racing
    or hostile entry under the agent-writable tree can't 500 the whole listing.
    """
    if not base.is_dir():
        return []
    out: list[ArtifactInfo] = []
    stack = [str(base)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat()
                    except OSError:
                        continue
                    out.append(
                        ArtifactInfo(
                            path=os.path.relpath(entry.path, base),
                            size_bytes=st.st_size,
                            mtime=st.st_mtime,
                            content_type=detect_content_type(entry.name),
                        )
                    )
        except OSError:
            continue
    out.sort(key=lambda a: a.path)
    return out


async def list_artifacts(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Recursive scan of a session's ``artifacts/``."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(session_base(user_id, conv_id) / ARTIFACTS_DIRNAME)

    async with fs_timer(FsOps.LIST_ARTIFACTS):
        return await asyncio.to_thread(_go)


async def list_user_uploaded(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Recursive scan of a session's ``user-uploaded/``."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(session_base(user_id, conv_id) / USER_UPLOADED_DIRNAME)

    async with fs_timer(FsOps.LIST_USER_UPLOADED):
        return await asyncio.to_thread(_go)


async def stat_artifact(user_id: str, conv_id: str, rel_path: str) -> ArtifactInfo | None:
    """Stat a single file under ``artifacts/``. Returns ``None`` if not a file."""

    def _stat() -> ArtifactInfo | None:
        base = session_base(user_id, conv_id) / ARTIFACTS_DIRNAME
        # `_contained` already resolves + containment-checks the path (one walk).
        # Then a SINGLE stat — the old `is_file()` + `.stat()` pair stat'd the
        # same inode twice, doubling the JuiceFS metadata round-trips on the
        # watcher's hottest per-event path. Reject non-regular files via the
        # mode bits from that one stat.
        target = _contained(base, rel_path)
        try:
            st = target.stat()
        except OSError:
            return None
        if not stat_module.S_ISREG(st.st_mode):
            return None
        # Anchor the relative path on the RESOLVED base: `_contained` resolves
        # `target` (follows symlinks), so anchoring on an unresolved base would
        # emit a `../`-laden path if the mount root is itself a symlink.
        return ArtifactInfo(
            path=os.path.relpath(target, base.resolve()),
            size_bytes=st.st_size,
            mtime=st.st_mtime,
            content_type=detect_content_type(target.name),
        )

    async with fs_timer(FsOps.STAT_ARTIFACT):
        return await asyncio.to_thread(_stat)


async def resolve_session_path(
    user_id: str, conv_id: str, role: SessionRole, rel_path: str
) -> Path:
    """Resolve a request path under a session's artifacts/ or user-uploaded/ root.

    Raises ``JuiceFSUnavailable`` if the mount is missing, ``ValueError`` if
    ``rel_path`` escapes the root. Existence is the caller's concern (so it
    can distinguish 404 from 400).
    """

    def _resolve() -> Path:
        base = session_base(user_id, conv_id) / _ROLE_DIRNAMES[role]
        return _contained(base, rel_path)

    async with fs_timer(FsOps.RESOLVE_SESSION_PATH, role=role):
        return await asyncio.to_thread(_resolve)


async def pin_session_artifact(
    user_id: str, conv_id: str, rel_path: str, target_name: str | None = None
) -> str:
    """Copy an artifact into the user's cross-session ``pinned/`` dir.

    Returns the ``/workspace/...`` path of the pinned copy.
    """

    def _pin() -> str:
        root = _require_mount()
        src = _contained(session_base(user_id, conv_id) / ARTIFACTS_DIRNAME, rel_path)
        if not src.is_file():
            raise FileNotFoundError(rel_path)
        pinned_root = root / "users" / user_id / "pinned"
        dest = _contained(pinned_root, target_name or src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return f"/workspace/pinned/{dest.relative_to(pinned_root.resolve())}"

    async with fs_timer(FsOps.PIN_ARTIFACT):
        return await asyncio.to_thread(_pin)
