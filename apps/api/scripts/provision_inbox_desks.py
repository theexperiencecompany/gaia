#!/usr/bin/env python3
"""One-time backfill: open the Inbox desk for every paying user who already has Gmail.

New users get their desk when they connect Gmail or start a plan; this covers the
users whose plan and Gmail both predate the desk. Run it before
retire_inbox_triage.py, which switches Inbox Triage off only for owners whose desk
is open.

Run from the api directory (or /app inside the container):

    python scripts/provision_inbox_desks.py --dry-run
    python scripts/provision_inbox_desks.py --execute

Flags:
--dry-run  Report how many users would get a desk. Default.
--execute  Open the desks. Required to write anything.

Safely re-runnable: provisioning skips a user whose desk is open or who stopped it.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.user_integrations import user_integration_repository
from app.services.todos.inbox_desk import provision_inbox_desk


@dataclass
class BackfillResult:
    dry_run: bool
    user_ids: list[str]
    #: user_id -> the error that stopped their desk; a re-run retries them.
    failures: dict[str, str] = field(default_factory=dict)


async def run_backfill(*, dry_run: bool) -> BackfillResult:
    gmail_users = set(
        await user_integration_repository.user_ids_with_integration(GMAIL_INTEGRATION_ID)
    )
    paying = [
        user_id
        for user_id in await subscription_repository.active_user_ids()
        if user_id in gmail_users
    ]
    result = BackfillResult(dry_run=dry_run, user_ids=paying)
    if dry_run:
        return result

    for user_id in paying:
        try:
            await provision_inbox_desk(user_id)
        except Exception as e:
            # One user's failure must not end the run for everyone behind them; it is
            # reported, and a re-run retries them.
            result.failures[user_id] = f"{type(e).__name__}: {e}"
    return result


def _render(result: BackfillResult) -> None:
    mode = "DRY RUN, nothing was written" if result.dry_run else "EXECUTED"
    print(f"\n{mode}")
    print(f"paying users with Gmail:  {len(result.user_ids)}")
    if result.dry_run:
        return
    print(f"provisioned:              {len(result.user_ids) - len(result.failures)}")
    if result.failures:
        print(f"failed (re-run retries):  {len(result.failures)}")
        for user_id, error in result.failures.items():
            print(f"  {user_id}: {error}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so an ambiguous invocation fails loud instead of guessing.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="open the desks")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args()

    result = await run_backfill(dry_run=not args.execute)
    _render(result)

    if not args.execute:
        print("\nRe-run with --execute to open these desks.")


if __name__ == "__main__":
    asyncio.run(main())
