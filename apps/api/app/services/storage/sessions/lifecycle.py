"""Session lifecycle — bootstrap, dir creation, deletion, idle scan.

Orchestrates the per-turn FS work for a chat conversation. ``bootstrap_user_session``
is the hot path called on every chat-stream entry; the rest is admin (idle
prune, user-level integration materialization, hard delete) reached from
workers and the ``/sessions`` admin endpoints.
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
    write_user_root_docs,
)


async def bootstrap_user_session(
    user_id: str,
    conv_id: str,
    connected_ids: set[str] | None = None,
) -> Path:
    """Idempotent + hash-gated session bootstrap for a chat turn.

    Combines session-dir creation, ``.meta.json`` touch, SKILL.md catalog
    materialization, the gaia-tasks VFS sync, and the user-todos VFS
    sync. Steady-state turns do zero writes when the library hash, the
    connected set, the gaia-tasks catalog, and the user-todos catalog
    haven't changed since the last bootstrap.

    Order matters: gaia-tasks runs first because it owns the legacy
    ``/workspace/todos/`` cleanup (the prior release used that path for
    gaia-tasks). user-todos then populates the now-empty ``/todos/``.
    """
    # Late-bound to break a structural cycle: ``app.services.storage`` re-
    # exports ``sessions`` (which re-exports this module), and the
    # gaia-tasks / user-todos modules import ``storage.juicefs`` — which
    # forces ``storage/__init__.py`` to run mid-import. Importing here,
    # after the package graph is fully resolved, is the only break that
    # does not require restructuring multiple ``__init__.py`` files.
    from app.services.gaia_tasks_fs import sync_user_gaia_tasks
    from app.services.integration_instructions_service import (
        get_all_instructions,
        instructions_signature,
    )
    from app.services.user_todos_fs import sync_user_todos

    connected = connected_ids or set()
    expected_hash = library_hash()
    instructions = await get_all_instructions(user_id)
    instructions_sig = instructions_signature(instructions)

    def _go() -> Path:
        base = session_base(user_id, conv_id)
        u_root = base.parent.parent
        _ensure_session_subdirs(base)
        _stamp_meta_on_bootstrap(base / SESSION_META_FILENAME)
        write_user_root_docs(u_root)
        _materialize_if_stale(u_root, expected_hash, connected, instructions, instructions_sig)
        return base

    async with fs_timer(FsOps.BOOTSTRAP_USER_SESSION):
        base = await asyncio.to_thread(_go)
        await sync_user_gaia_tasks(user_id)
        await sync_user_todos(user_id)
        return base


def _ensure_session_subdirs(base: Path) -> None:
    """Create the scratch/, user-uploaded/, artifacts/ trio under a session root."""
    for sub in (SCRATCH_DIRNAME, USER_UPLOADED_DIRNAME, ARTIFACTS_DIRNAME):
        (base / sub).mkdir(parents=True, exist_ok=True)


def _stamp_meta_on_bootstrap(meta: Path) -> None:
    """Set ``created_at`` (once), ``msg_count`` (once), and bump ``last_active``."""
    data = read_session_meta(meta)
    now = now_iso()
    data.setdefault("created_at", now)
    data.setdefault("msg_count", 0)
    data["last_active"] = now
    write_session_meta(meta, data)


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
        write_user_root_docs(base.parent.parent)
        return base

    async with fs_timer(FsOps.ENSURE_SESSION_DIRS):
        return await asyncio.to_thread(_mk)


async def materialize_user_integrations(user_id: str, connected_ids: set[str]) -> None:
    """Hash-gated materialization of the full SKILL.md catalog for a user.

    Soft-fails if the JuiceFS mount is missing (dev mode).
    """
    # Late-bound to break the same structural import cycle as in
    # ``bootstrap_user_session`` (storage -> sessions -> lifecycle -> service,
    # where the service transitively re-enters storage via the decorators pkg).
    from app.services.integration_instructions_service import (
        get_all_instructions,
        instructions_signature,
    )

    expected = library_hash()
    connected = set(connected_ids)
    instructions = await get_all_instructions(user_id)
    instructions_sig = instructions_signature(instructions)

    def _go() -> int:
        if not _is_mounted():
            return 0
        u_root = user_root(user_id)
        _materialize_if_stale(u_root, expected, connected, instructions, instructions_sig)
        return 0

    async with fs_timer(FsOps.MATERIALIZE_INTEGRATIONS):
        await asyncio.to_thread(_go)


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


async def list_stale_sessions(cutoff_days: int, limit: int | None = None) -> list[tuple[str, str]]:
    """Return (user_id, conv_id) for sessions inactive past ``cutoff_days``.

    Sessions whose ``last_active`` cannot be parsed are skipped, never pruned.
    """

    def _scan() -> list[tuple[str, str]]:
        if not _is_mounted():
            return []
        users_root = _mount_root() / "users"
        if not users_root.is_dir():
            return []
        cutoff = datetime.now(UTC) - timedelta(days=cutoff_days)
        stale: list[tuple[str, str]] = []
        for user_dir in sorted(users_root.iterdir()):
            sessions_dir = user_dir / "sessions"
            if not sessions_dir.is_dir():
                continue
            for sess in sorted(sessions_dir.iterdir()):
                if not sess.is_dir():
                    continue
                last_active = parse_last_active(sess / SESSION_META_FILENAME)
                if last_active is None or last_active >= cutoff:
                    continue
                stale.append((user_dir.name, sess.name))
                if limit is not None and len(stale) >= limit:
                    return stale
        return stale

    async with fs_timer(FsOps.LIST_STALE_SESSIONS):
        return await asyncio.to_thread(_scan)
