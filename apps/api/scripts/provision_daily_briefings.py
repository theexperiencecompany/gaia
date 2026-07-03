#!/usr/bin/env python3
"""One-time, idempotent existing-user briefing rollout.

For every user: provision the daily-briefing + weekly-digest system workflows and
send a one-time all-channel announcement. Users we can derive a goal for get the
standard announcement (real first briefing next morning); sparse users with no
derivable goal get a short bootstrap interview and their briefings are held until
they answer or the grace window elapses. Safe to re-run — provisioning is
idempotent by ``system_workflow_key`` and the announcement path is logged.

Run: uv run python scripts/provision_daily_briefings.py [--dry-run]
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import users_collection  # noqa: E402
from app.services.briefing.rollout import announce_and_provision  # noqa: E402


async def rollout(dry_run: bool) -> None:
    total = await users_collection.count_documents({})
    print(f"users to roll out: {total}")
    if dry_run:
        return

    paths: dict[str, int] = {}
    processed = 0
    cursor = users_collection.find({}, {"_id": 1})
    async for doc in cursor:
        user_id = str(doc["_id"])
        try:
            path = await announce_and_provision(user_id)
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
