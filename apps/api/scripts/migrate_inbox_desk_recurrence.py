"""Idempotent migration: move every Inbox desk's daily sweep ahead of the morning brief.

The desk's scheduled report is now held for the brief rather than sent, so the
sweep has to finish before the brief runs. Desks provisioned on the old 08:00
recurrence move to INBOX_DESK_RECURRENCE; a desk whose recurrence the user
changed is left alone, and re-running is safe. The occurrence already queued
fires once at its old time, then the desk follows the new recurrence.

    cd apps/api && uv run python scripts/migrate_inbox_desk_recurrence.py [--apply]
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.todos import INBOX_DESK_RECURRENCE
from app.db.mongodb.collections import get_async_collection
from app.models.todo_models import ExternalRefSource

_PREVIOUS_RECURRENCE = "0 8 * * *"

todos_collection = get_async_collection("todos")


async def migrate(apply: bool) -> None:
    """Point every desk still on the old recurrence at INBOX_DESK_RECURRENCE."""
    mode = "APPLY" if apply else "DRY RUN"
    print(
        f"[{mode}] Moving Inbox desks from {_PREVIOUS_RECURRENCE!r} to {INBOX_DESK_RECURRENCE!r}\n"
    )

    query = {
        "external_ref.source": ExternalRefSource.INBOX_DESK.value,
        "recurrence": _PREVIOUS_RECURRENCE,
    }
    moved = 0
    async for doc in todos_collection.find(query, {"_id": 1}):
        moved += 1
        print(f"  {doc['_id']}")
        if apply:
            await todos_collection.update_one(
                {"_id": doc["_id"], "recurrence": _PREVIOUS_RECURRENCE},
                {"$set": {"recurrence": INBOX_DESK_RECURRENCE, "updated_at": datetime.now(UTC)}},
            )

    print(f"\n[{mode}] Done. desks={moved}")
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
