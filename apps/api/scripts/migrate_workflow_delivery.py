"""Idempotent migration: replace each workflow's notify_on_completion with delivery.

notify_on_completion=true (or absent, the old default) becomes delivery="now";
notify_on_completion=false becomes delivery="silent". The legacy field is unset.
Workflows that already carry a delivery are left alone, so re-running is safe.

WorkflowDocument reads an unmigrated record the same way at load time, so the
deploy does not depend on this having run; running it retires that mapping's
work and is safe before or after the new code ships.

    cd apps/api && uv run python scripts/migrate_workflow_delivery.py [--apply]
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.workflows import WorkflowDelivery
from app.db.mongodb.collections import get_async_collection
from app.models.workflow_models import LegacyDeliveryFlag

workflows_collection = get_async_collection("workflows")


async def migrate(apply: bool) -> None:
    """Set delivery on every workflow that lacks it, from its legacy flag."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Mapping notify_on_completion to delivery...\n")

    counts = dict.fromkeys(WorkflowDelivery, 0)
    query = {"delivery": {"$exists": False}}
    async for doc in workflows_collection.find(query, {"_id": 1, "notify_on_completion": 1}):
        delivery = LegacyDeliveryFlag.model_validate(doc).delivery
        counts[delivery] += 1
        print(
            f"  {doc['_id']}: notify_on_completion={doc.get('notify_on_completion')!r} -> {delivery}"
        )
        if apply:
            await workflows_collection.update_one(
                {"_id": doc["_id"], "delivery": {"$exists": False}},
                {
                    "$set": {"delivery": delivery.value, "updated_at": datetime.now(UTC)},
                    "$unset": {"notify_on_completion": ""},
                },
            )

    summary = " ".join(f"{mode_value}={count}" for mode_value, count in counts.items())
    print(f"\n[{mode}] Done. {summary}")
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
