"""Contract step: drop the old fields the expand migrations copied into their new shape.

The expand migrations (migrate_todo_delivery, migrate_notification_details) copy and leave the
old fields, because the previous release keeps serving while the release step runs. This drops
them, so it runs as the last of POST_DEPLOY_STEPS, a release after the expands. Each contract
first re-runs its expand, so whatever the previous release wrote in the old shape meanwhile is
copied, not lost.

    cd apps/api && uv run python -m scripts.contract_moved_fields [--apply]
"""

import asyncio

from scripts import migrate_notification_details, migrate_todo_delivery
from scripts._cli import apply_requested


async def contract(apply: bool) -> None:
    """Drop every copied field, in the order the expands ran."""
    await migrate_todo_delivery.contract(apply)
    await migrate_notification_details.contract(apply)


if __name__ == "__main__":
    asyncio.run(contract(apply=apply_requested(__doc__)))
