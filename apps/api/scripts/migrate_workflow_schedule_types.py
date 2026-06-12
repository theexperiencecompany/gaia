"""
One-time, idempotent migration: repair workflow + reminder scheduling state.

Two defects left existing documents stuck:

1. ``scheduled_at`` / ``stop_after`` / ``trigger_config.next_run`` (and the audit
   fields ``created_at`` / ``updated_at``) were persisted as ISO **strings** instead
   of native datetimes. The scheduler selects due work with
   ``scheduled_at: {"$lte": now}``, which never matches a string — so those tasks are
   invisible to the recovery scan — and date-range/sort queries on the audit fields
   behave inconsistently across the mixed string/date population.
2. The workflow executor never re-armed recurrence, so a recurring workflow fired
   once and then sat at a stale ``scheduled_at`` forever.

For workflows this script converts the scheduling/audit timestamps to datetimes and,
for every active recurring workflow, recomputes the next *future* run, marks it
scheduled, and enqueues it in ARQ. It advances from now (never replays missed runs)
and honours ``max_occurrences`` / ``stop_after``. Cancelled, paused and one-time
workflows are left untouched.

For reminders it converts the same string timestamps to datetimes. A reminder whose
``scheduled_at`` lands in the past once it is a native datetime would be fired
immediately by the startup recovery scan (``status=scheduled`` + ``scheduled_at <=
now``) — replaying a long-missed reminder at the user. The scheduler's own policy is to
advance from now and never replay a missed run, so this migration settles overdue
reminders the same way: a one-time overdue reminder is marked ``completed`` and a
recurring overdue reminder is re-armed to its next *future* occurrence (and re-enqueued
in ARQ), honouring ``max_occurrences`` / ``stop_after``. Future-dated reminders are only
type-fixed and left scheduled, so a legitimately upcoming reminder still fires.

Idempotent: re-running recomputes a future run and the deterministic ARQ job id dedupes
the enqueue, so it is safe to run repeatedly.

Run from repo root (dry run prints what would change):
    cd apps/api && uv run python scripts/migrate_workflow_schedule_types.py
Apply the changes:
    cd apps/api && uv run python scripts/migrate_workflow_schedule_types.py --apply
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import (  # noqa: E402
    reminders_collection,
    workflows_collection,
)
from app.models.scheduler_models import ScheduledTaskStatus  # noqa: E402
from app.services.reminder_service import ReminderScheduler  # noqa: E402
from app.services.workflow.scheduler import WorkflowScheduler  # noqa: E402
from app.utils.cron_utils import get_next_run_time  # noqa: E402

# Scheduling + audit datetimes that were historically persisted as ISO strings.
_DATE_FIELDS = ("scheduled_at", "stop_after", "created_at", "updated_at")


def _to_datetime(value: object) -> datetime | None:
    """Coerce an ISO string (or existing datetime) to a UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _build_type_fixes(doc: dict) -> dict:
    """$set payload that converts string-typed datetime fields to datetimes.

    Covers the top-level scheduling/audit fields and (for workflows) the nested
    ``trigger_config.next_run``. The nested field is only set when ``trigger_config``
    is an object, so a missing/null ``trigger_config`` is never turned into a malformed
    subdocument (``TriggerConfig.type`` is required).
    """
    fixes: dict[str, datetime] = {}
    for field in _DATE_FIELDS:
        if isinstance(doc.get(field), str):
            coerced = _to_datetime(doc[field])
            if coerced is not None:
                fixes[field] = coerced

    trigger_config = doc.get("trigger_config")
    if isinstance(trigger_config, dict) and isinstance(trigger_config.get("next_run"), str):
        coerced = _to_datetime(trigger_config["next_run"])
        if coerced is not None:
            fixes["trigger_config.next_run"] = coerced
    return fixes


def _plan_reminder_recovery(
    doc: dict, now: datetime
) -> tuple[dict[str, object], str, datetime | None] | None:
    """Decide how to stop an overdue reminder from replaying on the next scan.

    Returns ``(set_fields, outcome, enqueue_at)`` where outcome is ``"settled"`` or
    ``"rearmed"``, or ``None`` when the reminder is future-dated or not in the resting
    scheduled state (type-fix only — leave its run-state alone). A re-armed reminder
    carries ``enqueue_at`` so the caller re-adds its deferred ARQ job; the startup scan
    only re-enqueues overdue tasks, so a future-armed reminder would otherwise be
    orphaned once its original (long-expired) job is gone.
    """
    if doc.get("status") != ScheduledTaskStatus.SCHEDULED.value:
        return None
    scheduled_at = _to_datetime(doc.get("scheduled_at"))
    if scheduled_at is None or scheduled_at > now:
        return None

    if not doc.get("repeat"):
        return ({"status": ScheduledTaskStatus.COMPLETED.value}, "settled", None)

    # Reminders carry no per-task timezone; recurrence is computed in UTC, matching
    # ReminderScheduler's runtime path (handle_recurring_task passes timezone=None).
    next_run = get_next_run_time(doc["repeat"], now, None)
    if next_run is None or _recurrence_limit_reached(doc, next_run):
        return ({"status": ScheduledTaskStatus.COMPLETED.value}, "settled", None)

    return (
        {"scheduled_at": next_run, "status": ScheduledTaskStatus.SCHEDULED.value},
        "rearmed",
        next_run,
    )


