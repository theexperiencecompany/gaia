"""Host-side JuiceFS mount primitives + user/skill helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
import shutil

from app.config.settings import settings
from app.services.storage.metrics import FsOps, add_fs_bytes, fs_timer
from shared.py.wide_events import log


class JuiceFSUnavailable(Exception):
    """Raised when the host-side JuiceFS mount is not available."""


SAFE_PATH_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_SAFE_ID_RE = re.compile(SAFE_PATH_ID_PATTERN)


def ensure_safe_path_id(value: str, *, label: str = "id") -> None:
    """Raise ``ValueError`` if ``value`` could escape a single path component."""
    if not isinstance(value, str) or not _SAFE_ID_RE.match(value):
        raise ValueError(f"unsafe {label}: must match {SAFE_PATH_ID_PATTERN}")


def _mount_root() -> Path:
    return Path(settings.JUICEFS_HOST_MOUNT_PATH)


def _is_mounted() -> bool:
    root = _mount_root()
    return root.exists() and root.is_dir()


def _require_mount() -> Path:
    root = _mount_root()
    if not _is_mounted():
        raise JuiceFSUnavailable(
            f"JuiceFS mount not available at {root}. "
            "Set JUICEFS_HOST_MOUNT_PATH and mount the sidecar."
        )
    return root


def _contained(base: Path, relative_path: str, *, root_label: str = "root") -> Path:
    """Resolve ``relative_path`` under ``base``; raise ``ValueError`` if it escapes."""
    target = (base / relative_path).resolve()
    base_resolved = base.resolve()
    try:
        target.relative_to(base_resolved)
    except ValueError as e:
        raise ValueError(f"path {relative_path} escapes the {root_label}") from e
    return target


def user_workspace_path(user_id: str) -> Path:
    """Absolute path on the host for a user's workspace root."""
    return _mount_root() / "users" / user_id


def user_skills_path(user_id: str) -> Path:
    """Absolute path on the host for a user's skills directory."""
    return _mount_root() / "skills" / user_id


def session_root(user_id: str, conversation_id: str) -> Path:
    """Host path for a conversation's session directory."""
    ensure_safe_path_id(conversation_id, label="conversation_id")
    return _mount_root() / "users" / user_id / "sessions" / conversation_id


def sandbox_session_path(conversation_id: str) -> str:
    """Return the ``/workspace/...`` session path visible inside the sandbox."""
    return f"/workspace/sessions/{conversation_id}"


async def ensure_user_workspace(user_id: str) -> Path:
    """Idempotently create the user's workspace tree on JuiceFS."""

    def _mkdir() -> Path:
        root = _require_mount()
        path = root / "users" / user_id
        gaia_dir = path / ".gaia"
        path.mkdir(parents=True, exist_ok=True)
        gaia_dir.mkdir(parents=True, exist_ok=True)
        return path

    return await asyncio.to_thread(_mkdir)


async def ensure_user_skills_dir(user_id: str) -> Path:
    """Create the user's `/skills/{user_id}/` directory tree on JuiceFS."""

    def _mkdir() -> Path:
        root = _require_mount()
        path = root / "skills" / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    return await asyncio.to_thread(_mkdir)


def _content_size(content: bytes | str) -> int:
    return len(content) if isinstance(content, bytes) else len(content.encode("utf-8"))


async def write_skill_file(
    user_id: str, skill_name: str, relative_path: str, content: bytes | str
) -> Path:
    """Write a skill file under the user's skill root. ``relative_path`` cannot escape it."""

    def _write() -> Path:
        skills_root = _require_mount() / "skills" / user_id / skill_name
        target = _contained(skills_root, relative_path, root_label="skill root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    async with fs_timer(FsOps.WRITE_SKILL_FILE):
        path = await asyncio.to_thread(_write)
    add_fs_bytes(FsOps.WRITE_SKILL_FILE, _content_size(content))
    return path


async def write_session_file(
    user_id: str,
    conversation_id: str,
    relative_path: str,
    content: bytes | str,
) -> tuple[Path, str]:
    """Write a session-scoped file. Returns ``(host_path, sandbox_path)``."""
    ensure_safe_path_id(conversation_id, label="conversation_id")

    def _write() -> tuple[Path, str]:
        base = _require_mount() / "users" / user_id / "sessions" / conversation_id
        target = _contained(base, relative_path, root_label="session root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        sandbox_view = f"/workspace/sessions/{conversation_id}/{relative_path}"
        return target, sandbox_view

    async with fs_timer(FsOps.WRITE_SESSION_FILE):
        result = await asyncio.to_thread(_write)
    add_fs_bytes(FsOps.WRITE_SESSION_FILE, _content_size(content))
    return result


async def delete_user_workspace(user_id: str) -> None:
    """Delete the user's workspace and skills trees (account deletion / GDPR)."""

    def _delete() -> None:
        if not _is_mounted():
            log.warning(
                "delete_user_workspace called but JuiceFS mount missing",
                user_id=user_id,
            )
            return
        for path in (user_workspace_path(user_id), user_skills_path(user_id)):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    await asyncio.to_thread(_delete)


async def delete_user_skill(user_id: str, skill_name: str) -> None:
    """Remove a single installed skill from disk."""

    def _delete() -> None:
        if not _is_mounted():
            return
        path = user_skills_path(user_id) / skill_name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    await asyncio.to_thread(_delete)
