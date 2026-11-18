"""Expand migration: give every short link written before typed targets its target reference.

Links minted before it carry target_type and a target_id string, a workspace file's
being "<conversation_id>/<path>" under the type "session_artifact". This writes each
one's target (a record's {type, id}, a workspace file's {type, conversation_id, path})
and drops the indexes keyed on the old fields: their unique live-target key would refuse
every second new-shape link, and their names block the API's build of the new ones. The
old fields stay until contract() drops them a release later. Short links never reached
production; this is for the databases that ran the branch (local dev and brief-eval copies).

    cd apps/api && uv run python -m scripts.migrate_short_link_targets [--apply]

Dry run by default. Safely re-runnable: a link that already has its target is skipped.
"""

import asyncio
from collections.abc import Mapping
import sys

from pydantic import TypeAdapter

from app.db.mongodb.collections import get_async_collection
from app.models.short_link_models import LinkTarget, ShortLinkTargetType

COLLECTION = "short_links"
OLD_TYPE_FIELD = "target_type"
OLD_ID_FIELD = "target_id"
OLD_WORKSPACE_FILE_TYPE = "session_artifact"
_TARGET: TypeAdapter[LinkTarget] = TypeAdapter(LinkTarget)


def target_of(doc: Mapping[str, object]) -> dict[str, object]:
    """Return the stored target of an old-shape link; raise naming the link when it cannot have one."""
    old_type, old_id = doc.get(OLD_TYPE_FIELD), doc.get(OLD_ID_FIELD)
    if not isinstance(old_type, str) or not isinstance(old_id, str):
        raise ValueError(f"short link {doc.get('slug')!r} has no target_type and target_id")
    if old_type == OLD_WORKSPACE_FILE_TYPE:
        conversation_id, _, path = old_id.partition("/")
        raw: dict[str, str] = {
            "type": ShortLinkTargetType.WORKSPACE_FILE.value,
            "conversation_id": conversation_id,
            "path": path,
        }
    else:
        raw = {"type": old_type, "id": old_id}
    return _TARGET.validate_python(raw).model_dump(mode="json")


async def old_shape_index_names() -> list[str]:
    """Name the indexes keyed on the old target fields."""
    return [
        index["name"]
        async for index in get_async_collection(COLLECTION).list_indexes()
        if OLD_TYPE_FIELD in index["key"]
    ]


async def migrate(*, apply: bool) -> tuple[int, list[str]]:
    """Give each old-shape link its target and drop the old indexes; return what was (or would be) changed."""
    collection = get_async_collection(COLLECTION)
    untargeted = {OLD_TYPE_FIELD: {"$exists": True}, "target": {"$exists": False}}
    planned = [(doc["_id"], target_of(doc)) async for doc in collection.find(untargeted)]
    indexes = await old_shape_index_names()
    if apply:
        for index in indexes:
            await collection.drop_index(index)
        for doc_id, target in planned:
            await collection.update_one({"_id": doc_id, **untargeted}, {"$set": {"target": target}})
    return len(planned), indexes


async def contract(*, apply: bool) -> int:
    """Target what the previous release minted since, then drop the old fields; return how many links lose them."""
    await migrate(apply=apply)
    collection = get_async_collection(COLLECTION)
    old = {OLD_TYPE_FIELD: {"$exists": True}}
    dropped = await collection.count_documents(old)
    if apply:
        await collection.update_many(old, {"$unset": {OLD_TYPE_FIELD: "", OLD_ID_FIELD: ""}})
    print(f"{'APPLIED' if apply else 'DRY RUN'}: old target fields dropped from links={dropped}")
    return dropped


async def main(apply: bool) -> None:
    links, indexes = await migrate(apply=apply)
    print("APPLIED" if apply else "DRY RUN, nothing was written")
    print(f"links given a target: {links}")
    print(f"old indexes dropped:  {', '.join(indexes) or 'none'}")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
