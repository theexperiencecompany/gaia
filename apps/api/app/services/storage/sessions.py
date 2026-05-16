"""Host-side session workspace helpers.

Everything under ``users/{user_id}/sessions/{conversation_id}/`` plus the
cross-session ``pinned/`` dir: creation, artifact listing, single-file
resolution for the HTTP layer, pinning, and the inactivity prune scan.

All filesystem access goes through the JuiceFS host mount primitives in
``juicefs.py``; this module only owns the *session* directory convention.

The hot path for chat is ``bootstrap_user_session`` — one async hop that fuses
session-dir creation, the ``.meta.json`` touch, and the SKILL.md catalog
materialization. It is hash-gated so a deploy that doesn't change the skill
library does **zero** redundant writes per chat turn.
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
    ARTIFACTS_DIRNAME,
    SCRATCH_DIRNAME,
    USER_UPLOADED_DIRNAME,
    detect_content_type,
)
from app.agents.workspace.skill_loader import library_hash, skills_by_subagent
from app.agents.workspace.system_docs import (
    INDEX_MD,
    INTEGRATIONS_GUIDE_MD,
    SESSIONS_GUIDE_MD,
)
from app.services.storage.juicefs import (
    _contained,
    _is_mounted,
    _mount_root,
    _require_mount,
)
from app.services.storage.metrics import FS_OPS, fs_timer

SESSION_META_FILENAME = ".meta.json"
SESSION_META_SCHEMA_VERSION = 1

# Per-user marker file recording the SKILL.md library hash the user's
# integrations/ tree was last materialized from. When it matches the current
# library_hash() we can skip rewriting the 30+ skill bodies on every turn.
_SKILLS_HASH_MARKER = ".gaia/skills.v"

SessionRole = Literal["artifacts", "uploaded"]
_ROLE_DIRNAMES: dict[SessionRole, str] = {
    "artifacts": ARTIFACTS_DIRNAME,
    "uploaded": USER_UPLOADED_DIRNAME,
}


@dataclass(slots=True)
class ArtifactInfo:
    """A single file under a session's ``artifacts/`` or ``user-uploaded/``."""

    path: str  # path relative to the listed root (POSIX, forward slashes)
    size_bytes: int
    mtime: float  # Unix epoch seconds
    content_type: str | None


# ---------------------------------------------------------------------------
# Path & helper internals (pure — no I/O, never raise JuiceFSUnavailable)
# ---------------------------------------------------------------------------


def _session_base(user_id: str, conv_id: str) -> Path:
    """Host path for a session dir. Raises JuiceFSUnavailable if unmounted."""
    return _require_mount() / "users" / user_id / "sessions" / conv_id


def _user_root(user_id: str) -> Path:
    """Host path for a user's workspace root. Caller must have ensured mount."""
    return _mount_root() / "users" / user_id


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


