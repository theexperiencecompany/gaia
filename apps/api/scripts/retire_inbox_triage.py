#!/usr/bin/env python3
"""One-time migration: retire Inbox Triage in favour of the Inbox desk.

Inbox Triage was the gmail:email_intelligence system workflow. Its definition is
gone, but every stored row still fires each morning from its saved prompt, so its
owner would get two briefings: Inbox Triage's and the Inbox desk's.

For each row that still runs, or that GAIA paused and a resume path could turn back
on, this first opens the owner's Inbox desk through provision_inbox_desk (which skips
users without a plan or Gmail, and never revives a desk the user stopped), then
switches the row off the way a user would, so nothing resumes it.

Run from the api directory (or /app inside the container):

    python scripts/retire_inbox_triage.py --dry-run
    python scripts/retire_inbox_triage.py --execute

Flags:
--dry-run  Report the rows that would be retired. Default.
--execute  Open the desks and retire the rows. Required to write anything.
--limit N  Only list the first N rows in the report (the totals stay complete).

Safely re-runnable: a retired row no longer matches, and provisioning is idempotent.
A row whose owner's desk could not be opened stays live, so a re-run retries it.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.workflow_models import WorkflowDocument
from app.services.todos.inbox_desk import INBOX_DESK_REF, provision_inbox_desk
from app.services.workflow.service import WorkflowService

INBOX_TRIAGE_KEY = "gmail:email_intelligence"


@dataclass
class MigrationResult:
    dry_run: bool
    workflows: list[WorkflowDocument]
    retired: int = 0
    #: Owners who have an open Inbox desk once their row was retired.
    desks_open: int = 0
    #: user_id -> the error that stopped their row; a re-run retries any row still live.
    failures: dict[str, str] = field(default_factory=dict)


async def run_migration(*, dry_run: bool) -> MigrationResult:
    workflows = await workflow_repository.find_live_system_workflows(INBOX_TRIAGE_KEY)
    result = MigrationResult(dry_run=dry_run, workflows=workflows)
    if dry_run:
        return result

    for workflow in workflows:
        try:
            await _retire(workflow, result)
        except Exception as e:
            # One user's failure must not end the run for everyone behind them; it is
            # reported, and a re-run retries any row still live.
            result.failures[workflow.user_id] = f"{type(e).__name__}: {e}"
    return result


async def _retire(workflow: WorkflowDocument, result: MigrationResult) -> None:
    """Open the owner's desk, then switch their row off, so nobody is left with neither."""
    await provision_inbox_desk(workflow.user_id)
    await WorkflowService.deactivate_workflow(workflow.id, workflow.user_id)
    result.retired += 1
    desk = await todo_repository.find_latest_by_external_ref(workflow.user_id, INBOX_DESK_REF)
    if desk is not None and not desk.completed:
        result.desks_open += 1


def _render(result: MigrationResult, limit: int) -> None:
    mode = "DRY RUN — nothing was written" if result.dry_run else "EXECUTED"
    print(f"\n{mode}")
    print(f"live Inbox Triage workflows:   {len(result.workflows)}")
    if not result.dry_run:
        print(f"retired:                       {result.retired}")
        print(f"owners with an open desk:      {result.desks_open}")
        if result.failures:
            print(f"failed (re-run retries):       {len(result.failures)}")
            for user_id, error in result.failures.items():
                print(f"  {user_id}: {error}")

    if not result.workflows:
        print("\nNothing to do.")
        return

    print(f"\n{'workflow_id':<44}{'user_id':<28}{'state'}")
    for workflow in result.workflows[:limit]:
        state = "running" if workflow.activated else "paused by GAIA"
        print(f"{workflow.id:<44}{workflow.user_id:<28}{state}")
    if len(result.workflows) > limit:
        print(f"... and {len(result.workflows) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so an ambiguous invocation fails loud instead of guessing:
    # this script switches off other people's automation.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="open the desks and retire the rows")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--limit", type=int, default=25, help="rows to list in the report")
    args = parser.parse_args()

    result = await run_migration(dry_run=not args.execute)
    _render(result, args.limit)

    if not args.execute:
        print("\nRe-run with --execute to open the desks and retire these workflows.")


if __name__ == "__main__":
    asyncio.run(main())
