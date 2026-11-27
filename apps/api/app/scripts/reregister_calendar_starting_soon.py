#!/usr/bin/env python3
"""Re-register every calendar "event starting soon" trigger under the corrected Composio config.

Instances registered before the fix carry the lead as a look-ahead only, so Composio fires them
at its 10-minute default whatever the user chose. Re-registering creates instances on the stored
minutes_before_start and releases the stale ones. Idempotent: a current instance is kept.

Usage::

    cd apps/api
    uv run python -m app.scripts.reregister_calendar_starting_soon            # dry run
    uv run python -m app.scripts.reregister_calendar_starting_soon --apply
"""

from __future__ import annotations

import argparse
import asyncio

from app.db.repositories.todos import todo_repository
from app.db.repositories.workflows import workflow_repository
from app.services.triggers.subscription_service import reregister_active_subscriptions
from app.services.workflow.trigger_service import TriggerService

TRIGGER_NAME = "calendar_event_starting_soon"


async def _run(apply: bool) -> int:
    workflow_users = await workflow_repository.distinct_users_with_activated_workflows()
    todo_users = await todo_repository.distinct_users_with_active_subscription(TRIGGER_NAME)
    print(f"candidates: workflow_users={len(workflow_users)} todo_users={len(todo_users)}")
    if not apply:
        print("dry run: pass --apply to re-register")
        return 0
    for user_id in workflow_users:
        await TriggerService.resync_user_workflow_triggers(user_id, [TRIGGER_NAME])
    todos = 0
    for user_id in todo_users:
        todos += await reregister_active_subscriptions(user_id, TRIGGER_NAME)
    print(f"re-registered: workflow_users={len(workflow_users)} todos={todos}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Re-register; without it, only count.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.apply)))


if __name__ == "__main__":
    main()
