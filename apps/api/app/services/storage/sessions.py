"""Host-side session workspace helpers.

Everything under `users/{user_id}/sessions/{conversation_id}/` plus the
cross-session `pinned/` dir: creation, artifact listing, single-file
resolution for the HTTP layer, pinning, and the inactivity prune scan.

All filesystem access goes through the JuiceFS host mount primitives in
`juicefs.py`; this module only owns the *session* directory convention.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from app.agents.workspace.paths import (
    SCRATCH_DIRNAME,
    USER_UPLOADED_DIRNAME,
    ARTIFACTS_DIRNAME,
    detect_content_type,
)
from app.services.storage.juicefs import (
    _contained,
    _is_mounted,
    _mount_root,
    _require_mount,
)

SESSION_META_FILENAME = ".meta.json"
SESSION_META_SCHEMA_VERSION = 1

SessionRole = Literal["artifacts", "uploaded"]
_ROLE_DIRNAMES: dict[SessionRole, str] = {
    "artifacts": ARTIFACTS_DIRNAME,
    "uploaded": USER_UPLOADED_DIRNAME,
}


@dataclass
class ArtifactInfo:
    """A single file under a session's `artifacts/` or `user-uploaded/`."""

    path: str  # path relative to the listed root (POSIX, forward slashes)
    size_bytes: int
    mtime: float  # Unix epoch seconds
    content_type: str | None


def _session_base(user_id: str, conv_id: str) -> Path:
    """Host path for a session dir. Raises JuiceFSUnavailable if unmounted."""
    return _require_mount() / "users" / user_id / "sessions" / conv_id


def _list_files(base: Path) -> list[ArtifactInfo]:
    if not base.is_dir():
        return []
    base_resolved = base.resolve()
    out: list[ArtifactInfo] = []
    for entry in sorted(base.rglob("*")):
        if not entry.is_file():
            continue
        st = entry.stat()
        out.append(
            ArtifactInfo(
                path=str(entry.resolve().relative_to(base_resolved)),
                size_bytes=st.st_size,
                mtime=st.st_mtime,
                content_type=detect_content_type(entry.name),
            )
        )
    return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_session_dirs(user_id: str, conv_id: str) -> Path:
    """Create scratch/, user-uploaded/, artifacts/ + .meta.json.

    Idempotent. Raises JuiceFSUnavailable if the host mount is missing.
    """

    def _mk() -> Path:
        base = _session_base(user_id, conv_id)
        for sub in (
            SCRATCH_DIRNAME,
            USER_UPLOADED_DIRNAME,
            ARTIFACTS_DIRNAME,
        ):
            (base / sub).mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        if not meta.exists():
            now = _now_iso()
            meta.write_text(
                json.dumps(
                    {
                        "created_at": now,
                        "last_active": now,
                        "msg_count": 0,
                        "schema_version": SESSION_META_SCHEMA_VERSION,
                    }
                ),
                encoding="utf-8",
            )
        return base

    return await asyncio.to_thread(_mk)


async def delete_session_dir(user_id: str, conv_id: str) -> None:
    """Recursive delete of a session dir. Soft-fail if the mount is missing."""

    def _delete() -> None:
        if not _is_mounted():
            return
        base = _mount_root() / "users" / user_id / "sessions" / conv_id
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)

    await asyncio.to_thread(_delete)


