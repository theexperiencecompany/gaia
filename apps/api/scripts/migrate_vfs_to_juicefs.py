#!/usr/bin/env python3
"""Copy a user's MongoDB-VFS data to their JuiceFS workspace.

This is the one-shot migration that backs the hard cutover from the old
MongoDB-backed VFS to the persistent E2B+JuiceFS workspace. For each user it:

  1. Reads all files from `/users/{user_id}/executor/files` and
     `/users/{user_id}/executor/notes` in the legacy `vfs_nodes` collection.
  2. Writes them into `/mnt/jfs/users/{user_id}/legacy/` on the host JuiceFS
     mount.
  3. Marks `legacy_imported=True` on the user's `e2b_sandboxes` doc.

NOTE: the runtime VFS service has been deleted; this script accesses the
legacy `vfs_nodes` MongoDB collection directly so it can run during the
cutover release. After it completes successfully you can drop the collection.

Skills migration: handled inline because installed skills already get
re-written to JuiceFS by the updated installer the next time they install/
sync a skill. For pre-existing user skills, run this script first and a
companion task will re-stamp skill files into `/mnt/jfs/skills/{user_id}/`.

Usage:
    cd apps/api
    uv run python scripts/migrate_vfs_to_juicefs.py            # all users
    uv run python scripts/migrate_vfs_to_juicefs.py --user X   # single user
    uv run python scripts/migrate_vfs_to_juicefs.py --dry-run

Requires the host JuiceFS mount to be available at JUICEFS_HOST_MOUNT_PATH.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
import sys

from app.db.mongodb.collections import (
    e2b_sandboxes_collection,
    users_collection,
    vfs_nodes_collection,
)
from app.services.storage import (
    JuiceFSUnavailable,
    ensure_user_workspace,
)
from shared.py.wide_events import log


async def _list_user_files(user_id: str) -> list[dict]:
    prefix = f"/users/{user_id}/executor/"
    cursor = vfs_nodes_collection.find(
        {
            "user_id": user_id,
            "path": {"$regex": f"^{prefix}(files|notes)/"},
            "type": "file",
        }
    )
    return [doc async for doc in cursor]


def _legacy_relative(node_path: str, user_id: str) -> str:
    """Strip the VFS prefix so the file lands at /workspace/legacy/<relative>."""
    return node_path.replace(f"/users/{user_id}/executor/", "", 1)


async def migrate_one(user_id: str, *, dry_run: bool = False) -> dict:
    files = await _list_user_files(user_id)
    if not files:
        return {"user_id": user_id, "files": 0, "status": "no-data"}

    if dry_run:
        return {"user_id": user_id, "files": len(files), "status": "dry-run"}

    try:
        workspace = await ensure_user_workspace(user_id)
    except JuiceFSUnavailable as e:
        return {"user_id": user_id, "files": 0, "status": f"skipped ({e})"}

    legacy_root = workspace / "legacy"
    legacy_root.mkdir(parents=True, exist_ok=True)

    written = 0
    for doc in files:
        relative = _legacy_relative(doc["path"], user_id)
        target = legacy_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = doc.get("content")
        if content is None:
            log.warning(f"[migrate] {user_id}: skipping {relative} (no inline content)")
            continue
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        written += 1

    await e2b_sandboxes_collection.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "legacy_imported": True,
                "legacy_imported_at": datetime.now(UTC),
            }
        },
        upsert=True,
    )
    return {"user_id": user_id, "files": written, "status": "ok"}


async def _all_user_ids() -> AsyncIterator[str]:
    async for doc in users_collection.find({}, projection={"_id": 1}):
        yield str(doc["_id"])


async def main_async(args: argparse.Namespace) -> int:
    if args.user:
        targets = [args.user]
    else:
        targets = [u async for u in _all_user_ids()]

    summary: list[dict] = []
    for user_id in targets:
        result = await migrate_one(user_id, dry_run=args.dry_run)
        summary.append(result)
        log.info(f"[migrate] {result}")

    total_files = sum(r["files"] for r in summary)
    print(
        f"Migrated {len(summary)} users, {total_files} files (dry_run={args.dry_run})",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", help="Single user_id to migrate")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
