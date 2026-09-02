#!/usr/bin/env python3
"""One-time migration: deactivate workflows for users without an active Pro subscription.

GAIA is going paid-only — automation (workflows) is a Pro feature going forward.
This is the backfill for the cutover: every user who already has an activated
workflow but no active Dodo subscription gets those workflows turned off, the
same way the webhook handler now does it live for a subscription that lapses.

Goes through the same ``deactivate_workflows_for_lapsed_subscription`` service
function as the webhook path, so triggers are unregistered upstream exactly
like a real cancellation — not a bulk repository write that would leave a
Composio webhook armed.

Run from the api directory (or /app inside the container):

    python scripts/deactivate_workflows_for_free_users.py --dry-run
    python scripts/deactivate_workflows_for_free_users.py --execute

Flags:
--dry-run  Report the free users and the workflows that would be deactivated. Default.
--execute  Actually deactivate them. Required to write anything.
--limit N  Only show the first N users in the report (the totals stay complete).

Safely re-runnable: a user who is re-checked after their workflows were already
deactivated (or who has since subscribed) is simply skipped.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.workflows import workflow_repository
from app.services.workflow.subscription_pause import (
    deactivate_workflows_for_lapsed_subscription,
)


@dataclass
class FreeUserWorkflows:
    """One free user and the activated workflows they own."""

    user_id: str
    workflow_ids: list[str] = field(default_factory=list)


@dataclass
class MigrationResult:
    dry_run: bool
    free_users: list[FreeUserWorkflows]
    workflows_deactivated: int = 0


async def find_free_user_candidates() -> list[FreeUserWorkflows]:
    """Every user with at least one activated workflow but no active subscription."""
    candidates: list[FreeUserWorkflows] = []

    for user_id in await workflow_repository.distinct_users_with_activated_workflows():
        if await subscription_repository.get_active_for_user(user_id):
            continue
        workflows = await workflow_repository.find_activated_for_user(user_id)
        if not workflows:
            continue
        candidates.append(
            FreeUserWorkflows(user_id=user_id, workflow_ids=[w.id for w in workflows])
        )

    return candidates


async def run_migration(*, dry_run: bool) -> MigrationResult:
    candidates = await find_free_user_candidates()
    deactivated = 0

    if not dry_run:
        for candidate in candidates:
            deactivated += await deactivate_workflows_for_lapsed_subscription(candidate.user_id)

    return MigrationResult(
        dry_run=dry_run, free_users=candidates, workflows_deactivated=deactivated
    )


def _render(result: MigrationResult, limit: int) -> None:
    mode = "DRY RUN — nothing was written" if result.dry_run else "EXECUTED"
    print(f"\n{mode}")
    print(f"free users with activated workflows: {len(result.free_users)}")
    total_workflows = sum(len(c.workflow_ids) for c in result.free_users)
    print(f"workflows in scope:                  {total_workflows}")
    if not result.dry_run:
        print(f"workflows deactivated:               {result.workflows_deactivated}")

    if not result.free_users:
        print("\nNothing to do.")
        return

    print(f"\n{'user_id':<28}{'workflows':>10}")
    for candidate in result.free_users[:limit]:
        print(f"{candidate.user_id:<28}{len(candidate.workflow_ids):>10}")
    if len(result.free_users) > limit:
        print(f"... and {len(result.free_users) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so `--execute --dry-run` is rejected by argparse instead
    # of silently doing one or the other — this script deactivates other people's
    # automation, so an ambiguous invocation should fail loud, not guess.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="actually deactivate the workflows")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--limit", type=int, default=25, help="users to list in the report")
    args = parser.parse_args()

    result = await run_migration(dry_run=not args.execute)
    _render(result, args.limit)

    if not args.execute:
        print("\nRe-run with --execute to deactivate these workflows.")


if __name__ == "__main__":
    asyncio.run(main())
