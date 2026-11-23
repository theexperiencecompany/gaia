"""The release step: every data migration a release needs, in order, each exactly once.

A one-off process of the new image that finishes before that image serves: GAIA Cloud runs
it as a Swarm job before the stack rolls (scripts/ci/deploy.sh migrate); the self-host
compose runs it as the migrate service the API and worker wait on.

Dry run unless --apply. With --apply each pending step runs after claiming its marker in
deploy_steps, so a finished step never re-runs; a step another live runner holds is waited
for, never skipped, so steps still apply in order. The holder refreshes its claim while the
step runs, so only a dead runner's claim goes stale and is taken over. A failed step releases
its claim and stops the sequence loudly; the next run retries it.

    cd apps/api && uv run python -m scripts.post_deploy [--apply]
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
import uuid

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

#: How often the runner applying a step refreshes its claim.
_CLAIM_HEARTBEAT = timedelta(seconds=30)
#: A claim not refreshed for this long belongs to a runner that died; the next run takes it over.
_STALE_CLAIM = timedelta(minutes=2)
#: How often a run waiting on another runner's step checks whether it has finished.
_CLAIM_POLL = timedelta(seconds=5)

deploy_steps = get_async_collection("deploy_steps")


async def _claim(name: str, holder: str) -> bool:
    """Claim a step for holder; False once another runner has applied it, waiting while it runs."""
    while True:
        now = datetime.now(UTC)
        try:
            # Upserts a fresh claim, or takes over one a killed runner left behind.
            await deploy_steps.update_one(
                {"_id": name, "applied_at": None, "claimed_at": {"$lt": now - _STALE_CLAIM}},
                {"$set": {"claimed_at": now, "claimed_by": holder, "applied_at": None}},
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


async def _keep_claim(name: str, holder: str) -> None:
    """Refresh holder's claim until cancelled or until another runner has taken it over."""
    while True:
        await asyncio.sleep(_CLAIM_HEARTBEAT.total_seconds())
        kept = await deploy_steps.update_one(
            {"_id": name, "claimed_by": holder}, {"$set": {"claimed_at": datetime.now(UTC)}}
        )
        if not kept.matched_count:
            return


async def run_post_deploy(apply: bool) -> list[str]:
    """Run every step not yet applied, in order; return the names this run applied."""
    done = {doc["_id"] async for doc in deploy_steps.find({"applied_at": {"$ne": None}})}
    pending = [(name, step) for name, step in POST_DEPLOY_STEPS if name not in done]
    print(f"[{'APPLY' if apply else 'DRY RUN'}] pending steps: {[name for name, _ in pending]}")
    applied: list[str] = []
    holder = uuid.uuid4().hex
    for name, step in pending:
        if not apply:
            await step(apply=False)
            continue
        if not await _claim(name, holder):
            print(f"  {name}: applied by another runner")
            continue
        keeper = asyncio.create_task(_keep_claim(name, holder))
        try:
            await step(apply=True)
        except BaseException:
            await deploy_steps.delete_one({"_id": name, "applied_at": None, "claimed_by": holder})
            raise
        finally:
            keeper.cancel()
        marked = await deploy_steps.update_one(
            {"_id": name, "claimed_by": holder}, {"$set": {"applied_at": datetime.now(UTC)}}
        )
        if not marked.matched_count:
            raise RuntimeError(f"{name}: another runner took this run's claim over while it ran")
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
