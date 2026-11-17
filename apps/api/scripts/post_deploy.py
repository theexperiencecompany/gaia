"""The one post-deploy step: every data migration a release needs, in order, each exactly once.

Dry run unless --apply: lists the steps still to run and runs each as its own dry run.
With --apply each pending step runs for real, after claiming its marker in the
deploy_steps collection, so a step that finished is never re-run and two runners never
run one step at once; a step that fails releases its claim and stops the sequence loudly,
and the next run retries it. The ARQ worker runs this with --apply on every start
(workers.lifecycle.post_deploy), which covers a production deploy and `gaia update` on
self-host alike. Deploy the worker before the API whenever a release adds a job name.

    cd apps/api && uv run python -m scripts.post_deploy [--apply]
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
import sys

from pymongo.errors import DuplicateKeyError

from app.db.mongodb.collections import get_async_collection
from app.services.links.backfill import backfill_snapshots
from scripts.backfill_last_active_at import backfill as backfill_last_active_at
from scripts.clear_email_derived_names import clear_email_derived_names
from scripts.migrate_inbox_desk_recurrence import migrate as migrate_inbox_desk_recurrence
from scripts.migrate_workflow_delivery import migrate as migrate_workflow_delivery
from scripts.provision_daily_briefings import rollout as provision_daily_briefings

#: Each step's marker name and its migration, run with apply=. Order matters: activity is
#: backfilled before anything reads dormancy, and the briefs exist before the desk follows them.
POST_DEPLOY_STEPS: tuple[tuple[str, Callable[..., Awaitable[object]]], ...] = (
    ("backfill_last_active_at", backfill_last_active_at),
    ("provision_daily_briefings", provision_daily_briefings),
    ("migrate_inbox_desk_recurrence", migrate_inbox_desk_recurrence),
    ("migrate_workflow_delivery", migrate_workflow_delivery),
    ("backfill_link_snapshots", backfill_snapshots),
    ("clear_email_derived_names", clear_email_derived_names),
)

#: A claim older than this belongs to a runner that died mid-step; the next run takes it over.
_STALE_CLAIM = timedelta(hours=2)

deploy_steps = get_async_collection("deploy_steps")


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
        now = datetime.now(UTC)
        try:
            # Upserts a fresh claim, or takes over one a killed runner left behind.
            await deploy_steps.update_one(
                {"_id": name, "applied_at": None, "claimed_at": {"$lt": now - _STALE_CLAIM}},
                {"$set": {"claimed_at": now, "applied_at": None}},
                upsert=True,
            )
        except DuplicateKeyError:
            print(f"  {name}: claimed by another runner, skipped")
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


if __name__ == "__main__":
    asyncio.run(run_post_deploy(apply="--apply" in sys.argv))
