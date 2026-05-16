"""Host-side JuiceFS mount primitives + user/skill helpers.

The API container runs a JuiceFS sidecar mount at `settings.JUICEFS_HOST_MOUNT_PATH`
(default `/mnt/jfs`). This module reads and writes user workspace + skill files
against that mount on behalf of the API process — the agent sandbox accesses
the same files via its own JuiceFS mount inside the E2B VM.

Layout under the mount:

    /mnt/jfs/users/{user_id}/        # bind-mounted to /workspace inside sandbox
    /mnt/jfs/skills/{user_id}/{name}/ # bind-mounted read-only to /workspace/skills

Session-scoped helpers live in `sessions.py`; this module owns only the mount
and the user/skill trees. In dev mode the mount typically isn't present — all
helpers raise `JuiceFSUnavailable`, which callers treat as a soft-fail.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from shared.py.wide_events import log
from app.config.settings import settings


class JuiceFSUnavailable(Exception):
    """Raised when the host-side JuiceFS mount is not available."""


def _mount_root() -> Path:
    return Path(settings.JUICEFS_HOST_MOUNT_PATH)


def _is_mounted() -> bool:
    root = _mount_root()
    if not root.exists():
        return False
    # We don't insist on a real FUSE mount in dev — if the directory exists
    # and is writable, treat it as a usable workspace root.
    return root.is_dir()


def _require_mount() -> Path:
    root = _mount_root()
    if not _is_mounted():
        raise JuiceFSUnavailable(
            f"JuiceFS mount not available at {root}. "
            "Set JUICEFS_HOST_MOUNT_PATH and mount the sidecar."
        )
    return root


def _contained(base: Path, relative_path: str, *, root_label: str = "root") -> Path:
    """Resolve `relative_path` under `base`, refusing to escape it.

    Single source of the path-containment check used by every host-side
    writer/reader. `root_label` only shapes the error message.
    """
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
    return _mount_root() / "users" / user_id / "sessions" / conversation_id


def sandbox_session_path(conversation_id: str) -> str:
    """The `/workspace/...` path the agent uses to read session files.

    `/workspace` inside the sandbox is bind-mounted from
    `/mnt/jfs/users/{user_id}/`, so the agent never sees the user prefix.
    """
    return f"/workspace/sessions/{conversation_id}"


async def ensure_user_workspace(user_id: str) -> Path:
    """Create the user's `/users/{user_id}/` directory tree on JuiceFS.

    Idempotent. Raises `JuiceFSUnavailable` if the host mount is missing.
    """

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
    """Write a single skill file (SKILL.md or script) into the user's skill dir.

    ``relative_path`` is interpreted relative to the skill's root and must
    not escape it. Returns the absolute on-disk path of the written file.
    """
    # Lazy imports keep `storage.metrics` from creating an import cycle with
    # this module — it sits "below" the wider storage package in the graph.
    from app.services.storage.metrics import FS_OPS, add_fs_bytes, fs_timer

    def _write() -> Path:
        skills_root = _require_mount() / "skills" / user_id / skill_name
        target = _contained(skills_root, relative_path, root_label="skill root")
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    async with fs_timer(FS_OPS.WRITE_SKILL_FILE):
        path = await asyncio.to_thread(_write)
    add_fs_bytes(FS_OPS.WRITE_SKILL_FILE, _content_size(content))
    return path


async def write_session_file(
    user_id: str,
    conversation_id: str,
    relative_path: str,
    content: bytes | str,
) -> tuple[Path, str]:
    """Write a session-scoped file under ``users/{user_id}/sessions/{conv}/``.

    Returns ``(host_path, sandbox_path)`` where ``sandbox_path`` is the
    ``/workspace/...`` path the agent can pass to the ``read`` tool.
    """
    from app.services.storage.metrics import FS_OPS, add_fs_bytes, fs_timer

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

    async with fs_timer(FS_OPS.WRITE_SESSION_FILE):
        result = await asyncio.to_thread(_write)
    add_fs_bytes(FS_OPS.WRITE_SESSION_FILE, _content_size(content))
    return result


async def delete_user_workspace(user_id: str) -> None:
    """Delete the user's workspace and skills directories. For GDPR / account
    deletion only."""

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
