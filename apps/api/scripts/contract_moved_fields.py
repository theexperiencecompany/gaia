"""Contract step: drop the old fields the expand migrations copied into their new shape.

The expand migrations (migrate_short_link_targets, migrate_brief_storage, migrate_briefing_state,
migrate_todo_delivery) copy and leave the old fields, because the previous release keeps serving
while the release step runs. This drops them, and so belongs to the release AFTER the one that
ran the expands, once no serving code reads the old fields: that release adds
("contract_moved_fields", contract) to the end of POST_DEPLOY_STEPS. Each contract first re-runs
its expand, so whatever the previous release wrote in the old shape meanwhile is copied, not lost.

    cd apps/api && uv run python -m scripts.contract_moved_fields [--apply]
"""

import asyncio
import sys

from scripts import (
    migrate_brief_storage,
    migrate_briefing_state,
    migrate_short_link_targets,
    migrate_todo_delivery,
)


async def contract(apply: bool) -> None:
    """Drop every copied field, in the order the expands ran."""
    await migrate_short_link_targets.contract(apply=apply)
    await migrate_brief_storage.contract(apply)
    await migrate_briefing_state.contract(apply)
    await migrate_todo_delivery.contract(apply)


if __name__ == "__main__":
    asyncio.run(contract(apply="--apply" in sys.argv))
