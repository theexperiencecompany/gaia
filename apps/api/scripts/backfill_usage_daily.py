"""
One-time, idempotent migration: backfill `usage_daily` for existing users.

The activity heatmap and percentile badge read from the `usage_daily` collection
(one doc per user per UTC day), which only starts accumulating when this feature
ships. Without a backfill, every existing user opens an empty year grid and
nobody can earn a badge for ~30 days (the percentile compares trailing-30-day
totals, and everyone would be at zero).

This script reconstructs history from the durable data we already have: the
`messages` arrays embedded in `conversations`. Each *user-role* message counts
as one action on its UTC day, and each `tool_data` entry on a bot message (one
persisted tool execution) counts as one more — matching what the live
`record_activity()` path meters from deploy day onward.

Idempotency: for each (user, day) the backfilled value is written with `$max`,
so re-runs never inflate counts, and days already ahead of the backfill value
(because live tracking has been running) are left untouched.

Run from repo root:
    cd apps/api && uv run python scripts/backfill_usage_daily.py [--days 365] [--dry-run]
"""

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pymongo import UpdateOne

from app.db.mongodb.collections import get_async_collection
from app.services.usage_activity import sync_activity_tiers

conversations_collection = get_async_collection("conversations")
usage_daily_collection = get_async_collection("usage_daily")

_USER_ROLES = {"user", "human"}
_BATCH = 1000


def _parse_ts(raw: object) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def backfill(days: int, dry_run: bool) -> None:
    since = datetime.now(UTC) - timedelta(days=days)
    counts: Counter[tuple[str, str]] = Counter()  # (user_id, YYYY-MM-DD) -> n
    conversations = 0

    cursor = conversations_collection.find(
        {},
        {
            "user_id": 1,
            "messages.role": 1,
            "messages.type": 1,
            "messages.timestamp": 1,
            "messages.date": 1,
            "messages.tool_data.timestamp": 1,
            "messages.tool_data.tool_name": 1,
        },
    )
    async for conv in cursor:
        conversations += 1
        user_id = conv.get("user_id")
        if not user_id:
            continue
        for message in conv.get("messages") or []:
            # Production messages carry `type` + `date`; newer code paths write
            # `role` + `timestamp`. Accept both shapes (verified against prod).
            message_dt = _parse_ts(message.get("timestamp") or message.get("date"))

            # Every user-role message is one action on its day.
            if (message.get("role") or message.get("type")) in _USER_ROLES:
                if message_dt is not None and message_dt >= since:
                    counts[(user_id, message_dt.astimezone(UTC).strftime("%Y-%m-%d"))] += 1
                continue

            # Bot messages carry the turn's tool executions in `tool_data`.
            # Only `tool_calls_data` entries are counted (one per invocation,
            # emitted when a call's args complete) — the other variants are
            # result payloads of those same calls and would double-count.
            for entry in message.get("tool_data") or []:
                if entry.get("tool_name") != "tool_calls_data":
                    continue
                dt = _parse_ts(entry.get("timestamp")) or message_dt
                if dt is None or dt < since:
                    continue
                counts[(user_id, dt.astimezone(UTC).strftime("%Y-%m-%d"))] += 1

    users = len({uid for uid, _ in counts})
    total = sum(counts.values())
    print(
        f"scanned {conversations} conversations -> {total} user messages "
        f"across {users} users / {len(counts)} user-days (window: {days}d)"
    )
    if dry_run:
        print("dry run — nothing written")
        return

    ops = [
        UpdateOne(
            {"user_id": uid, "date": day},
            # $max keeps whichever is larger: the backfilled estimate or a count
            # the live record_activity() path has already accumulated.
            {"$max": {"count": n}},
            upsert=True,
        )
        for (uid, day), n in counts.items()
    ]
    written = 0
    for i in range(0, len(ops), _BATCH):
        result = await usage_daily_collection.bulk_write(ops[i : i + _BATCH], ordered=False)
        written += (result.upserted_count or 0) + (result.modified_count or 0)
    print(f"bulk_write done: {len(ops)} ops, {written} inserted/updated")

    # Seed every user's current badge tier SILENTLY. Without this, the first
    # nightly promote_usage_badges run after deploy would read all existing
    # standings as brand-new promotions and blast congratulation emails at
    # ~25% of the user base in one night.
    stats = await sync_activity_tiers(send_emails=False)
    print(f"tiers seeded silently: {stats}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=365, help="Trailing window to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Scan and report, write nothing")
    args = parser.parse_args()
    asyncio.run(backfill(args.days, args.dry_run))
