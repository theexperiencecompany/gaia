"""Move the pre-isolation shared sandbox volume into per-user workspaces, once.

Every local sandbox used to mount one shared volume at /workspace. A session
directory (sessions/<conversation_id>) has a provable owner, the conversation's
user, so it is copied into that user's workspace. Nothing else has an owner
that can be proven, so it is reported and left behind, never exposed. The copy
never overwrites or deletes, never follows a symlink, and its report doubles as
the done-marker.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import shutil
import stat

from pydantic import BaseModel, Field

from app.agents.workspace.paths import SESSIONS_DIRNAME
from app.config.settings import settings
from app.constants.vfs import SAFE_PATH_ID_PATTERN
from app.db.repositories.conversations import conversation_repository
from app.services.storage.juicefs import ensure_user_workspace
from shared.py.wide_events import log

MIGRATION_REPORT_RELPATH = Path("_migrations") / "legacy-sandbox-workspace.json"
_SAFE_ID_RE = re.compile(SAFE_PATH_ID_PATTERN)


class LegacyWorkspaceReport(BaseModel):
    """What the migration moved and what it had to leave in the legacy volume."""

    migrated_sessions: dict[str, str] = Field(
        default_factory=dict, description="conversation id -> owning user id"
    )
    copied_files: int = 0
    skipped_existing: int = 0
    unresolved: list[str] = Field(
        default_factory=list, description="Legacy paths with no provable owner, left in place"
    )
    unreadable: list[str] = Field(
        default_factory=list, description="Legacy files that could not be read, left in place"
    )


def report_path() -> Path:
    return Path(settings.JUICEFS_HOST_MOUNT_PATH) / MIGRATION_REPORT_RELPATH


def _is_safe_id(value: str) -> bool:
    return _SAFE_ID_RE.match(value) is not None


def _copy_tree_without_overwrite(
    src: Path, dst: Path, legacy_root: Path, report: LegacyWorkspaceReport
) -> None:
    # os.walk never descends into a symlinked directory unless followlinks is set.
    for dirpath, dirnames, filenames in os.walk(src):
        here = Path(dirpath)
        target_dir = dst / here.relative_to(src)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in [*filenames, *(d for d in dirnames if (here / d).is_symlink())]:
            source = here / name
            target = target_dir / name
            if target.exists() or target.is_symlink():
                report.skipped_existing += 1
                continue
            mode = source.lstat().st_mode
            try:
                if stat.S_ISLNK(mode):
                    # Recreated verbatim; it resolves inside the owner's own sandbox view.
                    target.symlink_to(source.readlink())
                elif stat.S_ISREG(mode):
                    shutil.copy2(
                        source,
                        target,
                        # S_ISREG rules out a symlink; this closes the lstat-to-copy race.
                        follow_symlinks=False,
                    )
                else:
                    report.unresolved.append(source.relative_to(legacy_root).as_posix())
                    continue
            except PermissionError:
                report.unreadable.append(source.relative_to(legacy_root).as_posix())
                continue
            report.copied_files += 1


async def migrate_legacy_sandbox_workspace(legacy_root: Path) -> LegacyWorkspaceReport | None:
    """Copy owned session dirs from legacy_root into their users' workspaces.

    Returns None when an earlier run already wrote its report.
    """
    marker = report_path()
    if marker.exists():
        return None
    report = LegacyWorkspaceReport()
    sessions_root = legacy_root / SESSIONS_DIRNAME
    entries = sorted(legacy_root.iterdir()) if legacy_root.is_dir() else []
    report.unresolved.extend(e.name for e in entries if e.name != SESSIONS_DIRNAME)

    session_entries = (
        sorted(sessions_root.iterdir())
        if sessions_root.is_dir() and not sessions_root.is_symlink()
        else []
    )
    sessions = [p for p in session_entries if p.is_dir() and not p.is_symlink()]
    report.unresolved.extend(
        p.relative_to(legacy_root).as_posix() for p in session_entries if p not in sessions
    )
    candidate_ids = [p.name for p in sessions if _is_safe_id(p.name)]
    owners = await conversation_repository.owners_of(candidate_ids) if candidate_ids else {}
    for session in sessions:
        user_id = owners.get(session.name)
        if user_id is None or not _is_safe_id(user_id):
            report.unresolved.append(session.relative_to(legacy_root).as_posix())
            continue
        user_root = await ensure_user_workspace(user_id)
        await asyncio.to_thread(
            _copy_tree_without_overwrite,
            session,
            user_root / SESSIONS_DIRNAME / session.name,
            legacy_root,
            report,
        )
        report.migrated_sessions[session.name] = user_id

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(report.model_dump_json(indent=2).encode())
    log.set(
        legacy_workspace_migration={
            "sessions": len(report.migrated_sessions),
            "copied_files": report.copied_files,
            "unresolved": len(report.unresolved),
            "unreadable": len(report.unreadable),
        }
    )
    return report
