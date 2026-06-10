"""
One-time, idempotent migration: backfill the `source` field on bot conversations.

Older bot conversations were created without a `source`, so they leak into the web
conversation list (the list query excludes bot sources via `$nin`, but a missing
field is treated as "include"). This script derives the originating platform from
each `bot_sessions` mapping and stamps it onto the matching conversation document.

The platform is taken from the session_key, which has the format
`platform:platform_user_id:channel` (e.g. `whatsapp:123:dm`).

Only conversations whose `source` is missing/null are touched, so the script is
safe to run multiple times.

Run from repo root:
    cd apps/api && uv run python scripts/backfill_bot_conversation_source.py
"""

import asyncio
from pathlib import Path
import sys

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import (  # noqa: E402
    bot_sessions_collection,
    conversations_collection,
)
from app.models.chat_models import ConversationSource  # noqa: E402

_VALID_SOURCES = {source.value for source in ConversationSource}


def _derive_platform(session: dict) -> str | None:
    """Resolve the platform for a session, preferring an explicit field."""
    platform = session.get("platform")
    if not platform:
        # Fall back to the session_key prefix (`platform:user:channel`).
        session_key = session.get("session_key", "")
        platform = session_key.split(":", 1)[0] if session_key else None

    if platform in _VALID_SOURCES:
        return platform
    return None


async def backfill() -> None:
    """Stamp `source` onto bot conversations that are missing it."""
    total = await bot_sessions_collection.count_documents({})
    if total == 0:
        print("No bot sessions found. Nothing to backfill.")
        return

    print(f"Scanning {total} bot session(s) for conversations missing a source...")

    updated = 0
    skipped = 0

    async for session in bot_sessions_collection.find(
        {}, {"conversation_id": 1, "session_key": 1, "platform": 1}
    ):
        conversation_id = session.get("conversation_id")
        if not conversation_id:
            skipped += 1
            continue

        platform = _derive_platform(session)
        if not platform:
            print(f"  Skipping {conversation_id}: could not derive a valid platform")
            skipped += 1
            continue

        # Only set source where it is missing/null so re-runs are no-ops.
        result = await conversations_collection.update_one(
            {
                "conversation_id": conversation_id,
                "$or": [{"source": {"$exists": False}}, {"source": None}],
            },
            {"$set": {"source": platform}},
        )

        if result.modified_count:
            print(f"  {conversation_id}: source -> '{platform}'")
            updated += 1
        else:
            skipped += 1

    print(f"\nBackfill complete. Updated: {updated}, Skipped (already set/no match): {skipped}")


if __name__ == "__main__":
    asyncio.run(backfill())
