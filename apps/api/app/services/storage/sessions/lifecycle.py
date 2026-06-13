"""Session lifecycle — dir creation, user provisioning, deletion, idle scan.

``ensure_session_dirs`` creates a conversation's session dirs (at conversation
creation). ``provision_user_workspace`` / ``materialize_user_integrations`` do
the user-level materialization, driven by registration, integration changes,
and startup — not by the chat turn. The rest is admin (idle prune, hard delete,
stale scan) reached from workers and the ``/sessions`` admin endpoints.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil

from app.agents.workspace.paths import (
    ARTIFACTS_DIRNAME,
    SCRATCH_DIRNAME,
    USER_UPLOADED_DIRNAME,
)
from app.agents.workspace.skill_loader import library_hash
from app.services.storage.juicefs import _is_mounted, _mount_root, session_root
from app.services.storage.metrics import FsOps, fs_timer
from app.services.storage.sessions._paths import session_base, user_root
from app.services.storage.sessions.meta import (
    SESSION_META_FILENAME,
    now_iso,
    parse_last_active,
    read_session_meta,
    write_session_meta,
)
from app.services.storage.sessions.skills import (
    materialize_instructions,
    materialize_skills,
    read_skills_marker,
    read_text_or_none,
    write_skills_marker,
)


def _ensure_session_subdirs(base: Path) -> None:
    """Create the scratch/, user-uploaded/, artifacts/ trio under a session root."""
    for sub in (SCRATCH_DIRNAME, USER_UPLOADED_DIRNAME, ARTIFACTS_DIRNAME):
        (base / sub).mkdir(parents=True, exist_ok=True)


def _materialize_if_stale(
    u_root: Path,
    expected_hash: str,
    connected: set[str],
    instructions: dict[str, str],
    instructions_sig: str,
) -> None:
    """Rewrite the SKILL.md catalog + instructions projection iff anything changed.

    Gated on three signatures: the global skill-library hash, the connected-set,
    and the per-user instructions hash. A change in any one triggers a rewrite;
    the per-file ``matches_text`` checks inside the materializers keep untouched
    files at zero I/O.
    """
    current = read_skills_marker(u_root)
    connected_marker_path = u_root / ".gaia" / "connected.v"
    instructions_marker_path = u_root / ".gaia" / "instructions.v"
    connected_signature = ",".join(sorted(connected))
    previous_connected = read_text_or_none(connected_marker_path)
    previous_instructions = read_text_or_none(instructions_marker_path)
    if (
        current == expected_hash
        and previous_connected == connected_signature
        and previous_instructions == instructions_sig
    ):
        return
    materialize_skills(u_root, connected)
    materialize_instructions(u_root, instructions)
    write_skills_marker(u_root, expected_hash)
    connected_marker_path.parent.mkdir(parents=True, exist_ok=True)
    connected_marker_path.write_text(connected_signature, encoding="utf-8")
    instructions_marker_path.write_text(instructions_sig, encoding="utf-8")


async def ensure_session_dirs(user_id: str, conv_id: str) -> Path:
    """Create scratch/, user-uploaded/, artifacts/ + .meta.json. Idempotent."""

    def _mk() -> Path:
        base = session_base(user_id, conv_id)
        _ensure_session_subdirs(base)
        meta = base / SESSION_META_FILENAME
        if not meta.exists():
            now = now_iso()
            write_session_meta(meta, {"created_at": now, "last_active": now, "msg_count": 0})
        return base

    async with fs_timer(FsOps.ENSURE_SESSION_DIRS):
        return await asyncio.to_thread(_mk)


async def materialize_user_integrations(user_id: str, connected_ids: set[str]) -> None:
    """Hash-gated materialization of the full SKILL.md catalog for a user.

    Soft-fails if the JuiceFS mount is missing (dev mode).
    """
    # Late-bound to break the storage -> sessions -> lifecycle -> service ->
    # storage import cycle (the service transitively re-enters the storage pkg).
    from app.services.integration_instructions_service import (
        get_all_instructions,
        instructions_signature,
    )

    expected = library_hash()
    connected = set(connected_ids)
    instructions = await get_all_instructions(user_id)
    instructions_sig = instructions_signature(instructions)

    def _go() -> None:
        if not _is_mounted():
            return
        u_root = user_root(user_id)
        _materialize_if_stale(u_root, expected, connected, instructions, instructions_sig)

    async with fs_timer(FsOps.MATERIALIZE_INTEGRATIONS):
        await asyncio.to_thread(_go)


async def provision_user_workspace(user_id: str, connected_ids: set[str] | None = None) -> None:
    """User-level workspace provisioning: system-file symlinks (INDEX/GUIDE +
    builtin skills) + the SKILL.md / instructions catalog.

    Run on the events that actually change it — registration, integration
    connect/disconnect, and startup — instead of every chat turn. Idempotent and
    hash-gated, so repeat calls are near-zero I/O. Soft-fails when JuiceFS is
    unmounted (native dev).
    """
    # Late-bound: ``app.services.storage`` re-exports this module, so importing
    # ``system_workspace`` (which imports ``storage.juicefs``) at top level would
    # re-enter the half-initialized storage package.
    from app.services.storage.system_workspace import link_system_files_into_workspace

    await link_system_files_into_workspace(user_id)
    await materialize_user_integrations(user_id, connected_ids or set())


async def delete_session_dir(user_id: str, conv_id: str) -> None:
    """Recursive delete of a session dir. Soft-fail if the mount is missing."""

    def _delete() -> None:
        if not _is_mounted():
            return
        try:
            base = session_root(user_id, conv_id)
        except ValueError:
            return
        if base.is_symlink() or not base.exists():
            return
        shutil.rmtree(base, ignore_errors=True)

    async with fs_timer(FsOps.DELETE_SESSION_DIR):
        await asyncio.to_thread(_delete)


async def touch_session_last_active(user_id: str, conv_id: str) -> None:
    """Bump ``.meta.json.last_active``. Raises ``JuiceFSUnavailable`` if unmounted."""

    def _touch() -> None:
        base = session_base(user_id, conv_id)
        base.mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        data = read_session_meta(meta)
        now = now_iso()
        data.setdefault("created_at", now)
        data.setdefault("msg_count", 0)
        data["last_active"] = now
        write_session_meta(meta, data)

    async with fs_timer(FsOps.TOUCH_LAST_ACTIVE):
        await asyncio.to_thread(_touch)


async def chmod_path(host_path: Path, mode: int) -> None:
    """Off-loop ``os.chmod``."""
    await asyncio.to_thread(os.chmod, host_path, mode)


async def list_session_ids(user_id: str) -> list[str]:
    """Return conversation ids that have an on-disk session dir for this user."""

    def _scan() -> list[str]:
        if not _is_mounted():
            return []
        sessions_dir = _mount_root() / "users" / user_id / "sessions"
        if not sessions_dir.is_dir():
            return []
        return sorted(p.name for p in sessions_dir.iterdir() if p.is_dir())

    async with fs_timer(FsOps.LIST_SESSION_IDS):
        return await asyncio.to_thread(_scan)


def _stale_in_user_dir(user_dir: Path, cutoff: datetime) -> list[tuple[str, str]]:
    sessions_dir = user_dir / "sessions"
    if not sessions_dir.is_dir():
        return []
    found: list[tuple[str, str]] = []
    for sess in sorted(sessions_dir.iterdir()):
        if not sess.is_dir():
            continue
        last_active = parse_last_active(sess / SESSION_META_FILENAME)
        if last_active is None or last_active >= cutoff:
            continue
        found.append((user_dir.name, sess.name))
    return found


def _scan_stale_sessions(cutoff_days: int, limit: int | None) -> list[tuple[str, str]]:
    if not _is_mounted():
        return []
    users_root = _mount_root() / "users"
    if not users_root.is_dir():
        return []
    cutoff = datetime.now(UTC) - timedelta(days=cutoff_days)
    stale: list[tuple[str, str]] = []
    for user_dir in sorted(users_root.iterdir()):
        stale.extend(_stale_in_user_dir(user_dir, cutoff))
        if limit is not None and len(stale) >= limit:
            return stale[:limit]
    return stale


async def list_stale_sessions(cutoff_days: int, limit: int | None = None) -> list[tuple[str, str]]:
    """Return (user_id, conv_id) for sessions inactive past ``cutoff_days``.

    Sessions whose ``last_active`` cannot be parsed are skipped, never pruned.
    """
    async with fs_timer(FsOps.LIST_STALE_SESSIONS):
        return await asyncio.to_thread(_scan_stale_sessions, cutoff_days, limit)
