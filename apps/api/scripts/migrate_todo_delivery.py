"""Expand migration: give each todo still carrying the notify_on_run flag its delivery.

notify_on_run=false becomes delivery="silent"; true becomes "brief" on an Inbox desk, whose
scheduled sweep feeds the brief, and "now" on every other todo. The flag stays: the previous
release serves while the release step runs and still reads it. contract() drops it a release
later. A todo that already carries a delivery keeps it, so re-running is safe.

    cd apps/api && uv run python -m scripts.migrate_todo_delivery [--apply]
"""

import asyncio
import sys

from app.constants.workflows import WorkflowDelivery
from app.db.mongodb.collections import get_async_collection
from app.models.todo_models import ExternalRefSource

_FLAG = "notify_on_run"
_DESK = ExternalRefSource.INBOX_DESK.value
_IS_DESK = {"$eq": ["$external_ref.source", _DESK]}
#: The delivery each flagged todo gets, read off its own flag and external ref.
_DELIVERY_FROM_FLAG = {
    "$switch": {
        "branches": [
            {"case": {"$eq": [f"${_FLAG}", False]}, "then": WorkflowDelivery.SILENT.value},
            {"case": _IS_DESK, "then": WorkflowDelivery.BRIEF.value},
        ],
        "default": WorkflowDelivery.NOW.value,
    }
}

_UNMAPPED = {_FLAG: {"$exists": True}, "delivery": {"$exists": False}}

todos_collection = get_async_collection("todos")


async def migrate(apply: bool) -> int:
    """Store delivery on every todo carrying the flag without one; return how many todos it touched."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Mapping notify_on_run to delivery...\n")
    on = {**_UNMAPPED, _FLAG: {"$exists": True, "$ne": False}}
    counts = {
        "silent": await todos_collection.count_documents({**_UNMAPPED, _FLAG: False}),
        "brief": await todos_collection.count_documents({**on, "external_ref.source": _DESK}),
        "now": await todos_collection.count_documents(
            {**on, "external_ref.source": {"$ne": _DESK}}
        ),
    }
    if apply:
        await todos_collection.update_many(_UNMAPPED, [{"$set": {"delivery": _DELIVERY_FROM_FLAG}}])

    print(f"[{mode}] Done. " + " ".join(f"{name}={count}" for name, count in counts.items()))
    if not apply:
        print("Re-run with --apply to write these changes.")
    return sum(counts.values())


async def contract(apply: bool) -> int:
    """Map what the previous release wrote since, then drop the flag; return how many todos lose it."""
    await migrate(apply)
    mode = "APPLY" if apply else "DRY RUN"
    flagged = {_FLAG: {"$exists": True}}
    dropped = await todos_collection.count_documents(flagged)
    if apply:
        await todos_collection.update_many(flagged, {"$unset": {_FLAG: ""}})
    print(f"[{mode}] Dropped notify_on_run from todos={dropped}")
    return dropped


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
