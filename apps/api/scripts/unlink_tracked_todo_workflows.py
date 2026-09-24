#!/usr/bin/env python3
"""One-time migration: detach every tracked todo from the workflow it was given.

Tracked todos now always run on the agent from their canvas, activity and
references, never through a workflow. Before that change every todo got an
auto-generated workflow ("Todo: <title>") whose playbook replay froze the run
into a fixed list of calls. Those links are dead now: this unlinks each one
and deletes the workflow when it was the one generated for that todo. A
workflow the user built and linked themselves is only unlinked, never deleted.

Run from the api directory (or /app inside the container):

    python scripts/unlink_tracked_todo_workflows.py --dry-run
    python scripts/unlink_tracked_todo_workflows.py --execute

Flags:
--dry-run  Report the links that would be removed. Default.
--execute  Actually unlink and delete. Required to write anything.
--limit N  Only show the first N todos in the report (the totals stay complete).

Safely re-runnable: an unlinked todo drops out of the scan.
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
from app.services.workflow.service import WorkflowService

PAGE_SIZE = 200


@dataclass
class LinkedTodo:
    """One tracked todo still linked to a workflow, and whether that workflow goes too."""

    todo_id: str
    user_id: str
    workflow_id: str
    deletes_workflow: bool


@dataclass
class MigrationResult:
    dry_run: bool
    linked: list[LinkedTodo] = field(default_factory=list)
    workflows_deleted: int = 0


async def find_linked_tracked_todos() -> list[LinkedTodo]:
    """Every tracked todo with a workflow_id, marking the ones whose workflow was generated for it."""
    linked: list[LinkedTodo] = []
    after_id: str | None = None
    while page := await todo_repository.list_tracked_with_workflow(
        limit=PAGE_SIZE, after_id=after_id
    ):
        for todo in page:
            workflow_id = str(todo.workflow_id)
            workflow = await workflow_repository.get_for_user(workflow_id, todo.user_id)
            generated_for_todo = (
                workflow is not None
                and workflow.is_todo_workflow
                and workflow.source_todo_id == todo.id
            )
            linked.append(
                LinkedTodo(
                    todo_id=todo.id,
                    user_id=todo.user_id,
                    workflow_id=workflow_id,
                    deletes_workflow=generated_for_todo,
                )
            )
        after_id = page[-1].id
    return linked


async def run_migration(*, dry_run: bool) -> MigrationResult:
    linked = await find_linked_tracked_todos()
    if dry_run:
        return MigrationResult(dry_run=True, linked=linked)

    deleted = 0
    for link in linked:
        # Workflow first: a failure leaves the todo still linked, so a re-run retries it.
        if link.deletes_workflow and await WorkflowService.delete_workflow(
            link.workflow_id, link.user_id
        ):
            deleted += 1
        await todo_repository.clear_workflow_id(link.todo_id, user_id=link.user_id)

    return MigrationResult(dry_run=False, linked=linked, workflows_deleted=deleted)


def _render(result: MigrationResult, limit: int) -> None:
    mode = "DRY RUN — nothing was written" if result.dry_run else "EXECUTED"
    to_delete = sum(1 for link in result.linked if link.deletes_workflow)
    print(f"\n{mode}")
    print(f"tracked todos linked to a workflow: {len(result.linked)}")
    print(f"generated workflows in scope:       {to_delete}")
    if not result.dry_run:
        print(f"workflows deleted:                  {result.workflows_deleted}")

    if not result.linked:
        print("\nNothing to do.")
        return

    print(f"\n{'todo_id':<28}{'workflow_id':<28}{'action':>8}")
    for link in result.linked[:limit]:
        action = "delete" if link.deletes_workflow else "unlink"
        print(f"{link.todo_id:<28}{link.workflow_id:<28}{action:>8}")
    if len(result.linked) > limit:
        print(f"... and {len(result.linked) - limit} more (raise --limit to see them)")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually exclusive so an ambiguous invocation fails loud instead of guessing:
    # this script deletes other people's workflows.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="actually unlink and delete")
    mode.add_argument("--dry-run", action="store_true", help="preview only (default)")
    parser.add_argument("--limit", type=int, default=25, help="todos to list in the report")
    args = parser.parse_args()

    result = await run_migration(dry_run=not args.execute)
    _render(result, args.limit)

    if not args.execute:
        print("\nRe-run with --execute to unlink these todos.")


if __name__ == "__main__":
    asyncio.run(main())
