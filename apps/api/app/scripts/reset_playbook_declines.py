#!/usr/bin/env python3
"""Give back the playbook chances that blocked runs spent.

``decline_playbook`` used to count every decline against the workflow, including
the ones where the run never reached the work. In production roughly 80% of
declines said the same thing: the workflow needs an integration the user has
never connected. A workflow firing twice a day burns all three of its chances in
under two days that way, and ``PLAYBOOK_DECLINE_LIMIT`` then stops the check
being asked at all. Only an edit to the workflow resets the tally, so those
workflows can never earn a playbook again, not even after the user connects the
integration.

The blocked kinds no longer count, but the tallies they already ran up are still
on the workflows. This clears them, so the next run is asked again.

Dry run by default. Nothing is written without ``--apply``.

Usage::

    cd apps/api
    uv run python -m app.scripts.reset_playbook_declines            # report only
    uv run python -m app.scripts.reset_playbook_declines --apply
    uv run python -m app.scripts.reset_playbook_declines --apply --at-limit-only
"""

from __future__ import annotations

import argparse
import asyncio

from app.config.settings import settings
from app.constants.agents import PLAYBOOK_DECLINE_LIMIT
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME, MongoDB


async def _run(args: argparse.Namespace) -> None:
    database = MongoDB(settings.MONGO_DB, MONGO_DATABASE_NAME).database
    workflows = database["workflows"]

    floor = PLAYBOOK_DECLINE_LIMIT if args.at_limit_only else 1
    query = {"playbook_declines": {"$gte": floor}}

    affected = await workflows.count_documents(query)
    at_limit = await workflows.count_documents(
        {"playbook_declines": {"$gte": PLAYBOOK_DECLINE_LIMIT}}
    )
    print(f"workflows with at least {floor} decline(s): {affected}")
    print(f"...of which locked out at the limit of {PLAYBOOK_DECLINE_LIMIT}: {at_limit}")

    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply to clear them.")
        return

    # playbook_declined_hash goes with the count: it is the hash those declines
    # were about, and leaving it behind would make the next decline look like a
    # continuation of a tally that no longer exists.
    result = await workflows.update_many(
        query, {"$set": {"playbook_declines": 0, "playbook_declined_hash": None}}
    )
    print(f"\ncleared the tally on {result.modified_count} workflow(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the changes")
    parser.add_argument(
        "--at-limit-only",
        action="store_true",
        help=f"only workflows already locked out at {PLAYBOOK_DECLINE_LIMIT} declines",
    )
    asyncio.run(_run(parser.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
