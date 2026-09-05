#!/usr/bin/env python3
"""One-time, idempotent existing-user briefing rollout.

For every user: provision the daily-briefing + weekly-digest system workflows.
Users we can derive a goal for get a real first briefing next morning; sparse
users with no derivable goal have their briefings held (bootstrap marker) until a
goal arrives or the grace window elapses. The user-facing announcement is sent
manually by email, not from here. Safe to re-run — provisioning is idempotent by
``system_workflow_key`` and the path taken is logged.

Run: uv run python -m scripts.provision_daily_briefings [--dry-run]
"""

import asyncio
import sys

from app.db.repositories.users import user_repository
from app.services.briefing.rollout import provision_existing_user


async def rollout(dry_run: bool) -> None:
    user_ids = await user_repository.list_all_ids()
    total = len(user_ids)
    print(f"users to roll out: {total}")
    if dry_run:
        return

    paths: dict[str, int] = {}
    processed = 0
    for user_id in user_ids:
        try:
            path = await provision_existing_user(user_id)
        except Exception as e:  # one bad user must not abort the whole rollout
            print(f"  user {user_id}: FAILED ({e})")
            paths["failed"] = paths.get("failed", 0) + 1
            continue
        paths[path] = paths.get(path, 0) + 1
        processed += 1
        if processed % 100 == 0:
            print(f"  ...{processed}/{total}")

    print(f"done: {processed}/{total} rolled out; breakdown={paths}")


if __name__ == "__main__":
    asyncio.run(rollout(dry_run="--dry-run" in sys.argv))
