"""Artifact + user-uploaded listing, stat, path resolution, pinning.

Covers the read paths driving ``GET /sessions/<id>/artifacts`` and the
artifact watcher's resync. Path resolution goes through ``_contained`` from
the juicefs primitives so a malicious ``rel_path`` cannot escape the
session root.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import shutil
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
    path: str
    size_bytes: int
    mtime: float
    content_type: str | None


def _list_files(base: Path) -> list[ArtifactInfo]:
    """List regular files under ``base``.

    Symlinks and per-entry stat errors are silently skipped so a malicious
    or racing entry under the agent-writable tree can't 500 the whole listing
    or be used to probe host paths.
    """
    if not base.is_dir():
        return []
    base_resolved = base.resolve()
    out: list[ArtifactInfo] = []
    for entry in sorted(base.rglob("*")):
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            st = entry.stat()
            rel = entry.resolve().relative_to(base_resolved)
        except (OSError, ValueError):
            continue
        out.append(
            ArtifactInfo(
                path=str(rel),
                size_bytes=st.st_size,
                mtime=st.st_mtime,
                content_type=detect_content_type(entry.name),
            )
        )
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
        target = _contained(base, rel_path)
        if not target.is_file():
            return None
        st = target.stat()
        return ArtifactInfo(
            path=str(target.relative_to(base.resolve())),
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
