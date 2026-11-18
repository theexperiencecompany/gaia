"""Rename the brief loop's idle ladder in briefing_state from dormancy to wind_down.

Rows an earlier migrate_briefing_state wrote hold it as dormancy, its pause stamp as
dormant_since; this release reads wind_down and wound_down_since. The release step runs before
the new code serves and the previous release never reads briefing_state, so the rename is
done in place. Re-running renames nothing.

    cd apps/api && uv run python -m scripts.rename_brief_wind_down [--apply]
"""

import asyncio

from app.db.mongodb.collections import get_async_collection
from scripts._cli import apply_requested

_OLD = {"dormancy": {"$exists": True}}

briefing_state_collection = get_async_collection("briefing_state")


async def migrate(apply: bool) -> int:
    """Rename dormancy to wind_down on every row holding it; return how many rows it renamed."""
    mode = "APPLY" if apply else "DRY RUN"
    renamed = await briefing_state_collection.count_documents(_OLD)
    if apply:
        await briefing_state_collection.update_many(_OLD, {"$rename": {"dormancy": "wind_down"}})
        await briefing_state_collection.update_many(
            {"wind_down.dormant_since": {"$exists": True}},
            {"$rename": {"wind_down.dormant_since": "wind_down.wound_down_since"}},
        )
    print(f"[{mode}] Renamed dormancy to wind_down on briefing_state rows={renamed}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return renamed


if __name__ == "__main__":
    asyncio.run(migrate(apply=apply_requested(__doc__)))
