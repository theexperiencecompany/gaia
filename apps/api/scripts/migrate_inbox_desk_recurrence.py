"""Idempotent migration: move every Inbox desk's daily sweep ahead of its user's daily brief.

The desk's scheduled report is held for the brief, so the sweep has to finish before
the brief runs: INBOX_DESK_LEAD_HOURS before the user's own brief hour. Desks still
on one of the fixed recurrences GAIA used to give them move to their user's; a desk
whose recurrence the user changed is left alone, and re-running is safe. The next run
is re-armed on the new recurrence, which retires the occurrence already queued.

    cd apps/api && uv run python scripts/migrate_inbox_desk_recurrence.py [--apply]
"""

import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import get_async_collection
from app.db.repositories.briefing_state import briefing_state_repository
from app.db.repositories.users import user_repository
from app.models.todo_models import ExternalRefSource
from app.services.briefing.run_times import inbox_desk_recurrence
from app.services.todos.inbox_desk import follow_the_brief

#: The recurrences GAIA gave every desk before the sweep followed the brief hour.
_FIXED_RECURRENCES = ("0 8 * * *", "0 7 * * *")

todos_collection = get_async_collection("todos")


async def migrate(apply: bool) -> int:
    """Move every open desk still on a fixed recurrence onto its user's; return the count."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Moving Inbox desks off {_FIXED_RECURRENCES} onto each user's brief hour\n")
    query = {
        "external_ref.source": ExternalRefSource.INBOX_DESK.value,
        "completed": {"$ne": True},
        "recurrence": {"$in": list(_FIXED_RECURRENCES)},
    }
    moved = 0
    async for doc in todos_collection.find(query, {"_id": 1, "user_id": 1, "recurrence": 1}):
        user = await user_repository.get(doc["user_id"])
        if user is None:
            print(f"  {doc['_id']}: no user {doc['user_id']}, left alone")
            continue
        schedule = (await briefing_state_repository.state_for(user.id)).schedule
        target = inbox_desk_recurrence(schedule, user.effective_quiet_hours)
        if target == doc["recurrence"]:
            continue
        moved += 1
        print(f"  {doc['_id']}: {doc['recurrence']!r} -> {target!r}")
        if apply:
            await follow_the_brief(doc["user_id"], doc["recurrence"], target)

    print(f"\n[{mode}] Done. desks={moved}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return moved


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