def _read_session_meta(meta: Path) -> dict[str, object]:
    """Load ``.meta.json`` defensively, returning ``{}`` on any read/parse error."""
    if not meta.exists():
        return {}
    try:
        loaded = json.loads(meta.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_session_meta(meta: Path, data: dict[str, object]) -> None:
    """Persist a session ``.meta.json`` with the current schema version stamped."""
    data["schema_version"] = SESSION_META_SCHEMA_VERSION
    meta.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-session bootstrap — fused hot path
# ---------------------------------------------------------------------------


def _write_user_root_docs(user_root: Path) -> None:
    """Write INDEX.md + sessions/GUIDE.md if their content has actually changed.

    These files are tiny (<4 KB) but written by every chat turn historically.
    Skipping the rewrite when content matches drops a couple syscalls per turn;
    the prose-update path still rolls out automatically because the source is
    a Python constant.
    """
    index = user_root / "INDEX.md"
    if not _matches_text(index, INDEX_MD):
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(INDEX_MD, encoding="utf-8")
    sessions_guide = user_root / "sessions" / "GUIDE.md"
    if not _matches_text(sessions_guide, SESSIONS_GUIDE_MD):
        sessions_guide.parent.mkdir(parents=True, exist_ok=True)
        sessions_guide.write_text(SESSIONS_GUIDE_MD, encoding="utf-8")


def _matches_text(path: Path, expected: str) -> bool:
    """Cheap content-equality check that avoids rewriting unchanged docs.

    ``read_text`` is a single syscall against JuiceFS's metadata cache — far
    cheaper than the equivalent ``write_text``, which fans out into a meta
    update and may trigger an async R2 upload.
    """
    try:
        return path.read_text(encoding="utf-8") == expected
    except (OSError, UnicodeDecodeError):
        return False


def _materialize_skills(user_root: Path, connected_ids: set[str]) -> int:
    """Lay down the SKILL.md catalog under ``integrations/`` and ``skills/``.

    Returns the number of skill bodies actually written. Caller is responsible
    for the hash-gate; this function always writes.
    """
    written = 0
    integrations_root = user_root / "integrations"
    integrations_root.mkdir(parents=True, exist_ok=True)
    if not _matches_text(integrations_root / "GUIDE.md", INTEGRATIONS_GUIDE_MD):
        (integrations_root / "GUIDE.md").write_text(
            INTEGRATIONS_GUIDE_MD, encoding="utf-8"
        )

    grouped = skills_by_subagent()
    for iid, skills in grouped.items():
        if iid == "executor" or not skills:
            continue
        agent_dir = integrations_root / iid / "agent"
        skills_dir = agent_dir / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            slug_dir = skills_dir / skill.slug
            slug_dir.mkdir(parents=True, exist_ok=True)
            target = slug_dir / "skill.md"
            if not _matches_text(target, skill.body):
                target.write_text(skill.body, encoding="utf-8")
                written += 1
        marker = agent_dir / ".connected"
        if iid in connected_ids:
            if not marker.exists():
                marker.write_text("", encoding="utf-8")
        elif marker.exists():
            marker.unlink()

    # General-purpose skills (target: executor) live at the workspace root.
    for skill in grouped.get("executor", []):
        slug_dir = user_root / "skills" / skill.slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        target = slug_dir / "skill.md"
        if not _matches_text(target, skill.body):
            target.write_text(skill.body, encoding="utf-8")
            written += 1
    return written


def _read_skills_marker(user_root: Path) -> str | None:
    """Read the user's last-materialized library hash, or None if absent."""
    marker = user_root / _SKILLS_HASH_MARKER
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


def _write_skills_marker(user_root: Path, value: str) -> None:
    """Persist the library hash so we can short-circuit on the next bootstrap."""
    marker = user_root / _SKILLS_HASH_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value, encoding="utf-8")


