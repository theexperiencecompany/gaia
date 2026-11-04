#!/usr/bin/env python3
"""Remove the playbook decline tally from every workflow.

Workflows used to stop being asked for a playbook after three declines. That
give-up is gone: a workflow is asked on every run until it has a playbook. The
tally fields it left on stored workflows are read by nothing, and this unsets them.

Dry run by default. Nothing is written without ``--apply``.

Usage::

    cd apps/api
    uv run python -m app.scripts.drop_playbook_decline_state            # report only
    uv run python -m app.scripts.drop_playbook_decline_state --apply
"""

from __future__ import annotations

import argparse
import asyncio

from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB

WORKFLOWS_COLLECTION = "workflows"
DECLINE_FIELDS = ("playbook_declines", "playbook_declined_hash", "playbook_declined_run")


async def _run(args: argparse.Namespace) -> None:
    workflows = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database.get_collection(
        WORKFLOWS_COLLECTION
    )
    query = {"$or": [{field: {"$exists": True}} for field in DECLINE_FIELDS]}
    affected = await workflows.count_documents(query)
    print(f"workflows carrying decline state: {affected}")
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply to remove it.")
        return
    result = await workflows.update_many(query, {"$unset": dict.fromkeys(DECLINE_FIELDS, "")})
    print(f"\nremoved decline state from {result.modified_count} workflow(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    asyncio.run(_run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
