#!/usr/bin/env python3
"""One-time cleanup: pause stored recurring schedules that break the recurring-schedule rule.

The rule (app.utils.schedule) now guards every entry point, but rows written
before it still fire: the every-minute reminder 688f55d2263a1ab3d79db728 and
the 6-field '0 6 30 * * *' that croniter reads as per-second. This pauses each
such reminder and workflow with reason INVALID_SCHEDULE. The expression is never
rewritten (the user's intent is ambiguous); the user fixes it and resumes.

It also backfills stop_after on live recurring reminders that predate the
default lifetime, so legacy rows end the way new ones do.

Invalid tracked-todo recurrences are reported only: a todo paused for its schedule
would have no path back once the user fixed it.

Run from the api directory (or /app inside the container):

    python scripts/pause_invalid_recurring_schedules.py            # dry run, prints counts
    python scripts/pause_invalid_recurring_schedules.py --apply    # writes

Safely re-runnable: a reminder already paused for INVALID_SCHEDULE, a workflow
already deactivated for it, and a reminder that already has stop_after are skipped.
"""

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from bson import ObjectId

from app.constants.reminders import REMINDER_DEFAULT_LIFETIME
from app.constants.todos import GAIA_TRACKED_LABEL, TODO_RECURRENCE_SHORTCUTS
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.reminders import reminder_repository
from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason, ScheduledTaskStatus
from app.models.workflow_models import TriggerType
from app.utils.schedule import schedule_rejection

#: Reminder states that still fire, or can be resumed into firing.
LIVE_REMINDER_STATUSES = [
    ScheduledTaskStatus.SCHEDULED.value,
    ScheduledTaskStatus.EXECUTING.value,
    ScheduledTaskStatus.PAUSED.value,
]


@dataclass(frozen=True)
class InvalidSchedule:
    """One stored schedule that breaks the rule."""

    id: str
    user_id: str
    expression: str
    reason: str


@dataclass
class CleanupPlan:
    """Everything the cleanup would write, computed before the first write."""

    reminders_to_pause: list[InvalidSchedule] = field(default_factory=list)
    workflows_to_pause: list[InvalidSchedule] = field(default_factory=list)
    stop_after_backfill: dict[str, datetime] = field(default_factory=dict)
    invalid_todos: list[InvalidSchedule] = field(default_factory=list)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _invalid(doc: dict[str, Any], expression: str) -> InvalidSchedule | None:
    rejection = schedule_rejection(expression)
    if rejection is None:
        return None
    return InvalidSchedule(str(doc["_id"]), str(doc.get("user_id")), expression, rejection.value)


def plan_reminder(doc: dict[str, Any], now: datetime, plan: CleanupPlan) -> None:
    """Add one live recurring reminder's pause and stop_after backfill to plan."""
    invalid = _invalid(doc, doc["repeat"])
    already_paused = (
        doc.get("status") == ScheduledTaskStatus.PAUSED.value
        and doc.get("pause_reason") == DeactivationReason.INVALID_SCHEDULE.value
    )
    if invalid and not already_paused:
        plan.reminders_to_pause.append(invalid)
    if doc.get("stop_after") is None:
        lifetime_end = _as_utc(doc.get("created_at") or now) + REMINDER_DEFAULT_LIFETIME
        plan.stop_after_backfill[str(doc["_id"])] = (
            lifetime_end if lifetime_end > now else now + REMINDER_DEFAULT_LIFETIME
        )


def plan_workflow(doc: dict[str, Any], plan: CleanupPlan) -> None:
    """Add one scheduled workflow to plan when its cron breaks the rule."""
    if doc.get("deactivated_reason") == DeactivationReason.INVALID_SCHEDULE.value:
        return
    invalid = _invalid(doc, doc["trigger_config"]["cron_expression"])
    if invalid:
        plan.workflows_to_pause.append(invalid)


def plan_todo(doc: dict[str, Any], plan: CleanupPlan) -> None:
    """Report one tracked todo whose recurrence is neither a shortcut nor an acceptable schedule."""
    recurrence = doc["recurrence"]
    if recurrence in TODO_RECURRENCE_SHORTCUTS:
        return
    invalid = _invalid(doc, recurrence)
    if invalid:
        plan.invalid_todos.append(invalid)


async def build_plan(now: datetime) -> CleanupPlan:
    """Scan reminders, workflows and todos without writing anything."""
    plan = CleanupPlan()
    reminders = get_async_collection("reminders").find(
        {"repeat": {"$nin": [None, ""]}, "status": {"$in": LIVE_REMINDER_STATUSES}}
    )
    async for doc in reminders:
        plan_reminder(doc, now, plan)
    workflows = get_async_collection("workflows").find(
        {
            "trigger_config.type": TriggerType.SCHEDULE.value,
            "trigger_config.cron_expression": {"$nin": [None, ""]},
        }
    )
    async for doc in workflows:
        plan_workflow(doc, plan)
    # Only a tracked todo's recurrence schedules runs; a plain todo's is display-only (an RRULE).
    todos = get_async_collection("todos").find(
        {"recurrence": {"$nin": [None, ""]}, "labels": GAIA_TRACKED_LABEL}
    )
    async for doc in todos:
        plan_todo(doc, plan)
    return plan


async def apply_plan(plan: CleanupPlan) -> None:
    """Write the pauses and the stop_after backfill through the canonical repositories."""
    for reminder in plan.reminders_to_pause:
        await reminder_repository.set_status(
            reminder.id,
            ScheduledTaskStatus.PAUSED,
            pause_reason=DeactivationReason.INVALID_SCHEDULE,
        )
    for workflow in plan.workflows_to_pause:
        await workflow_repository.deactivate(
            workflow.id, workflow.user_id, reason=DeactivationReason.INVALID_SCHEDULE
        )
    reminders = get_async_collection("reminders")
    for reminder_id, stop_after in plan.stop_after_backfill.items():
        await reminders.update_one(
            {"_id": ObjectId(reminder_id), "stop_after": None}, {"$set": {"stop_after": stop_after}}
        )


def _render(plan: CleanupPlan, *, applied: bool) -> None:
    print("\nAPPLIED" if applied else "\nDRY RUN — nothing was written")
    print(f"reminders to pause (invalid schedule):  {len(plan.reminders_to_pause)}")
    print(f"workflows to pause (invalid schedule):  {len(plan.workflows_to_pause)}")
    print(f"recurring reminders given stop_after:   {len(plan.stop_after_backfill)}")
    print(f"tracked todos with invalid recurrence:  {len(plan.invalid_todos)} (report only)")
    for kind, rows in (
        ("reminder", plan.reminders_to_pause),
        ("workflow", plan.workflows_to_pause),
        ("todo", plan.invalid_todos),
    ):
        for row in rows:
            print(f"  {kind:<9}{row.id:<28}{row.reason:<20}{row.expression!r}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the pauses and backfill")
    args = parser.parse_args()

    plan = await build_plan(datetime.now(UTC))
    if args.apply:
        await apply_plan(plan)
    _render(plan, applied=args.apply)
    if not args.apply:
        print("\nRe-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
