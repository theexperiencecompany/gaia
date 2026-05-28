"""
One-time, idempotent migration: repair workflow scheduling state.

Two defects left existing workflows stuck:

1. ``scheduled_at`` / ``stop_after`` / ``trigger_config.next_run`` were persisted as
   ISO **strings** instead of native datetimes. The scheduler selects due work with
   ``scheduled_at: {"$lte": now}``, which never matches a string — so those workflows
   are invisible to the recovery scan.
2. The executor never re-armed recurrence, so a recurring workflow fired once and then
   sat at a stale ``scheduled_at`` forever.

This script converts the scheduling timestamps to datetimes and, for every active
recurring workflow, recomputes the next *future* run, marks it scheduled, and enqueues
it in ARQ. It advances from now (never replays missed runs) and honours
``max_occurrences`` / ``stop_after``. Cancelled, paused and one-time workflows are left
untouched.

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

from app.db.mongodb.collections import workflows_collection  # noqa: E402
from app.models.scheduler_models import ScheduledTaskStatus  # noqa: E402
from app.services.workflow.scheduler import WorkflowScheduler  # noqa: E402
from app.utils.cron_utils import get_next_run_time  # noqa: E402

_DATE_FIELDS = ("scheduled_at", "stop_after")


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
    """$set payload that converts string-typed scheduling fields to datetimes."""
    fixes: dict[str, datetime] = {}
    for field in _DATE_FIELDS:
        if isinstance(doc.get(field), str):
            coerced = _to_datetime(doc[field])
            if coerced is not None:
                fixes[field] = coerced

    trigger_config = doc.get("trigger_config") or {}
    if isinstance(trigger_config.get("next_run"), str):
        coerced = _to_datetime(trigger_config["next_run"])
        if coerced is not None:
            fixes["trigger_config.next_run"] = coerced
    return fixes


async def migrate(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Repairing workflow scheduling state...\n")

    scheduler = WorkflowScheduler()
    if apply:
        await scheduler.initialize()

    type_fixed = 0
    rearmed = 0
    completed = 0
    skipped = 0

    try:
        async for doc in workflows_collection.find({}):
            workflow_id = doc.get("_id")
            now = datetime.now(UTC)

            # 1. Type repair for the scheduling timestamps.
            fixes = _build_type_fixes(doc)
            if fixes:
                type_fixed += 1
                print(f"  {workflow_id}: type-fix {sorted(fixes)}")
                if apply:
                    await workflows_collection.update_one({"_id": workflow_id}, {"$set": fixes})

            # 2. Re-arm active recurring workflows.
            repeat = doc.get("repeat")
            activated = doc.get("activated", False)
            status = doc.get("status")
            if not repeat or not activated or status != ScheduledTaskStatus.SCHEDULED.value:
                skipped += 1
                continue

            timezone = (doc.get("trigger_config") or {}).get("timezone") or "UTC"
            next_run = get_next_run_time(repeat, now, timezone)

            occurrence_count = doc.get("occurrence_count") or 0
            max_occurrences = doc.get("max_occurrences")
            stop_after = _to_datetime(doc.get("stop_after"))

            if (max_occurrences and occurrence_count >= max_occurrences) or (
                stop_after and next_run >= stop_after
            ):
                completed += 1
                print(f"  {workflow_id}: limit reached -> completed")
                if apply:
                    await workflows_collection.update_one(
                        {"_id": workflow_id},
                        {"$set": {"status": ScheduledTaskStatus.COMPLETED.value}},
                    )
                continue

            rearmed += 1
            print(f"  {workflow_id}: re-arm -> {next_run.isoformat()}")
            if apply:
                await workflows_collection.update_one(
                    {"_id": workflow_id},
                    {
                        "$set": {
                            "scheduled_at": next_run,
                            "trigger_config.next_run": next_run,
                            "status": ScheduledTaskStatus.SCHEDULED.value,
                            "updated_at": now,
                        }
                    },
                )
                await scheduler.reschedule_task(str(workflow_id), next_run)
    finally:
        if apply:
            await scheduler.close()

    print(
        f"\n[{mode}] Done. type-fixed={type_fixed} re-armed={rearmed} "
        f"completed={completed} skipped={skipped}"
    )
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
