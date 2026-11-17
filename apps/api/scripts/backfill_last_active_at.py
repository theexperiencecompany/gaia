"""Idempotent backfill: give every user the last_active_at their own metered actions prove.

Until the request middleware recorded activity on every surface, only a WorkOS web
login wrote users.last_active_at, so a bot-only or self-host user reads as never
seen and the 30-day dormancy sweep would pause them the day it ships. Every metered
action a user takes counts on usage_daily (count > 0; agent and brief runs only add
cost), so the latest such day is a floor for when they were last active. The write
only ever moves last_active_at forward ($max), so a re-run changes nothing.

    cd apps/api && uv run python -m scripts.backfill_last_active_at [--apply]
"""

import asyncio
from datetime import UTC, datetime
import sys

from app.db.mongodb.collections import get_async_collection
from app.db.mongodb.mongodb import object_id_filter

users_collection = get_async_collection("users")
usage_daily_collection = get_async_collection("usage_daily")

#: The latest UTC day each user took a metered action on, as YYYY-MM-DD.
_LATEST_ACTIVE_DAY = [
    {"$match": {"count": {"$gt": 0}}},
    {"$group": {"_id": "$user_id", "day": {"$max": "$date"}}},
]


async def backfill(apply: bool) -> int:
    """Raise each user's last_active_at to their latest metered day; return how many move."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Raising users.last_active_at to each user's latest metered action\n")
    moved = 0
    async for row in usage_daily_collection.aggregate(_LATEST_ACTIVE_DAY):
        user_id, day = str(row["_id"]), str(row["day"])
        active_at = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
        behind = {
            **object_id_filter(user_id),
            "$or": [{"last_active_at": None}, {"last_active_at": {"$lt": active_at}}],
        }
        if await users_collection.count_documents(behind, limit=1) == 0:
            continue
        moved += 1
        print(f"  {user_id}: -> {day}")
        if apply:
            await users_collection.update_one(
                object_id_filter(user_id), {"$max": {"last_active_at": active_at}}
            )

    print(f"\n[{mode}] Done. users={moved}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return moved


if __name__ == "__main__":
    asyncio.run(backfill(apply="--apply" in sys.argv))