async def bootstrap_user_session(
    user_id: str,
    conv_id: str,
    connected_ids: set[str] | None = None,
) -> Path:
    """One-shot host-side bootstrap for a chat turn — idempotent + hash-gated.

    Fuses what used to be three separate ``asyncio.to_thread`` hops:
      1. ``ensure_session_dirs``   — scratch/, user-uploaded/, artifacts/
      2. ``touch_session_last_active`` — bump ``.meta.json.last_active``
      3. ``materialize_user_integrations`` — full SKILL.md catalog write

    Plus a content-hash gate against ``library_hash()`` so steady-state turns
    do **zero** skill rewrites. The user-root harness docs (``INDEX.md`` and
    ``sessions/GUIDE.md``) are likewise skipped when the on-disk bytes already
    match the in-process constant.

    Returns the session base path. Raises ``JuiceFSUnavailable`` if the host
    mount is missing — callers (chat_service) treat that as a soft-fail.
    """

    connected = connected_ids or set()
    expected_hash = library_hash()

    def _go() -> Path:
        base = _session_base(user_id, conv_id)
        user_root = base.parent.parent

        # 1. Session dirs + meta. Always cheap, always idempotent.
        for sub in (SCRATCH_DIRNAME, USER_UPLOADED_DIRNAME, ARTIFACTS_DIRNAME):
            (base / sub).mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        meta_data = _read_session_meta(meta)
        now = _now_iso()
        meta_data.setdefault("created_at", now)
        meta_data.setdefault("msg_count", 0)
        meta_data["last_active"] = now
        _write_session_meta(meta, meta_data)

        # 2. User-root harness docs (only rewrite when the constant changed).
        _write_user_root_docs(user_root)

        # 3. Skill catalog — gated on library hash + connection set delta.
        current = _read_skills_marker(user_root)
        # Connection state is part of the gate: if the set changed we still
        # need to touch ``.connected`` markers under each integration.
        connected_marker_path = user_root / ".gaia" / "connected.v"
        connected_signature = ",".join(sorted(connected))
        previous_connected = _read_text_or_none(connected_marker_path)
        if current != expected_hash or previous_connected != connected_signature:
            _materialize_skills(user_root, connected)
            _write_skills_marker(user_root, expected_hash)
            connected_marker_path.parent.mkdir(parents=True, exist_ok=True)
            connected_marker_path.write_text(connected_signature, encoding="utf-8")
        return base

    async with fs_timer(FS_OPS.BOOTSTRAP_USER_SESSION):
        return await asyncio.to_thread(_go)


def _read_text_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Granular helpers — still used by tests, scripts, and the prune worker
# ---------------------------------------------------------------------------


async def ensure_session_dirs(user_id: str, conv_id: str) -> Path:
    """Create scratch/, user-uploaded/, artifacts/ + .meta.json.

    Idempotent. Raises ``JuiceFSUnavailable`` if the host mount is missing.
    Kept as a thin wrapper for callers (scripts) that don't need the full
    fused bootstrap.
    """

    def _mk() -> Path:
        base = _session_base(user_id, conv_id)
        for sub in (SCRATCH_DIRNAME, USER_UPLOADED_DIRNAME, ARTIFACTS_DIRNAME):
            (base / sub).mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        if not meta.exists():
            now = _now_iso()
            _write_session_meta(
                meta, {"created_at": now, "last_active": now, "msg_count": 0}
            )
        _write_user_root_docs(base.parent.parent)
        return base

    async with fs_timer(FS_OPS.ENSURE_SESSION_DIRS):
        return await asyncio.to_thread(_mk)


async def materialize_user_integrations(user_id: str, connected_ids: set[str]) -> None:
    """Lay down the FULL FS catalog of built-in skills for a user.

    Reads the canonical SKILL.md library at
    ``apps/api/app/agents/skills/builtin/`` via ``skill_loader`` and writes
    byte-identical bodies into the user's workspace:

        integrations/
            GUIDE.md                      — how the dir works
            <integration>/agent/skills/<slug>/skill.md   (every target subagent)
        skills/<slug>/skill.md            — executor-targeted general skills

    Connection state surfaces via a stub empty file at
    ``integrations/<id>/agent/.connected`` (present only for connected
    integrations) so the agent can tell which sub-tree the user can actually
    act on right now.

    Hash-gated: re-runs that find the user's marker matching the current
    ``library_hash()`` write nothing. Soft-fails if the JuiceFS mount is
    missing (dev mode).
    """

    expected = library_hash()
    connected = set(connected_ids)

    def _go() -> int:
        if not _is_mounted():
            return 0
        user_root = _user_root(user_id)
        if _read_skills_marker(user_root) == expected:
            return 0
        written = _materialize_skills(user_root, connected)
        _write_skills_marker(user_root, expected)
        return written

    async with fs_timer(FS_OPS.MATERIALIZE_INTEGRATIONS):
        await asyncio.to_thread(_go)


async def delete_session_dir(user_id: str, conv_id: str) -> None:
    """Recursive delete of a session dir. Soft-fail if the mount is missing."""

    def _delete() -> None:
        if not _is_mounted():
            return
        base = _mount_root() / "users" / user_id / "sessions" / conv_id
        if base.exists():
            shutil.rmtree(base, ignore_errors=True)

    async with fs_timer(FS_OPS.DELETE_SESSION_DIR):
        await asyncio.to_thread(_delete)


