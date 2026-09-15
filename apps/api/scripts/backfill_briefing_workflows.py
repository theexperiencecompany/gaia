#!/usr/bin/env python3
"""Backfill the universal system workflows (the briefings) for existing users.

New users get them from seed_initial_user_data() at onboarding completion; users
who onboarded before that hook existed do not have them. This provisions the
universal set for every user whose onboarding is complete, through the same
idempotent provisioner, so re-runs are no-ops and a user who already has one of
the keys keeps it untouched.

Provisioning arms each schedule through the workflow scheduler, so the ARQ pool
is initialised first: run this with the API's Redis reachable.

Run from the api directory (or /app/apps/api inside the container):

    python scripts/backfill_briefing_workflows.py --dry-run
    python scripts/backfill_briefing_workflows.py --apply
    python scripts/backfill_briefing_workflows.py --apply --notify

Flags:
--dry-run  List the users and the keys each is missing. Default.
--apply    Actually create them. Required to write anything.
--notify   With --apply: send each user the "I set up N workflows for you"
           notification. Off by default so a backfill does not fan out a
           notification to every existing account.
--user-id  Limit the run to one user.
"""

import argparse
import asyncio
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.db.repositories.workflows import workflow_repository
from app.services.system_workflows.provisioner import (
    UNIVERSAL_SYSTEM_WORKFLOWS,
    provision_universal_system_workflows,
)
from app.services.workflow.scheduler import workflow_scheduler

users_collection = get_async_collection("users")


async def _onboarded_user_ids(user_id: str | None) -> list[str]:
    query: dict[str, object] = {"onboarding.completed": True}
    if user_id:
        query["_id"] = user_id
    return [str(doc["_id"]) async for doc in users_collection.find(query, {"_id": 1})]


async def _missing_keys(user_id: str) -> list[str]:
    return [
        key
        for key, _factory in UNIVERSAL_SYSTEM_WORKFLOWS
        if await workflow_repository.find_system_workflow(user_id, key) is None
    ]


async def run(*, apply: bool, notify: bool, user_id: str | None) -> None:
    user_ids = await _onboarded_user_ids(user_id)
    print(f"{len(user_ids)} onboarded user(s) in scope")

    candidates: dict[str, list[str]] = {}
    for uid in user_ids:
        missing = await _missing_keys(uid)
        if missing:
            candidates[uid] = missing
    print(f"{len(candidates)} user(s) missing at least one universal workflow")

    if not apply:
        for uid, missing in candidates.items():
            print(f"  would provision {uid}: {', '.join(missing)}")
        print("\nDRY RUN, nothing was written. Re-run with --apply.")
        return

    await workflow_scheduler.initialize()
    try:
        created_total = 0
        for uid in candidates:
            created = await provision_universal_system_workflows(uid, notify=notify)
            created_total += len(created)
            print(f"  provisioned {uid}: {len(created)} created")
        print(f"\nAPPLIED: {created_total} workflow(s) created across {len(candidates)} user(s)")
    finally:
        await workflow_scheduler.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report only (default)")
    mode.add_argument("--apply", action="store_true", help="Create the missing workflows")
    parser.add_argument("--notify", action="store_true", help="Notify each user (with --apply)")
    parser.add_argument("--user-id", help="Limit to one user id")
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, notify=args.notify, user_id=args.user_id))


if __name__ == "__main__":
    main()
