"""The release step: every data migration a release needs, in order, each exactly once.

A one-off process of the new image that finishes before that image serves: GAIA Cloud runs
it as a Swarm job before the stack rolls (scripts/ci/deploy.sh migrate); the self-host
compose runs it as the migrate service the API and worker wait on.

Dry run unless --apply. With --apply each pending step runs after claiming its marker in
deploy_steps, so a finished step never re-runs; a step another live runner holds is waited
for, never skipped, so steps still apply in order. A failed step releases its claim and
stops the sequence loudly; the next run retries it.

    cd apps/api && uv run python -m scripts.post_deploy [--apply]
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.db.mongodb.collections import get_async_collection
from app.services.workflow.scheduler import workflow_scheduler
from scripts._cli import apply_requested
from scripts.backfill_last_active_at import backfill as backfill_last_active_at
from scripts.clear_email_derived_names import clear_email_derived_names
from scripts.migrate_inbox_desk_recurrence import migrate as migrate_inbox_desk_recurrence
from scripts.migrate_notification_details import migrate as migrate_notification_details
from scripts.migrate_todo_delivery import migrate as migrate_todo_delivery
from scripts.migrate_workflow_delivery import migrate as migrate_workflow_delivery
from scripts.provision_daily_briefings import rollout as provision_daily_briefings
from scripts.retire_legacy_triggers import migrate as retire_legacy_triggers

#: Order matters: shapes are migrated before anything reads them, activity is backfilled before
#: dormancy reads it, and briefs are provisioned before the desk follows them.
#: A migration reads only the fields it rewrites, never a whole old document.
POST_DEPLOY_STEPS: tuple[tuple[str, Callable[..., Awaitable[object]]], ...] = (
    ("retire_legacy_triggers", retire_legacy_triggers),
    ("backfill_last_active_at", backfill_last_active_at),
    ("provision_daily_briefings", provision_daily_briefings),
    ("migrate_inbox_desk_recurrence", migrate_inbox_desk_recurrence),
    ("migrate_workflow_delivery", migrate_workflow_delivery),
    ("migrate_todo_delivery", migrate_todo_delivery),
    ("clear_email_derived_names", clear_email_derived_names),
    ("migrate_notification_details", migrate_notification_details),
)

#: A claim older than this belongs to a runner that died mid-step; the next run takes it over.
#: Just above deploy.sh migrate's 1800s release-job cap, so no live release job holds one this old.
_STALE_CLAIM = timedelta(minutes=35)
#: How often a run waiting on another runner's step checks whether it has finished.
_CLAIM_POLL = timedelta(seconds=5)

deploy_steps = get_async_collection("deploy_steps")


async def _claim(name: str) -> bool:
    """Claim a step for this run; False once another runner has applied it, waiting while it runs."""
    while True:
        now = datetime.now(UTC)
        try:
            # Upserts a fresh claim, or takes over one a killed runner left behind.
            await deploy_steps.update_one(
                {"_id": name, "applied_at": None, "claimed_at": {"$lt": now - _STALE_CLAIM}},
                {"$set": {"claimed_at": now, "applied_at": None}},
                upsert=True,
            )
        except DuplicateKeyError:
            marker = await deploy_steps.find_one({"_id": name})
            if marker is not None and marker["applied_at"] is not None:
                return False
            print(f"  {name}: another runner is applying it, waiting")
            await asyncio.sleep(_CLAIM_POLL.total_seconds())
            continue
        return True


async def run_post_deploy(apply: bool) -> list[str]:
    """Run every step not yet applied, in order; return the names this run applied."""
    done = {doc["_id"] async for doc in deploy_steps.find({"applied_at": {"$ne": None}})}
    pending = [(name, step) for name, step in POST_DEPLOY_STEPS if name not in done]
    print(f"[{'APPLY' if apply else 'DRY RUN'}] pending steps: {[name for name, _ in pending]}")
    applied: list[str] = []
    for name, step in pending:
        if not apply:
            await step(apply=False)
            continue
        if not await _claim(name):
            print(f"  {name}: applied by another runner")
            continue
        try:
            await step(apply=True)
        except BaseException:
            await deploy_steps.delete_one({"_id": name, "applied_at": None})
            raise
        await deploy_steps.update_one({"_id": name}, {"$set": {"applied_at": datetime.now(UTC)}})
        applied.append(name)
        print(f"  {name}: applied")
    return applied


async def release(apply: bool) -> list[str]:
    """Run the release with the workflow scheduler's ARQ pool open, so a workflow a step arms is queued now."""
    await workflow_scheduler.initialize()
    try:
        return await run_post_deploy(apply)
    finally:
        await workflow_scheduler.close()


if __name__ == "__main__":
    asyncio.run(release(apply=apply_requested(__doc__)))