async def touch_session_last_active(user_id: str, conv_id: str) -> None:
    """Bump ``.meta.json.last_active`` — used by the prune worker as the
    activity signal. Raises ``JuiceFSUnavailable`` if the mount is missing."""

    def _touch() -> None:
        base = _session_base(user_id, conv_id)
        base.mkdir(parents=True, exist_ok=True)
        meta = base / SESSION_META_FILENAME
        data = _read_session_meta(meta)
        now = _now_iso()
        data.setdefault("created_at", now)
        data.setdefault("msg_count", 0)
        data["last_active"] = now
        _write_session_meta(meta, data)

    async with fs_timer(FS_OPS.TOUCH_LAST_ACTIVE):
        await asyncio.to_thread(_touch)


async def chmod_path(host_path: Path, mode: int) -> None:
    """Wrap ``os.chmod`` (used to make uploads read-only at mode=0o444)."""
    await asyncio.to_thread(os.chmod, host_path, mode)


async def list_artifacts(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Host-side recursive scan of a session's ``artifacts/``. Zero R2 ops
    (PG metadata only). Backs the GET endpoint + defense-in-depth recovery."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(_session_base(user_id, conv_id) / ARTIFACTS_DIRNAME)

    async with fs_timer(FS_OPS.LIST_ARTIFACTS):
        return await asyncio.to_thread(_go)


async def list_user_uploaded(user_id: str, conv_id: str) -> list[ArtifactInfo]:
    """Same shape as ``list_artifacts``, for the ``user-uploaded/`` dir."""

    def _go() -> list[ArtifactInfo]:
        return _list_files(_session_base(user_id, conv_id) / USER_UPLOADED_DIRNAME)

    async with fs_timer(FS_OPS.LIST_USER_UPLOADED):
        return await asyncio.to_thread(_go)


async def stat_artifact(
    user_id: str, conv_id: str, rel_path: str
) -> ArtifactInfo | None:
    """Single-file stat under ``artifacts/``. Used by the watcher to enrich
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

    async with fs_timer(FS_OPS.STAT_ARTIFACT):
        return await asyncio.to_thread(_stat)


async def resolve_session_path(
    user_id: str, conv_id: str, role: SessionRole, rel_path: str
) -> Path:
    """Resolve a request path under a session's visible/uploaded root.

    Raises ``JuiceFSUnavailable`` if the mount is missing, ValueError if
    ``rel_path`` escapes the root. Existence is the caller's concern (so it
    can distinguish 404 from 400).
    """

    def _resolve() -> Path:
        base = _session_base(user_id, conv_id) / _ROLE_DIRNAMES[role]
        return _contained(base, rel_path)

    async with fs_timer(FS_OPS.RESOLVE_SESSION_PATH, role=role):
        return await asyncio.to_thread(_resolve)


async def pin_session_artifact(
    user_id: str, conv_id: str, rel_path: str, target_name: str | None = None
) -> str:
    """Copy a ``artifacts/`` artifact into the user's cross-session
    ``pinned/`` dir. Returns the ``/workspace/...`` path of the pinned copy."""

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

    async with fs_timer(FS_OPS.PIN_ARTIFACT):
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

    async with fs_timer(FS_OPS.LIST_SESSION_IDS):
        return await asyncio.to_thread(_scan)


def _parse_last_active(meta: Path) -> datetime | None:
    """Read ``.meta.json.last_active`` as an aware datetime, or None."""
    data = _read_session_meta(meta)
    raw = data.get("last_active")
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
    """Return (user_id, conv_id) for sessions inactive past ``cutoff_days``.

    Conservative: a session whose ``last_active`` cannot be determined is
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

    async with fs_timer(FS_OPS.LIST_STALE_SESSIONS):
        return await asyncio.to_thread(_scan)
