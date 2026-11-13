"""Collapse selected_integrations into integration_ids on workflow documents, one-time and idempotent.

selected_integrations was UI-picked (scoping step generation);
integration_ids was assistant-derived from intent. They are now one field;
connection state is derived from steps at read time, not stored.

Merges the two lists (integration_ids first, then new selected_integrations
ids), de-duped and order-preserving, lowercases ids to match the create
path, then drops the legacy key. Ids are NOT validated against the OAuth
catalog since custom integrations use an opaque uuid. Idempotent: a
document with no legacy key is skipped.

Run: cd apps/api && uv run python scripts/migrate_workflow_integration_fields.py [--apply]
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import workflows_collection

_LEGACY_FIELD = "selected_integrations"


def _merge_ids(existing: object, legacy: object) -> list[str]:
    """Merge both lists into one, lowercased, de-duped, order-preserving."""
    merged: list[str] = []
    for source in (existing, legacy):
        if not isinstance(source, list):
            continue
        for raw in source:
            if not isinstance(raw, str):
                continue
            value = raw.strip().lower()
            if value and value not in merged:
                merged.append(value)
    return merged


async def migrate(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN"
    print(f"[{mode}] Collapsing {_LEGACY_FIELD} into integration_ids...\n")

    scanned = 0
    changed = 0

    async for doc in workflows_collection.find({_LEGACY_FIELD: {"$exists": True}}):
        scanned += 1
        workflow_id = doc.get("_id")
        existing = doc.get("integration_ids")
        legacy = doc.get(_LEGACY_FIELD)

        merged = _merge_ids(existing, legacy)
        current = existing if isinstance(existing, list) else []

        if merged != current:
            print(f"  {workflow_id}: integration_ids {current!r} -> {merged!r}")
            changed += 1
        else:
            print(f"  {workflow_id}: dropping legacy {_LEGACY_FIELD} (no new ids)")

        if apply:
            await workflows_collection.update_one(
                {"_id": workflow_id},
                {
                    "$set": {"integration_ids": merged, "updated_at": datetime.now(UTC)},
                    "$unset": {_LEGACY_FIELD: ""},
                },
            )

    print(
        f"\n[{mode}] Done. scanned={scanned} gaining_ids={changed} legacy_field_dropped={scanned}"
    )
    if not apply:
        print("Re-run with --apply to write these changes.")


if __name__ == "__main__":
    asyncio.run(migrate(apply="--apply" in sys.argv))
