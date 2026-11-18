"""Expand migration: move each stored brief's link off its payload onto the brief itself.

The link is minted once the brief is stored, so it is the stored brief's, never its payload's. The
previous release serves while the release step runs and still reads and writes payload.link, so it
stays and contract() drops it a release later, after re-running the expand over what that release
wrote. A brief that already carries its link keeps it, so re-running is safe.

    cd apps/api && uv run python -m scripts.migrate_brief_link [--apply]
"""

import asyncio

from pymongo import UpdateOne

from app.db.mongodb.collections import get_async_collection
from scripts._cli import apply_requested

_PAYLOAD_LINK = "payload.link"
_UNMOVED = {_PAYLOAD_LINK: {"$exists": True}, "link": {"$exists": False}}
_BATCH = 500

briefings_collection = get_async_collection("briefings")


async def migrate(apply: bool) -> int:
    """Copy each stored brief's payload link onto the brief; return how many briefs it touched."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Moving each brief's link off its payload...\n")
    moved = 0
    batch: list[UpdateOne] = []
    async for doc in briefings_collection.find(_UNMOVED, {_PAYLOAD_LINK: 1}):
        moved += 1
        if not apply:
            continue
        batch.append(
            UpdateOne({"_id": doc["_id"], **_UNMOVED}, {"$set": {"link": doc["payload"]["link"]}})
        )
        if len(batch) >= _BATCH:
            await briefings_collection.bulk_write(batch, ordered=False)
            batch = []
    if batch:
        await briefings_collection.bulk_write(batch, ordered=False)
    print(f"[{mode}] Done. briefs={moved}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return moved


async def contract(apply: bool) -> int:
    """Move what the previous release stored since, then drop every payload's link; return how many lose it."""
    await migrate(apply)
    mode = "APPLY" if apply else "DRY RUN"
    carrying = {_PAYLOAD_LINK: {"$exists": True}}
    dropped = await briefings_collection.count_documents(carrying)
    if apply:
        await briefings_collection.update_many(carrying, {"$unset": {_PAYLOAD_LINK: ""}})
    print(f"[{mode}] Dropped the payload link from briefs={dropped}")
    return dropped


if __name__ == "__main__":
    asyncio.run(migrate(apply=apply_requested(__doc__)))
