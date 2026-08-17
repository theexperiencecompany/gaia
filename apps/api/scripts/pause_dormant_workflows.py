#!/usr/bin/env python3
"""Pause (or preview) the workflows of users who have gone dormant.

The manual companion to the daily ``sweep_dormant_user_workflows`` cron — for
running the backlog once, on demand, and seeing exactly who it would touch
before anything is written.

Dormancy is judged across every signal (web login, chat activity, metered
feature use), so a user who only ever talks to GAIA through a bot is not
mistaken for an abandoned account.

Run from the api directory (or /app inside the container):

    python scripts/pause_dormant_workflows.py --dry-run
    python scripts/pause_dormant_workflows.py --days 60 --dry-run
    python scripts/pause_dormant_workflows.py --apply

Flags:
--dry-run  Report the cohort and the workflows that would be paused. Default.
--apply    Actually pause them. Required to write anything.
--days N   Dormancy threshold in days (default: the service's own threshold).
--limit N  Only show the first N users in the report (the totals stay complete).
"""

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.workflow.dormancy import (
    DORMANCY_THRESHOLD,
    DormancySweepResult,
    sweep_dormant_workflows,
)


def _render(result: DormancySweepResult, limit: int) -> None:
    mode = "DRY RUN — nothing was written" if result.dry_run else "APPLIED"
    print(f"\n{mode}")
    print(f"cutoff (dormant since before): {result.cutoff.isoformat()}")
    print(f"dormant users with workflows:  {result.dormant_users}")
    total = sum(len(c.workflow_ids) for c in result.candidates)
    print(f"workflows in scope:            {total}")
    if not result.dry_run:
        print(f"workflows paused:              {result.workflows_paused}")
        print(f"failures:                      {result.failures}")

    if not result.candidates:
        print("\nNothing to do.")
        return

    # The stamp is the WEB LOGIN one specifically; chat and metered activity were
    # already checked to get here, so "never" here does not mean "never used GAIA".
    print(f"\n{'user_id':<28}{'last web login':<28}{'workflows':>10}")
    for candidate in result.candidates[:limit]:
        last_active = candidate.last_active_at.isoformat() if candidate.last_active_at else "never"
        print(f"{candidate.user_id:<28}{last_active:<28}{len(candidate.workflow_ids):>10}")
    if len(result.candidates) > limit:
        print(f"... and {len(result.candidates) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so `--apply --dry-run` is rejected by argparse instead of
    # silently applying: --dry-run was parsed but never read, and the mode came
    # from `not args.apply` alone. On a script that deactivates other people's
    # automation, "I passed --dry-run and it wrote" is the wrong way to find out.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="actually pause the workflows")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--days", type=int, default=None, help="dormancy threshold in days")
    parser.add_argument("--limit", type=int, default=25, help="users to list in the report")
    parser.add_argument(
        "--max-users",
        type=int,
        default=None,
        help="stop after this many dormant users (batch a large first run)",
    )
    args = parser.parse_args()

    # `--days 0` would put the cutoff at this instant, so every prior activity
    # timestamp falls before it and every user reads as dormant. The service
    # raises on this too; rejecting here turns it into a usage error rather than
    # a traceback. Same for a negative value, which puts the cutoff in the future.
    if args.days is not None and args.days <= 0:
        parser.error(f"--days must be positive, got {args.days}")
    if args.max_users is not None and args.max_users <= 0:
        parser.error(f"--max-users must be positive, got {args.max_users}")

    threshold = timedelta(days=args.days) if args.days is not None else DORMANCY_THRESHOLD
    print(f"Dormancy threshold: {threshold.days} days")

    result = await sweep_dormant_workflows(
        threshold=threshold, dry_run=not args.apply, max_users=args.max_users
    )
    _render(result, args.limit)

    if not args.apply:
        print("\nRe-run with --apply to pause these workflows.")


if __name__ == "__main__":
    asyncio.run(main())
