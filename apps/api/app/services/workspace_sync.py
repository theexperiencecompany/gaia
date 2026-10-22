"""Bulk user-workspace provisioning/sync.

Re-materializes the per-user JuiceFS workspace (system symlinks + user-root docs
+ SKILL.md / instructions catalog) for many users at once. Two callers share
this core:

* **App startup** (unified_startup): bounded run over users not yet dormant
  (ActivityStatus) whose on-disk skills marker is stale vs. the current library_hash() — so a
  deploy that ships new builtin skills re-syncs everyone who's been using GAIA,
  without touching the chat-turn hot path.
* **Developer CLI** (app/scripts/sync_user_workspaces.py): one-off backfill of
  users who predate registration-time provisioning, or a forced re-sync.

Per-user work is delegated to :func:provision_user_workspace, which is
idempotent and hash-gated; this module only decides *which* users to touch.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.agents.workspace.skill_loader import library_hash
from app.constants.user_activity import ActivityStatus
from app.core.lazy_loader import providers
from app.db.repositories.users import user_repository
from app.services._vfs_scheduler import make_scheduler
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.storage import provision_user_workspace
from app.services.storage.juicefs import _is_mounted
from app.services.storage.sessions._paths import user_root
from app.services.storage.sessions.skills import read_skills_marker
from app.services.storage.system_workspace import ensure_system_subtree
from shared.py.wide_events import log


async def _provision(user_id: str) -> int:
    """Provision a single user's workspace (adapter for the fire-and-forget scheduler)."""
    await provision_user_workspace(user_id)
    return 0


# Fire-and-forget wrapper for registration: provision a brand-new user's
# workspace without blocking signup. No-ops when JuiceFS is unmounted (dev).
schedule_user_provision = make_scheduler(_provision, log_name="user_provision")


@dataclass(frozen=True, slots=True)
class WorkspaceSyncResult:
    """Counts from one bulk workspace sync run."""

    scanned: int
    synced: int
    skipped: int


async def _active_user_ids() -> list[str]:
    """Ids of users GAIA still serves: active or idle, never dormant."""
    return [
        user.id
        for status in (ActivityStatus.ACTIVE, ActivityStatus.IDLE)
        for user in await user_repository.find_by_activity_status(status)
    ]


async def sync_stale_user_workspaces(
    *,
    active_only: bool = True,
    force: bool = False,
) -> WorkspaceSyncResult:
    """Re-provision users whose skills marker != current library_hash().

    active_only restricts to users not yet dormant (the startup default). force re-provisions
    regardless of the marker. No-ops when JuiceFS is unmounted.
    """
    if not _is_mounted():
        log.info("workspace_sync.skipped_no_mount")
        return WorkspaceSyncResult(scanned=0, synced=0, skipped=0)

    expected = library_hash()
    user_ids = await (_active_user_ids() if active_only else user_repository.list_all_ids())

    scanned = synced = skipped = 0
    for user_id in user_ids:
        scanned += 1
        if not force:
            marker = await asyncio.to_thread(read_skills_marker, user_root(user_id))
            if marker == expected:
                skipped += 1
                continue
        try:
            await provision_user_workspace(user_id, await get_connected_integration_ids(user_id))
            synced += 1
        except Exception as e:  # one bad user must not abort the batch
            log.warning("workspace_sync.user_failed", user_id=user_id, error=str(e))

    log.info(
        "workspace_sync.done",
        scanned=scanned,
        synced=synced,
        skipped=skipped,
        force=force,
        active_only=active_only,
    )
    return WorkspaceSyncResult(scanned=scanned, synced=synced, skipped=skipped)


async def init_system_subtree() -> None:
    """Materialize the shared _system subtree at startup (idempotent, hash-gated; no-op without a mount)."""
    await providers.aget("juicefs_mount")
    await ensure_system_subtree()


async def resync_stale_user_workspaces() -> None:
    """Re-provision active users whose skill catalog is stale; the dev script covers backfill/ad-hoc runs."""
    await providers.aget("juicefs_mount")
    await sync_stale_user_workspaces(active_only=True)
