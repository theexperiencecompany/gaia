"""Idempotent migration: move each user's briefing state off the user document into briefing_state.

briefing_schedule, briefing_editions, briefing_bootstrap, briefing_dormancy, day_zero_hello and
briefing_shuffle_bags become the user's briefing_state row (schedule, editions, bootstrap,
dormancy, day_zero_hello, shuffle_bags) and leave the user document. The post-deploy step runs
beside a worker already on the new code, so a value the row holds wins over the moved one, and
dormancy and the shuffle bags merge key by key, as the new code writes them. Every moved value
is validated first, so a malformed one stops the run before anything is written. Re-running
moves nothing.

    cd apps/api && uv run python -m scripts.migrate_briefing_state [--apply]
"""

import asyncio
from collections.abc import Mapping
import sys

from app.db.mongodb.collections import get_async_collection
from app.models.briefing_state_models import BriefingStateDocument

#: Each user-document field and the briefing_state field it becomes.
_MOVED: dict[str, str] = {
    "briefing_schedule": "schedule",
    "briefing_editions": "editions",
    "briefing_bootstrap": "bootstrap",
    "briefing_dormancy": "dormancy",
    "day_zero_hello": "day_zero_hello",
    "briefing_shuffle_bags": "shuffle_bags",
}
#: The fields the new code writes key by key, so they move key by key.
_MERGED_BY_KEY = frozenset({"dormancy", "shuffle_bags"})

users_collection = get_async_collection("users")
briefing_state_collection = get_async_collection("briefing_state")


def _moved_paths(user_id: str, doc: Mapping[str, object]) -> dict[str, object]:
    """Return the briefing_state path each of the user's set values moves to, validated."""
    moved = {_MOVED[old]: doc[old] for old in _MOVED if doc.get(old) is not None}
    BriefingStateDocument.model_validate({"user_id": user_id, **moved})
    paths: dict[str, object] = {}
    for field, value in moved.items():
        if field in _MERGED_BY_KEY and isinstance(value, Mapping):
            paths.update({f"{field}.{key}": v for key, v in value.items() if v is not None})
        else:
            paths[field] = value
    return paths


async def migrate(apply: bool) -> int:
    """Move every user's briefing fields into their briefing_state row; return how many users moved."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Moving briefing state off the user documents\n")
    query = {"$or": [{old: {"$exists": True}} for old in _MOVED]}
    moved = 0
    async for doc in users_collection.find(query, dict.fromkeys(_MOVED, 1)):
        user_id = str(doc["_id"])
        paths = _moved_paths(user_id, doc)
        moved += 1
        print(f"  {user_id}: {sorted(paths)}")
        if not apply:
            continue
        if paths:
            fills = {
                path: {"$ifNull": [f"${path}", {"$literal": value}]}
                for path, value in paths.items()
            }
            await briefing_state_collection.update_one(
                {"user_id": user_id}, [{"$set": fills}], upsert=True
            )
        await users_collection.update_one(
            {"_id": doc["_id"]}, {"$unset": dict.fromkeys(_MOVED, "")}
        )

    print(f"\n[{mode}] Done. users={moved}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return moved


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
