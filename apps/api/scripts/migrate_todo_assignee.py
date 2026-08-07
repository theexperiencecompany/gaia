#!/usr/bin/env python3
"""One-time, idempotent migration: `gaia-tracked` label → `assignee` field.

The label was the legacy discriminator for GAIA-owned todos. The unified todo
model replaces it with ``assignee: "user" | "gaia"`` plus an ``execution_status``
lifecycle. This backfill:

1. Sets ``assignee: "gaia"`` on every todo whose ``labels`` contains
   ``gaia-tracked``.
2. Derives ``execution_status``: ``done`` when completed, else ``queued``
   (pre-migration tracked todos were always auto-executing — there was no
   proposal state to preserve).
3. Removes the legacy label. Readers dual-read (``gaia_assigned_filter``) for
   one release, so running this is safe before or after deploy.
4. Sets ``assignee: "user"`` explicitly on remaining todos that lack the field
   so queries never depend on missing-field semantics.

Run: uv run python -m scripts.migrate_todo_assignee [--dry-run]
"""

import asyncio
import sys

from app.constants.todos import (
    ASSIGNEE_GAIA,
    ASSIGNEE_USER,
    GAIA_TRACKED_LABEL,
)
from app.db.mongodb.collections import get_async_collection
from app.models.todo_models import ExecutionStatus

todos_collection = get_async_collection("todos")


async def migrate(dry_run: bool) -> None:
    tracked = {"labels": GAIA_TRACKED_LABEL}
    tracked_count = await todos_collection.count_documents(tracked)
    untagged = {"assignee": {"$exists": False}, "labels": {"$ne": GAIA_TRACKED_LABEL}}
    untagged_count = await todos_collection.count_documents(untagged)
    print(f"tracked (label) todos: {tracked_count}; user todos missing assignee: {untagged_count}")
    if dry_run:
        return

    done = await todos_collection.update_many(
        {**tracked, "completed": True},
        {
            "$set": {
                "assignee": ASSIGNEE_GAIA,
                "execution_status": ExecutionStatus.DONE.value,
            },
            "$pull": {"labels": GAIA_TRACKED_LABEL},
        },
    )
    active = await todos_collection.update_many(
        tracked,
        {
            "$set": {
                "assignee": ASSIGNEE_GAIA,
                "execution_status": ExecutionStatus.QUEUED.value,
            },
            "$pull": {"labels": GAIA_TRACKED_LABEL},
        },
    )
    users = await todos_collection.update_many(untagged, {"$set": {"assignee": ASSIGNEE_USER}})
    print(
        f"migrated gaia todos: done={done.modified_count} active={active.modified_count}; "
        f"user todos stamped: {users.modified_count}"
    )


if __name__ == "__main__":
    asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
