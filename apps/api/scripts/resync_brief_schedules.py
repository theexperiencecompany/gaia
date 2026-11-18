"""Idempotent: move every user's briefing workflows onto the cron their profile gives today.

Briefs used to fire at minute 0 of their hour; a stored cron keeps that minute until something
resyncs it, so existing users only get their spread slot minute (workers.brief_slots) here.
A dry run lists each briefing workflow whose cron would move; a re-run moves nothing.

    cd apps/api && uv run python -m scripts.resync_brief_schedules [--apply]
"""

import asyncio
import sys

from app.constants.briefing import BRIEFING_KIND_BY_WORKFLOW_KEY
from app.core.provider_registration import register_lazy_providers
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.services.briefing.run_times import briefing_cron
from app.services.briefing.schedule import resync_briefing_schedules


async def resync(apply: bool) -> int:
    """Resync every user whose briefing crons are not the ones their profile gives; return how many."""
    mode = "APPLY" if apply else "DRY RUN"
    if apply:
        # No app lifespan here: register the providers the workflow scheduler reads.
        register_lazy_providers("main_app")
    behind = 0
    for user_id in await user_repository.list_all_ids():
        user = await user_repository.get(user_id)
        if user is None:
            continue
        schedule = (await briefing_state_repository.state_for(user_id)).schedule
        workflows = await workflow_repository.find_system_workflows(
            user_id, tuple(BRIEFING_KIND_BY_WORKFLOW_KEY)
        )
        moves = [
            (w.system_workflow_key, w.trigger_config.cron_expression, cron)
            for w in workflows
            if w.system_workflow_key
            and w.trigger_config.cron_expression
            != (cron := briefing_cron(w.system_workflow_key, user, schedule))
        ]
        if not moves:
            continue
        behind += 1
        for key, old, new in moves:
            print(f"  {user_id} {key}: {old} -> {new}")
        if apply:
            await resync_briefing_schedules(user)
    print(f"[{mode}] Done. users={behind}")
    if not apply:
        print("Re-run with --apply to move them.")
    return behind


if __name__ == "__main__":
    asyncio.run(resync(apply="--apply" in sys.argv))
