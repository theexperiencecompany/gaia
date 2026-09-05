#!/usr/bin/env python3
"""One-time, idempotent cleanup of pre-capability short links.

Short links used to be per-user and 3 characters, resolved behind auth. The
capability model replaced that: a slug is now globally unique and grants read
access on its own, enforced by a unique index on ``slug`` alone.

The old rows cannot coexist with that index — two users could hold the same
3-char slug, so a global unique index fails to build over them. They are not
migrated because they are derived data: the briefing re-mints a link for any
artifact it still surfaces, and the old auth-gated resolution path is gone, so
the rows resolve to nothing either way.

This lives in a script rather than in index bootstrap on purpose. Deleting rows
is not something a process should do because it started, and doing it there
means every deploy and every dev restart runs a ``delete_many`` nobody reviewed
at that moment.

Run: uv run python -m scripts.migrate_short_link_slugs [--dry-run]
"""

import asyncio
from contextlib import suppress
import sys

from pymongo.errors import OperationFailure

from app.db.mongodb.collections import get_async_collection
from app.services.short_link_service import LEGACY_SLUG_MAX_LENGTH

short_links_collection = get_async_collection("short_links")

LEGACY_FILTER = {"$expr": {"$lte": [{"$strLenCP": "$slug"}, LEGACY_SLUG_MAX_LENGTH]}}
LEGACY_INDEX = "user_slug_unique"


async def migrate(dry_run: bool) -> None:
    legacy_count = await short_links_collection.count_documents(LEGACY_FILTER)
    total = await short_links_collection.count_documents({})
    print(
        f"short links: {total} total, {legacy_count} legacy "
        f"(slug <= {LEGACY_SLUG_MAX_LENGTH} chars) to delete"
    )
    if dry_run:
        return

    deleted = await short_links_collection.delete_many(LEGACY_FILTER)
    # The per-user index is meaningless once slugs are globally unique. Absent
    # when the collection is new, which is not an error.
    dropped = False
    with suppress(OperationFailure):
        await short_links_collection.drop_index(LEGACY_INDEX)
        dropped = True
    print(f"deleted: {deleted.deleted_count}; legacy index dropped: {dropped}")
    print("now restart the API (or run create_all_indexes) to build slug_unique")


if __name__ == "__main__":
    asyncio.run(migrate(dry_run="--dry-run" in sys.argv))
