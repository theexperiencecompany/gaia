#!/usr/bin/env python3
"""One-time, idempotent migration: legacy ``canvas_content`` → ``notes_content``.

Tracked todos used to store all working memory in a single ``canvas_content``
blob. That field is now split into facets — ``deliverable``, ``notes``, ``log``
— and the old canvas maps to the ``notes`` facet (it WAS GAIA's working memory).

This backfill copies ``canvas_content`` into ``notes_content`` for every todo
that has the former but not the latter. It is NON-DESTRUCTIVE: ``canvas_content``
is left in place so the read-side dual-read bridge (``facet_from_doc``) keeps
working before and after this runs, and so the change is safe to run either side
of a deploy. The deliverable facet is intentionally NOT backfilled — legacy
proposals fall back to the old canvas for their deliverable via the same bridge,
and new deliverables are authored going forward.

Run: uv run python -m scripts.migrate_todo_facets [--dry-run]
"""

import asyncio
import sys

from app.db.mongodb.collections import get_async_collection

todos_collection = get_async_collection("todos")


async def migrate(dry_run: bool) -> None:
    pending = {
        "canvas_content": {"$exists": True, "$ne": ""},
        "notes_content": {"$exists": False},
    }
    pending_count = await todos_collection.count_documents(pending)
    print(f"todos to backfill (canvas_content → notes_content): {pending_count}")
    if dry_run:
        return

    # Aggregation-pipeline update so notes_content is set from the doc's own
    # canvas_content in a single server-side pass.
    result = await todos_collection.update_many(
        pending,
        [{"$set": {"notes_content": "$canvas_content"}}],
    )
    print(f"backfilled notes_content on {result.modified_count} todos")


if __name__ == "__main__":
    asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
