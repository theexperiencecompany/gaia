#!/usr/bin/env python3
"""Provision / re-sync user workspaces in bulk.

Re-materializes the per-user JuiceFS workspace (system-file symlinks + user-root
docs + SKILL.md / instructions catalog) for many users at once. Run this when:

- You ship new builtin skills and want existing users re-synced immediately. A
  deploy already re-syncs *active* users at startup; this forces it and/or
  covers inactive users.
- Backfilling users who predate registration-time provisioning.

Per-user work is delegated to the same idempotent, hash-gated path used at
registration, so this is safe to re-run.

Usage::

    cd apps/api
    uv run python -m app.scripts.sync_user_workspaces                 # active users, stale only
    uv run python -m app.scripts.sync_user_workspaces --all           # every user, stale only
    uv run python -m app.scripts.sync_user_workspaces --all --force   # every user, ignore marker
    uv run python -m app.scripts.sync_user_workspaces --active-days 90

Requires the JuiceFS mount (run inside the dockered API / prod). No-ops on a
host without the mount.
"""

from __future__ import annotations

import argparse
import asyncio

from app.services.workspace_sync import sync_stale_user_workspaces


async def _run(args: argparse.Namespace) -> int:
    result = await sync_stale_user_workspaces(
        active_only=not args.all,
        active_days=args.active_days,
        force=args.force,
    )
    print(
        f"workspace sync complete: scanned={result['scanned']} "
        f"synced={result['synced']} skipped={result['skipped']}"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process every user, not just those with recent activity.",
    )
    parser.add_argument(
        "--active-days",
        type=int,
        default=None,
        help="Activity window in days (default: SESSION_RETENTION_DAYS).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-provision even when the on-disk skills marker is already current.",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
