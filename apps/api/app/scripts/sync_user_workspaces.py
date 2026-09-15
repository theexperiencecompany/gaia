#!/usr/bin/env python3
"""Provision / re-sync user workspaces in bulk.

Re-materializes the per-user JuiceFS workspace (system-file symlinks,
user-root docs, SKILL.md/instructions catalog) for many users at once. Use
it after shipping new builtin skills (a deploy already re-syncs active users
at startup; this forces it and/or covers inactive ones) or to backfill users
who predate registration-time provisioning.

Per-user work reuses the same idempotent, hash-gated path used at
registration, so this is safe to re-run. Requires the JuiceFS mount (dockered
API / prod); no-ops on a host without it.

Usage: uv run python -m app.scripts.sync_user_workspaces [--all] [--force]
[--active-days N].
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