async def touch_session_last_active(user_id: str, conv_id: str) -> None:
    """Bump `.meta.json.last_active`. Used by the ARQ prune task as the
    activity signal. Raises JuiceFSUnavailable if the mount is missing."""

    def _touch() -> None:
        base = _session_base(user_id, conv_id)
        base.mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        now = _now_iso()
        data: dict[str, object] = {}
        if meta.exists():
            try:
                loaded = json.loads(meta.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = loaded
            except (ValueError, OSError):
                data = {}
        data.setdefault("created_at", now)
        data.setdefault("msg_count", 0)
        data["last_active"] = now
        data["schema_version"] = SESSION_META_SCHEMA_VERSION
        meta.write_text(json.dumps(data), encoding="utf-8")

    await asyncio.to_thread(_touch)


async def chmod_path(host_path: Path, mode: int) -> None:
    """Wrap os.chmod (used to make uploads read-only at mode=0o444)."""
    await asyncio.to_thread(os.chmod, host_path, mode)


async def list_artifacts(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Host-side recursive scan of a session's `artifacts/`. Zero R2 ops
    (PG metadata only). Backs the GET endpoint + defense-in-depth recovery."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(_session_base(user_id, conv_id) / ARTIFACTS_DIRNAME)

    return await asyncio.to_thread(_go)


async def list_user_uploaded(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Same shape as list_artifacts, for the `user-uploaded/` dir."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(_session_base(user_id, conv_id) / USER_UPLOADED_DIRNAME)

    return await asyncio.to_thread(_go)


async def stat_artifact(
    user_id: str, conv_id: str, rel_path: str
) -> ArtifactInfo | None:
    """Single-file stat under `artifacts/`. Used by the watcher to enrich
    an event. Returns None if the path is not a file."""

    def _stat() -> ArtifactInfo | None:
        base = _session_base(user_id, conv_id) / ARTIFACTS_DIRNAME
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

    return await asyncio.to_thread(_stat)


async def resolve_session_path(
    user_id: str, conv_id: str, role: SessionRole, rel_path: str
) -> Path:
    """Resolve a request path under a session's visible/uploaded root.

    Raises JuiceFSUnavailable if the mount is missing, ValueError if
    `rel_path` escapes the root. Existence is the caller's concern (so it
    can distinguish 404 from 400).
    """

    def _resolve() -> Path:
        base = _session_base(user_id, conv_id) / _ROLE_DIRNAMES[role]
        return _contained(base, rel_path)

    return await asyncio.to_thread(_resolve)


async def pin_session_artifact(
    user_id: str, conv_id: str, rel_path: str, target_name: str | None = None
) -> str:
    """Copy a `artifacts/` artifact into the user's cross-session
    `pinned/` dir. Returns the `/workspace/...` path of the pinned copy."""

    def _pin() -> str:
        root = _require_mount()
        src = _contained(
            root / "users" / user_id / "sessions" / conv_id / ARTIFACTS_DIRNAME,
            rel_path,
        )
        if not src.is_file():
            raise FileNotFoundError(rel_path)
        pinned_root = root / "users" / user_id / "pinned"
        name = target_name or src.name
        dest = _contained(pinned_root, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return f"/workspace/pinned/{dest.relative_to(pinned_root.resolve())}"

    return await asyncio.to_thread(_pin)


async def list_session_ids(user_id: str) -> list[str]:
    """Conversation ids that have an on-disk session dir for this user.

    Zero R2 ops (PG-only readdir). Soft-returns [] if the mount is missing.
    """

    def _scan() -> list[str]:
        if not _is_mounted():
            return []
        sessions_dir = _mount_root() / "users" / user_id / "sessions"
        if not sessions_dir.is_dir():
            return []
        return sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())

    return await asyncio.to_thread(_scan)


def _parse_last_active(meta: Path) -> datetime | None:
    """Read `.meta.json.last_active` as an aware datetime, or None."""
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    raw = data.get("last_active") if isinstance(data, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def list_stale_sessions(
    cutoff_days: int, limit: int | None = None
) -> list[tuple[str, str]]:
    """Return (user_id, conv_id) for sessions inactive past `cutoff_days`.

    Conservative: a session whose `last_active` cannot be determined is
    skipped, never pruned. Soft-returns [] if the mount is missing.
    """

    def _scan() -> list[tuple[str, str]]:
        if not _is_mounted():
            return []
        users_root = _mount_root() / "users"
        if not users_root.is_dir():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
        stale: list[tuple[str, str]] = []
        for user_dir in sorted(users_root.iterdir()):
            sessions_dir = user_dir / "sessions"
            if not sessions_dir.is_dir():
                continue
            for sess in sorted(sessions_dir.iterdir()):
                if not sess.is_dir():
                    continue
                last_active = _parse_last_active(sess / SESSION_META_FILENAME)
                if last_active is None or last_active >= cutoff:
                    continue
                stale.append((user_dir.name, sess.name))
                if limit is not None and len(stale) >= limit:
                    return stale
        return stale

    return await asyncio.to_thread(_scan)
