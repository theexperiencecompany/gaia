#!/usr/bin/env python3
"""Idempotent existing-user briefing rollout; a dry run unless --apply.

For every onboarded user: provision the daily-briefing + weekly-digest system workflows
and fit them to the user's schedule and plan. Users we can derive a goal for get a real
first briefing next morning; sparse users with no derivable goal have their briefings
held (bootstrap marker) until a goal arrives or the grace window elapses. A user still
in the wizard is left to it. Safe to re-run: provisioning is idempotent by
system_workflow_key and the path taken is printed.

Run: uv run python -m scripts.provision_daily_briefings [--apply]
"""

import asyncio
from collections import Counter
import sys

from app.core.provider_registration import register_lazy_providers
from app.db.repositories.users import user_repository
from app.services.briefing.rollout import provision_existing_user
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context


async def rollout(apply: bool) -> Counter[str]:
    """Roll briefings out to every user, or only count them on a dry run; return the paths taken."""
    mode = "APPLY" if apply else "DRY RUN"
    user_ids = await user_repository.list_all_ids()
    print(f"[{mode}] users to roll out: {len(user_ids)}")
    paths: Counter[str] = Counter()
    if not apply:
        print("Re-run with --apply to provision them.")
        return paths

    # No app lifespan here: register the providers capture() and provisioning read.
    register_lazy_providers("main_app")
    for done, user_id in enumerate(user_ids, start=1):
        # A script is an entry point: each user's rollout reports through capture().
        with analytics_context(worker_context(Trigger.SYSTEM)):
            paths[(await provision_existing_user(user_id)).value] += 1
        if done % 100 == 0:
            print(f"  ...{done}/{len(user_ids)}")
    print(f"[{mode}] done: {sum(paths.values())}/{len(user_ids)}; breakdown={dict(paths)}")
    return paths


if __name__ == "__main__":
    asyncio.run(rollout(apply="--apply" in sys.argv))
