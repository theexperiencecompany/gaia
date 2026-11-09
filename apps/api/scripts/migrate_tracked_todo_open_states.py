#!/usr/bin/env python3
"""One-time migration: give every open tracked todo a next step.

Every open, non-recurring, unpaused tracked todo now needs waiting_on and a future
scheduled_at (app.services.todos.open_state). Todos written before the rule have
neither, so many sit open with nothing that will ever look at them again.

Each one without a waiting_on becomes 'unplanned'. Its first run's brief asks the
model to decide what it really waits on. It keeps a future scheduled_at that is
within the limit; otherwise its check is spread across the next three days, so the
backlog does not all run at once. Failed todos are left alone: they need the user.

Run from the api directory (or /app inside the container), with Redis reachable:

    python scripts/migrate_tracked_todo_open_states.py            # dry run, prints the plan
    python scripts/migrate_tracked_todo_open_states.py --apply    # writes and enqueues

Safely re-runnable: a todo that already has a waiting_on is skipped.
"""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.todos import (
    FAILED_LABEL,
    GAIA_TRACKED_LABEL,
    MAX_NEXT_CHECK_AHEAD,
    TodoActivityEvent,
    WaitingOn,
)
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoUpdate
from app.services.todo_activity import record_activity
from app.services.tracked_todo_service import tracked_todo_service

#: How long the backlog's first checks are spread over, and how soon the first one runs.
SPREAD = timedelta(days=3)
FIRST_CHECK_AFTER = timedelta(hours=1)


@dataclass(frozen=True)
class Migration:
    """One todo's new open state."""

    todo_id: str
    user_id: str
    title: str
    scheduled_at: datetime
    kept_schedule: bool


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def build_plan(now: datetime) -> list[Migration]:
    """Find every open tracked todo with no waiting_on and decide its next check; writes nothing."""
    cursor = get_async_collection("todos").find(
        {
            "labels": GAIA_TRACKED_LABEL,
            "completed": False,
            "recurrence": {"$in": [None, ""]},
            "pause_reason": None,
            "waiting_on": None,
        }
    )
    found = [doc async for doc in cursor if FAILED_LABEL not in doc.get("labels", [])]
    found.sort(key=lambda doc: str(doc["_id"]))
    step = SPREAD / max(len(found), 1)
    plan: list[Migration] = []
    for index, doc in enumerate(found):
        current = doc.get("scheduled_at")
        keep = current is not None and now < _as_utc(current) <= now + MAX_NEXT_CHECK_AHEAD
        plan.append(
            Migration(
                todo_id=str(doc["_id"]),
                user_id=str(doc["user_id"]),
                title=str(doc.get("title", "")),
                scheduled_at=_as_utc(current) if keep else now + FIRST_CHECK_AFTER + step * index,
                kept_schedule=keep,
            )
        )
    return plan


async def apply_plan(plan: list[Migration]) -> None:
    """Write each todo's open state, record it in its activity, and enqueue its check."""
    for row in plan:
        updated = await todo_repository.update(
            row.todo_id,
            user_id=row.user_id,
            update=TodoUpdate(waiting_on=WaitingOn.UNPLANNED, scheduled_at=row.scheduled_at),
        )
        if updated is None:
            continue
        if not row.kept_schedule:
            await tracked_todo_service.schedule_execution(row.todo_id, row.scheduled_at)
        await record_activity(
            row.todo_id,
            row.user_id,
            TodoActivityEvent.WAITING_CHANGED,
            f"waiting on unplanned, plan it by {row.scheduled_at.isoformat()}, by the open-state migration",
        )


def _render(plan: list[Migration], *, applied: bool) -> None:
    print("\nAPPLIED" if applied else "\nDRY RUN, nothing was written")
    print(f"open tracked todos given a next step: {len(plan)}")
    print(f"  kept their scheduled_at:            {sum(row.kept_schedule for row in plan)}")
    for row in plan:
        kept = "kept" if row.kept_schedule else "new "
        print(f"  {row.todo_id:<26}{kept} {row.scheduled_at.isoformat():<34}{row.title[:60]!r}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the states and enqueue checks")
    args = parser.parse_args()

    plan = await build_plan(datetime.now(UTC))
    if args.apply:
        await apply_plan(plan)
    _render(plan, applied=args.apply)
    if not args.apply:
        print("\nRe-run with --apply to write.")


if __name__ == "__main__":
    asyncio.run(main())
