"""Expand migration: copy each user's briefing state off the user document into briefing_state.

briefing_schedule, briefing_editions, briefing_bootstrap, briefing_dormancy, day_zero_hello and
briefing_shuffle_bags are copied into the user's briefing_state row (schedule, editions,
bootstrap, wind_down, day_zero_hello, shuffle_bags; dormant_since becomes wound_down_since). The
user document keeps them: the previous release serves while the release step runs and still
reads them there. contract() drops them a release later. A value the row already holds wins, and
the wind-down and the shuffle bags merge key by key, as the new code writes them. Every value is validated first, so a malformed one stops
the run before anything is written. Re-running copies nothing.

    cd apps/api && uv run python -m scripts.migrate_briefing_state [--apply]
"""

import asyncio
from collections.abc import Mapping

from app.db.mongodb.collections import get_async_collection
from app.models.briefing_state_models import BriefingStateDocument
from scripts._cli import apply_requested

#: Each user-document field and the briefing_state field it becomes.
_MOVED: dict[str, str] = {
    "briefing_schedule": "schedule",
    "briefing_editions": "editions",
    "briefing_bootstrap": "bootstrap",
    "briefing_dormancy": "wind_down",
    "day_zero_hello": "day_zero_hello",
    "briefing_shuffle_bags": "shuffle_bags",
}
#: The fields the new code writes key by key, so they move key by key.
_MERGED_BY_KEY = frozenset({"wind_down", "shuffle_bags"})
#: The keys a user-document field held under another name.
_RENAMED_KEYS: dict[str, dict[str, str]] = {"wind_down": {"dormant_since": "wound_down_since"}}
_HAS_OLD_FIELD = {"$or": [{old: {"$exists": True}} for old in _MOVED]}

users_collection = get_async_collection("users")
briefing_state_collection = get_async_collection("briefing_state")


def _renamed(field: str, value: object) -> object:
    renames = _RENAMED_KEYS.get(field)
    if renames is None or not isinstance(value, Mapping):
        return value
    return {renames.get(key, key): v for key, v in value.items()}


def _moved_paths(user_id: str, doc: Mapping[str, object]) -> dict[str, object]:
    """Return the briefing_state path each of the user's set values moves to, validated."""
    moved = {
        _MOVED[old]: _renamed(_MOVED[old], doc[old]) for old in _MOVED if doc.get(old) is not None
    }
    BriefingStateDocument.model_validate({"user_id": user_id, **moved})
    paths: dict[str, object] = {}
    for field, value in moved.items():
        if field in _MERGED_BY_KEY and isinstance(value, Mapping):
            paths.update({f"{field}.{key}": v for key, v in value.items() if v is not None})
        else:
            paths[field] = value
    return paths


def _missing(paths: Mapping[str, object], row: Mapping[str, object] | None) -> dict[str, object]:
    """Return the paths the user's row does not hold yet."""

    def held(path: str) -> bool:
        value: object = row
        for part in path.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        return value is not None

    return {path: value for path, value in paths.items() if not held(path)}


async def migrate(apply: bool) -> int:
    """Copy every user's briefing fields into their briefing_state row; return how many users it copied."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Copying briefing state off the user documents\n")
    copied = 0
    async for doc in users_collection.find(_HAS_OLD_FIELD, dict.fromkeys(_MOVED, 1)):
        user_id = str(doc["_id"])
        row = await briefing_state_collection.find_one({"user_id": user_id})
        paths = _missing(_moved_paths(user_id, doc), row)
        if not paths:
            continue
        copied += 1
        print(f"  {user_id}: {sorted(paths)}")
        if apply:
            fills = {
                path: {"$ifNull": [f"${path}", {"$literal": value}]}
                for path, value in paths.items()
            }
            await briefing_state_collection.update_one(
                {"user_id": user_id}, [{"$set": fills}], upsert=True
            )

    print(f"\n[{mode}] Done. users={copied}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return copied


async def contract(apply: bool) -> int:
    """Copy what the previous release wrote since, then drop the old user fields; return how many users lose them."""
    await migrate(apply)
    mode = "APPLY" if apply else "DRY RUN"
    dropped = await users_collection.count_documents(_HAS_OLD_FIELD)
    if apply:
        await users_collection.update_many(_HAS_OLD_FIELD, {"$unset": dict.fromkeys(_MOVED, "")})
    print(f"[{mode}] Dropped the old briefing fields from users={dropped}")
    return dropped


if __name__ == "__main__":
    asyncio.run(migrate(apply=apply_requested(__doc__)))