async def _migrate_reminders(
    scheduler: ReminderScheduler, now: datetime, apply: bool
) -> dict[str, int]:
    """Type-repair reminder datetimes, then settle/re-arm any overdue reminder so the
    startup recovery scan never replays a long-missed fire."""
    counts = {"type_fixed": 0, "rearmed": 0, "settled": 0}
    async for doc in reminders_collection.find({}):
        set_fields: dict[str, object] = dict(_build_type_fixes(doc))
        if set_fields:
            counts["type_fixed"] += 1

        plan = _plan_reminder_recovery(doc, now)
        enqueue_at: datetime | None = None
        if plan is not None:
            delta, outcome, enqueue_at = plan
            set_fields.update(delta)
            counts[outcome] += 1
            print(f"  reminder {doc.get('_id')}: {outcome} {sorted(delta)}")
        elif set_fields:
            print(f"  reminder {doc.get('_id')}: type-fix {sorted(set_fields)}")

        if not set_fields:
            continue
        if apply:
            if plan is not None:
                set_fields["updated_at"] = now
            await reminders_collection.update_one({"_id": doc["_id"]}, {"$set": set_fields})
            if enqueue_at is not None:
                await scheduler.reschedule_task(str(doc["_id"]), enqueue_at)
    return counts


async def _apply_type_fixes(doc: dict, apply: bool) -> bool:
    """Type-repair the scheduling + audit timestamps. Returns True if any fixed."""
    fixes = _build_type_fixes(doc)
    if not fixes:
        return False
    print(f"  {doc.get('_id')}: type-fix {sorted(fixes)}")
    if apply:
        await workflows_collection.update_one({"_id": doc.get("_id")}, {"$set": fixes})
    return True


def _is_active_recurring(doc: dict) -> bool:
    return bool(
        doc.get("repeat")
        and doc.get("activated", False)
        and doc.get("status") == ScheduledTaskStatus.SCHEDULED.value
    )


def _recurrence_limit_reached(doc: dict, next_run: datetime) -> bool:
    occurrence_count = doc.get("occurrence_count") or 0
    max_occurrences = doc.get("max_occurrences")
    stop_after = _to_datetime(doc.get("stop_after"))
    return bool(max_occurrences and occurrence_count >= max_occurrences) or bool(
        stop_after and next_run >= stop_after
    )


async def _rearm_workflow(
    doc: dict, scheduler: WorkflowScheduler, now: datetime, apply: bool
) -> str:
    """Re-arm one active recurring workflow. Returns 'completed' or 'rearmed'."""
    workflow_id = doc.get("_id")
    timezone = (doc.get("trigger_config") or {}).get("timezone") or "UTC"
    next_run = get_next_run_time(doc["repeat"], now, timezone)

    if next_run is None:
        # Invalid cron or no future occurrence left -> nothing more to fire.
        print(f"  {workflow_id}: no future run -> completed")
        if apply:
            await workflows_collection.update_one(
                {"_id": workflow_id},
                {"$set": {"status": ScheduledTaskStatus.COMPLETED.value}},
            )
        return "completed"

    if _recurrence_limit_reached(doc, next_run):
        print(f"  {workflow_id}: limit reached -> completed")
        if apply:
            await workflows_collection.update_one(
                {"_id": workflow_id},
                {"$set": {"status": ScheduledTaskStatus.COMPLETED.value}},
            )
        return "completed"

    print(f"  {workflow_id}: re-arm -> {next_run.isoformat()}")
    if apply:
        set_fields: dict[str, datetime | str] = {
            "scheduled_at": next_run,
            "status": ScheduledTaskStatus.SCHEDULED.value,
            "updated_at": now,
        }
        # Only touch the nested field when the parent object exists, so a
        # missing/null trigger_config is never auto-created as a malformed
        # subdocument.
        if isinstance(doc.get("trigger_config"), dict):
            set_fields["trigger_config.next_run"] = next_run
        await workflows_collection.update_one({"_id": workflow_id}, {"$set": set_fields})
        await scheduler.reschedule_task(str(workflow_id), next_run)
    return "rearmed"


async def migrate(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Repairing workflow + reminder scheduling state...\n")

    scheduler = WorkflowScheduler()
    reminder_scheduler = ReminderScheduler()
    if apply:
        await scheduler.initialize()
        await reminder_scheduler.initialize()

    counts = {"type_fixed": 0, "rearmed": 0, "completed": 0, "skipped": 0}
    reminder_counts = {"type_fixed": 0, "rearmed": 0, "settled": 0}

    try:
        async for doc in workflows_collection.find({}):
            now = datetime.now(UTC)
            if await _apply_type_fixes(doc, apply):
                counts["type_fixed"] += 1

            if not _is_active_recurring(doc):
                counts["skipped"] += 1
                continue

            outcome = await _rearm_workflow(doc, scheduler, now, apply)
            counts[outcome] += 1

        # 3. Type repair + settle/re-arm for reminders (same string->datetime defect;
        #    overdue reminders are settled/re-armed so the scan never replays them).
        reminder_counts = await _migrate_reminders(reminder_scheduler, datetime.now(UTC), apply)
    finally:
        if apply:
            await scheduler.close()
            await reminder_scheduler.close()

    print(
        f"\n[{mode}] Done. workflow type-fixed={counts['type_fixed']} "
        f"re-armed={counts['rearmed']} completed={counts['completed']} "
        f"skipped={counts['skipped']} | reminder type-fixed={reminder_counts['type_fixed']} "
        f"re-armed={reminder_counts['rearmed']} settled={reminder_counts['settled']}"
    )
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
