#!/usr/bin/env python3
"""Archive the todos and workflows that were saved for "system", the template owner.

"system" owns templates only (system skills, explore workflows). Four tracked
todos and their four "Todo: ..." workflows were saved for it by an agent run,
and the worker ran them as a fabricated user every hour. This archives them
through the same services a user's own archive uses, so schedules and trigger
subscriptions are torn down, and then reports every other row still owned by
"system" (templates excluded) without touching it.

Run from the api directory (or /app inside the container):

    python scripts/archive_system_owned_runs.py           # report only (default)
    python scripts/archive_system_owned_runs.py --apply   # archive the 4 + 4
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
import sys
import traceback

from bson import ObjectId

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.vfs import SYSTEM_USER_ID
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.models.todo_models import TodoUpdate
from app.models.workflow_models import DeactivationReason
from app.services.tracked_todo_service import tracked_todo_service
from app.services.workflow.service import WorkflowService

SYSTEM_OWNED_TODO_IDS = (
    "6a387b78347776fca38bbd37",
    "6a39daa605b9d11d9e4340d5",
    "6a39e8e86bfc550f72eb77a5",
    "6a752e411130bc70d6536d29",
)
SYSTEM_OWNED_WORKFLOW_IDS = (
    "wf_dccaf3effd38",
    "wf_3d1394036869",
    "wf_8d5c09bdb286",
    "wf_200a113c7cc6",
)
ARCHIVE_SUMMARY = "Auto-archived: owned by the template owner, not a GAIA user"

#: Collections whose rows carry a user_id, read off the repositories and indexes.
#: skills is left out: system skills are the template owner's legitimate rows.
USER_OWNED_COLLECTIONS = (
    "approval_ledger",
    "bot_sessions",
    "browser_profiles",
    "browser_tasks",
    "calendar",
    "checkout_sessions",
    "conversations",
    "device_tokens",
    "e2b_sandboxes",
    "files",
    "hil_approvals",
    "integration_instructions",
    "llm_calls",
    "mail",
    "notes",
    "notifications",
    "pending_platform_registrations",
    "playbooks",
    "projects",
    "reminders",
    "subscriptions",
    "support_requests",
    "todos",
    "usage_daily",
    "usage_snapshots",
    "user_integrations",
    "workflow_executions",
    "workflows",
)


@dataclass(frozen=True)
class TargetState:
    """One targeted row as found: missing, already archived, or still live."""

    id: str
    found: bool
    archived: bool
    detail: str


@dataclass(frozen=True)
class ArchiveReport:
    """The targets as read back, the other system rows, and every target that failed to archive."""

    todos: list[TargetState]
    workflows: list[TargetState]
    others: dict[str, int]
    failures: list[tuple[str, Exception]] = field(default_factory=list)


async def _todo_states() -> list[TargetState]:
    states = []
    for todo_id in SYSTEM_OWNED_TODO_IDS:
        doc = await todo_repository.get(todo_id, user_id=SYSTEM_USER_ID)
        if doc is None:
            states.append(TargetState(todo_id, found=False, archived=False, detail="not found"))
            continue
        detail = (
            f"{doc.title!r} recurrence={doc.recurrence} scheduled_at={doc.scheduled_at} "
            f"subscriptions={len(doc.trigger_subscriptions)}"
        )
        states.append(TargetState(todo_id, found=True, archived=doc.completed, detail=detail))
    return states


async def _workflow_states() -> list[TargetState]:
    states = []
    for workflow_id in SYSTEM_OWNED_WORKFLOW_IDS:
        doc = await workflow_repository.get_for_user(workflow_id, SYSTEM_USER_ID)
        if doc is None or doc.is_explore:
            reason = "not found" if doc is None else "an explore template: never touched"
            states.append(TargetState(workflow_id, found=False, archived=False, detail=reason))
            continue
        detail = (
            f"{doc.title!r} trigger={doc.trigger_config.type} "
            f"composio_triggers={len(doc.trigger_config.composio_trigger_ids or [])}"
        )
        states.append(
            TargetState(workflow_id, found=True, archived=not doc.activated, detail=detail)
        )
    return states


async def _archive_todo(todo_id: str) -> None:
    await todo_repository.update(
        todo_id, user_id=SYSTEM_USER_ID, update=TodoUpdate(scheduled_at=None)
    )
    # Completing a tracked todo is its archive, and tears down its trigger subscriptions.
    await tracked_todo_service.complete_tracked_todo(todo_id, SYSTEM_USER_ID, ARCHIVE_SUMMARY)


async def _archive_workflow(workflow_id: str) -> None:
    await WorkflowService.deactivate_workflow(
        workflow_id, SYSTEM_USER_ID, reason=DeactivationReason.OWNER_NOT_FOUND
    )


async def other_system_rows() -> dict[str, int]:
    """Count rows still owned by "system" per collection, past the targets and the templates."""
    counts: dict[str, int] = {}
    for name in USER_OWNED_COLLECTIONS:
        query: dict[str, object] = {"user_id": SYSTEM_USER_ID}
        if name == "todos":
            query["_id"] = {"$nin": [ObjectId(todo_id) for todo_id in SYSTEM_OWNED_TODO_IDS]}
        if name == "workflows":
            query["is_explore"] = {"$ne": True}
            query["_id"] = {"$nin": list(SYSTEM_OWNED_WORKFLOW_IDS)}
        counts[name] = await get_async_collection(name).count_documents(query)
    return counts


async def _archive_live(
    states: list[TargetState], archive: Callable[[str], Awaitable[None]]
) -> list[tuple[str, Exception]]:
    """Archive every live target; one that fails is recorded and the rest still run."""
    failures: list[tuple[str, Exception]] = []
    for state in states:
        if not state.found or state.archived:
            continue
        try:
            await archive(state.id)
        except Exception as e:  # reported after the read-back; the other targets must still run
            traceback.print_exc()
            failures.append((state.id, e))
    return failures


async def run(*, apply: bool) -> ArchiveReport:
    """Report the targets, archive the live ones when apply is set, then count the rest.

    After apply the targets are read back, so the report shows what was written.
    """
    todos = await _todo_states()
    workflows = await _workflow_states()
    failures: list[tuple[str, Exception]] = []
    if apply:
        failures = await _archive_live(todos, _archive_todo)
        failures += await _archive_live(workflows, _archive_workflow)
        todos = await _todo_states()
        workflows = await _workflow_states()
    return ArchiveReport(todos, workflows, await other_system_rows(), failures)


def _status(state: TargetState) -> str:
    if not state.found:
        return "skipped"
    return "archived" if state.archived else "live"


def _render(
    todos: list[TargetState],
    workflows: list[TargetState],
    others: dict[str, int],
    *,
    apply: bool,
) -> None:
    print("APPLIED: read back after writing" if apply else "DRY RUN: nothing was written")
    for label, states in (("todos", todos), ("workflows", workflows)):
        live = sum(_status(state) == "live" for state in states)
        print(f"\n{label}: {live} {'still live' if apply else 'to archive'}")
        for state in states:
            print(f"  {state.id}  [{_status(state)}]  {state.detail}")
    print(
        '\nother rows owned by "system" (reported, never changed; skills and templates excluded):'
    )
    reported = {name: count for name, count in others.items() if count}
    for name, count in reported.items():
        print(f"  {name:<32}{count:>8}")
    if not reported:
        print("  none")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="archive the targets (default: report)"
    )
    args = parser.parse_args()
    report = await run(apply=args.apply)
    _render(report.todos, report.workflows, report.others, apply=args.apply)
    if report.failures:
        raise ExceptionGroup(
            f"{len(report.failures)} target(s) could not be archived",
            [error for _, error in report.failures],
        )
    if not args.apply:
        print("\nRe-run with --apply to archive them.")


if __name__ == "__main__":
    asyncio.run(main())
