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


def _host_base_and_rel(user_id: str, workspace_rel_path: str) -> tuple[Path, str]:
    """Map a ``/workspace``-relative path to its host ``(base_root, rel_under_base)``.

    ``/workspace/skills`` is a SEPARATE JuiceFS subtree — the read-only overlay of
    ``/skills/<uid>`` (see ``mount_juicefs.sh``) — while everything else lives under
    ``/users/<uid>``. Built-in skill bodies are served from process memory
    (``system_files``), so the only host reads under ``skills/`` are user-installed
    skills, which live in the ``/skills/<uid>`` subtree. Routing them here keeps the
    host read consistent with what the sandbox sees at ``/workspace/skills``.
    """
    mount = _require_mount()
    if workspace_rel_path == "skills" or workspace_rel_path.startswith("skills/"):
        rel = workspace_rel_path[len("skills/") :] if workspace_rel_path != "skills" else ""
        return mount / "skills" / user_id, rel
    return mount / "users" / user_id, workspace_rel_path


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


def page_bounds(offset: int, limit: int) -> tuple[int, int]:
    """1-indexed inclusive ``(start, end)`` line range for a paged read.

    ``offset`` is the 1-indexed start line (0 and 1 both mean line 1); ``limit``
    is clamped to at least one line. Shared by every read path (memory, JuiceFS,
    sandbox) so their slices stay byte-for-byte consistent.
    """
    start = max(1, offset) if offset > 0 else 1
    end = start + max(1, limit) - 1
    return start, end


async def read_user_file(
    user_id: str,
    workspace_rel_path: str,
    *,
    offset: int = 0,
    limit: int = 2000,
) -> tuple[list[str], int]:
    """Read a workspace file straight from the host JuiceFS mount — no sandbox.

    ``/workspace`` inside the sandbox is a bind-mount of ``/mnt/jfs/users/<id>``,
    so the same bytes are readable host-side without paying an E2B spin-up.
    ``workspace_rel_path`` is relative to ``/workspace`` (e.g.
    ``sessions/<conv>/scratch/out.txt``); it is resolved under the user's OWN
    root via ``_contained`` and cannot escape it — this defeats ``..`` traversal
    and symlink escape (``.resolve()`` + ``relative_to``), so a model-supplied
    path can only ever reach this user's files.

    Returns ``(lines, total_line_count)`` where ``lines`` is the 1-indexed slice
    ``[start, start + limit)`` with trailing newlines stripped. Raises
    ``FileNotFoundError`` if the target is missing or not a regular file, and
    ``JuiceFSUnavailable`` if the host mount is absent (e.g. native dev).
    """
    start, end = page_bounds(offset, limit)

    def _read() -> tuple[list[str], int]:
        base, rel = _host_base_and_rel(user_id, workspace_rel_path)
        target = _contained(base, rel, root_label="workspace root")
        if not target.is_file():
            raise FileNotFoundError(workspace_rel_path)
        sliced: list[str] = []
        total = 0
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle, start=1):
                total = idx
                if start <= idx <= end:
                    sliced.append(line.rstrip("\n"))
        return sliced, total

    return await asyncio.to_thread(_read)


async def user_owns_regular_file(user_id: str, workspace_rel_path: str) -> bool:
    """True iff the user has a real (non-symlink) regular file at this path.

    The ``read`` tool serves system-owned files (INDEX.md, the GUIDE.md docs,
    builtin skill bodies) from process memory. This lets it skip that fast-path
    when the user has created their OWN file at the same workspace path, so a
    user file is never shadowed by the in-memory system copy. A symlink (the
    de-duplicated system projection) does not count as an override. Never raises;
    returns ``False`` when the mount is absent (native dev) so the memory
    fast-path still applies there.
    """
    if not _is_mounted():
        return False

    def _check() -> bool:
        try:
            base, rel = _host_base_and_rel(user_id, workspace_rel_path)
            target = base / rel
            return target.is_file() and not target.is_symlink()
        except Exception:
            return False

    return await asyncio.to_thread(_check)


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
