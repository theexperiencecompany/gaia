"""Idempotent migration: replace each todo's notify_on_run flag with its delivery.

notify_on_run=false becomes delivery="silent"; true becomes "brief" on an Inbox desk, whose
scheduled sweep feeds the brief, and "now" on every other todo. The flag is unset. A todo
that already carries a delivery keeps it and only loses the stale flag, so re-running is safe.

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

todos_collection = get_async_collection("todos")


async def migrate(apply: bool) -> int:
    """Store delivery on every todo still carrying the flag; return how many todos it touched."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Mapping notify_on_run to delivery...\n")
    unmapped = {_FLAG: {"$exists": True}, "delivery": {"$exists": False}}
    stale = {_FLAG: {"$exists": True}, "delivery": {"$exists": True}}
    on = {_FLAG: {"$exists": True, "$ne": False}, "delivery": {"$exists": False}}
    counts = {
        "silent": await todos_collection.count_documents({**unmapped, _FLAG: False}),
        "brief": await todos_collection.count_documents({**on, "external_ref.source": _DESK}),
        "now": await todos_collection.count_documents(
            {**on, "external_ref.source": {"$ne": _DESK}}
        ),
        "stale_flag": await todos_collection.count_documents(stale),
    }
    if apply:
        await todos_collection.update_many(
            unmapped, [{"$set": {"delivery": _DELIVERY_FROM_FLAG}}, {"$unset": _FLAG}]
        )
        await todos_collection.update_many(stale, {"$unset": {_FLAG: ""}})

    print(f"[{mode}] Done. " + " ".join(f"{name}={count}" for name, count in counts.items()))
    if not apply:
        print("Re-run with --apply to write these changes.")
    return sum(counts.values())


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
