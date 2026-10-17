"""Idempotent migration: replace each workflow's notify_on_completion with delivery.

notify_on_completion=true (or absent, the old default) becomes delivery="now";
notify_on_completion=false becomes delivery="silent". The legacy field is unset.
Workflows that already carry a delivery are left alone, so re-running is safe.

WorkflowDocument reads an unmigrated record the same way at load time, so the
deploy does not depend on this having run; running it retires that mapping's
work and is safe before or after the new code ships.

    cd apps/api && uv run python -m scripts.migrate_workflow_delivery [--apply]
"""

import asyncio
import sys

from app.constants.workflows import WorkflowDelivery
from app.db.repositories.workflows import workflow_repository


async def migrate(apply: bool) -> None:
    """Store delivery on every workflow that lacks it, from its legacy flag."""
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Mapping notify_on_completion to delivery...\n")

    counts = dict.fromkeys(WorkflowDelivery, 0)
    for workflow in await workflow_repository.find_without_stored_delivery():
        counts[workflow.delivery] += 1
        print(f"  {workflow.id}: -> {workflow.delivery}")
        if apply:
            await workflow_repository.store_delivery(workflow.id, workflow.delivery)

    summary = " ".join(f"{mode_value}={count}" for mode_value, count in counts.items())
    print(f"\n[{mode}] Done. {summary}")
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
