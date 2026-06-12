"""
One-time, idempotent migration: repair workflow liveness/run-state after the
status refactor.

The refactor split two concepts that the workflow scheduler used to conflate:
- **liveness** (is this workflow on?) -> governed solely by ``activated``.
- **run-state** (is a fire in flight?) -> ``status``, now restricted for workflows to
  ``scheduled`` / ``executing`` / ``completed``.

Existing documents carry the old shape and must be normalised (workflows only -
reminders keep the full ``ScheduledTaskStatus`` vocabulary):

1. Any workflow whose ``status`` is a forbidden lifecycle value (``cancelled`` /
   ``failed`` / ``paused``) or a leftover ``executing`` (a fire that never re-armed)
   is reset to ``scheduled`` - the resting run-state. This is what un-wedges the
   ``status=cancelled`` + ``activated=True`` rows the original bug produced.
2. For every active recurring workflow (``activated`` + ``repeat``), the next *future*
   run is recomputed, ``scheduled_at`` / ``trigger_config.next_run`` are advanced, and
   the job is enqueued in ARQ so it resumes. ``max_occurrences`` / ``stop_after`` are
   honoured (-> ``completed``).
3. ``trigger_config.enabled`` is synced to ``activated`` on every workflow (the two
   are now a single liveness concept).

Run with the ARQ worker stopped (so no legitimate ``executing`` fire is in flight).
Idempotent: re-running recomputes a future run and the deterministic ARQ job id
dedupes the enqueue, so it is safe to run repeatedly.

Run from repo root (dry run prints what would change):
    cd apps/api && uv run python scripts/migrate_workflow_status_liveness.py
Apply the changes:
    cd apps/api && uv run python scripts/migrate_workflow_status_liveness.py --apply
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

# Run-states a workflow may legitimately hold after the refactor. Anything else is a
# leftover from the old conflated model and gets normalised to SCHEDULED.
_ALLOWED = {
    ScheduledTaskStatus.SCHEDULED.value,
    ScheduledTaskStatus.COMPLETED.value,
}


def _to_datetime(value: object) -> datetime | None:
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


def _normalise_status(doc: dict, set_fields: dict[str, object], counts: dict[str, int]) -> None:
    """Reset any non-allowed status back to the resting run-state."""
    status = doc.get("status")
    if status not in _ALLOWED:
        counts["normalised"] += 1
        print(f"  {doc.get('_id')}: status {status!r} -> scheduled")
        set_fields["status"] = ScheduledTaskStatus.SCHEDULED.value


def _sync_enabled(
    doc: dict, activated: bool, set_fields: dict[str, object], counts: dict[str, int]
) -> None:
    """Sync trigger_config.enabled to activated (single liveness field)."""
    current_enabled = (doc.get("trigger_config") or {}).get("enabled")
    if isinstance(doc.get("trigger_config"), dict) and current_enabled != activated:
        counts["enabled_synced"] += 1
        print(f"  {doc.get('_id')}: trigger_config.enabled {current_enabled!r} -> {activated}")
        set_fields["trigger_config.enabled"] = activated


def _rearm_recurring(
    doc: dict, now: datetime, set_fields: dict[str, object], counts: dict[str, int]
) -> None:
    """Recompute the next future run for an active recurring workflow."""
    timezone = (doc.get("trigger_config") or {}).get("timezone") or "UTC"
    next_run = get_next_run_time(doc["repeat"], now, timezone)
    occurrence_count = doc.get("occurrence_count") or 0
    max_occurrences = doc.get("max_occurrences")
    stop_after = _to_datetime(doc.get("stop_after"))
    workflow_id = doc.get("_id")

    if next_run is None:
        # Invalid cron or no future occurrence -> nothing left to fire.
        counts["completed"] += 1
        print(f"  {workflow_id}: no future run -> completed")
        set_fields["status"] = ScheduledTaskStatus.COMPLETED.value
        return

    limit_reached = (max_occurrences and occurrence_count >= max_occurrences) or (
        stop_after and next_run >= stop_after
    )
    if limit_reached:
        counts["completed"] += 1
        print(f"  {workflow_id}: limit reached -> completed")
        set_fields["status"] = ScheduledTaskStatus.COMPLETED.value
    else:
        counts["rearmed"] += 1
        print(f"  {workflow_id}: re-arm -> {next_run.isoformat()}")
        set_fields["status"] = ScheduledTaskStatus.SCHEDULED.value
        set_fields["scheduled_at"] = next_run
        if isinstance(doc.get("trigger_config"), dict):
            set_fields["trigger_config.next_run"] = next_run


async def migrate(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Repairing workflow liveness/run-state...\n")

    scheduler = WorkflowScheduler()
    if apply:
        await scheduler.initialize()

    counts = {"normalised": 0, "rearmed": 0, "completed": 0, "enabled_synced": 0}

    try:
        async for doc in workflows_collection.find({}):
            workflow_id = doc.get("_id")
            now = datetime.now(UTC)
            activated = bool(doc.get("activated", False))
            set_fields: dict[str, object] = {}

            _normalise_status(doc, set_fields, counts)
            _sync_enabled(doc, activated, set_fields, counts)
            if doc.get("repeat") and activated:
                _rearm_recurring(doc, now, set_fields, counts)

            if not set_fields:
                continue

            if apply:
                set_fields["updated_at"] = now
                await workflows_collection.update_one({"_id": workflow_id}, {"$set": set_fields})
                if set_fields.get("scheduled_at"):
                    await scheduler.reschedule_task(str(workflow_id), set_fields["scheduled_at"])
    finally:
        if apply:
            await scheduler.close()

    print(
        f"\n[{mode}] Done. status-normalised={counts['normalised']} "
        f"enabled-synced={counts['enabled_synced']} "
        f"re-armed={counts['rearmed']} completed={counts['completed']}"
    )
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
