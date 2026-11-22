#!/usr/bin/env python3
"""Dry-run the recipes GAIA ships against one user's real data, acting for nobody.

For each of the user's system workflows that ships a recipe, the recipe is
replayed in dry-run mode: the allowlisted reads (DRY_RUN_READ_TOOLS) run for
real, every other step prints the call it would have made, and the narration
is printed instead of delivered. Nothing is stored: no playbook, execution,
message or notification. The model calls the replay makes are real, so they
are metered to the user like any background call (COGS only, never their
budget).

A calendar recipe needs the event a fire would be about; the user's next
upcoming event stands in for it.

Usage, in the backend container::

    python -m app.scripts.playbook_dry_run --user-id <id>
    python -m app.scripts.playbook_dry_run --user-id <id> --key calendar:meeting_reminder
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json

from app.core.provider_registration import boot_process
from app.db.repositories.workflows import workflow_repository
from app.models.playbook_models import PlaybookDocument
from app.services.calendar_service import get_calendar_events
from app.services.system_workflows.definitions import SYSTEM_RECIPES
from app.services.system_workflows.recipes import RECIPE_AUTHORED_RUN_PREFIX
from app.services.user_service import get_user_by_id
from app.services.workflow.playbook.dry_run import DryRun
from app.services.workflow.playbook.evaluator import PlaybookUser
from app.services.workflow.playbook.runner import run_playbook
from app.services.workflow.playbook.workflow_hash import workflow_hash
from app.utils.timezone import Timezone
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context

#: Recipes whose trigger is a calendar event about to start.
_CALENDAR_KEYS = frozenset({"calendar:meeting_prep", "calendar:meeting_reminder"})
_UPCOMING_EVENTS = 5


async def _next_event_trigger(user_id: str) -> dict[str, object]:
    """The context a calendar_event_starting_soon fire for the next event would carry."""
    page = await get_calendar_events(
        user_id=user_id, time_min=datetime.now(UTC).isoformat(), max_results=_UPCOMING_EVENTS
    )
    event = next((item for item in page.events if item.id), None)
    if event is None:
        raise SystemExit("the user has no upcoming calendar event to dry-run a calendar recipe on")
    return {
        "trigger_type": "integration",
        "trigger_data": {
            "event_id": event.id,
            "calendar_id": event.calendarId or "primary",
            "summary": event.summary,
            "start_time": event.start.dateTime if event.start else None,
            "html_link": event.htmlLink,
        },
    }


async def _run(args: argparse.Namespace) -> int:
    boot_process("arq_worker")
    user = await get_user_by_id(args.user_id)
    if user is None:
        raise SystemExit(f"no user {args.user_id}")
    playbook_user = PlaybookUser(
        email=user.email or "",
        name=user.name or "",
        timezone=user.timezone or Timezone.utc().value,
    )
    keys = [args.key] if args.key else sorted(SYSTEM_RECIPES)
    failed = 0
    for key in keys:
        workflow = await workflow_repository.find_system_workflow(args.user_id, key)
        if workflow is None:
            print(f"== {key}: the user has no such workflow; skipped")
            continue
        body = SYSTEM_RECIPES[key]()
        now = datetime.now(UTC)
        playbook = PlaybookDocument(
            workflow_id=workflow.id,
            user_id=args.user_id,
            workflow_hash=workflow_hash(workflow.prompt, workflow.steps),
            authored_run=f"{RECIPE_AUTHORED_RUN_PREFIX}{key}",
            created_at=now,
            updated_at=now,
            description=body.description,
            steps=body.steps,
            result_brief=body.result_brief,
        )
        trigger = await _next_event_trigger(args.user_id) if key in _CALENDAR_KEYS else {}
        print(f"== {key} ({workflow.id})\ntrigger: {json.dumps(trigger)}")
        result = await run_playbook(
            playbook,
            user=playbook_user,
            conversation_id=f"dry_run_{workflow.id}",
            stream_id=f"dry_run_{workflow.id}",
            trigger=trigger,
            dry_run=DryRun(),
        )
        for line in result.completed:
            print(f"  step: {line[:400]}")
        if not result.ok:
            failed += 1
            print(f"  STOPPED: {result.failure}")
            continue
        verdict = result.suspect or result.narration_failed
        print(f"  model calls: {result.llm_calls}; flagged: {verdict or 'no'}")
        print(f"  narration (not delivered):\n{result.text}\n")
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--key", choices=sorted(SYSTEM_RECIPES), help="one recipe only")
    args = parser.parse_args()
    # An operator's dry run: the model calls it makes are system work.
    with analytics_context(worker_context(Trigger.SYSTEM)):
        return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
