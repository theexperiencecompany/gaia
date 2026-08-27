"""
One-time, idempotent migration: collapse ``selected_integrations`` into
``integration_ids`` on workflow documents.

The two fields grew independently on separate branches and ended up meaning the
same thing — which integrations a workflow uses:

- ``selected_integrations`` — the ids the user picked in the UI, used to scope
  step generation.
- ``integration_ids`` — the ids the workflow assistant identified from intent.

They are now a single field, ``integration_ids``. Connection state is never
stored: required/missing integrations are derived from the workflow's steps at
read time, so connecting an integration clears the warning with nothing to
clean up.

For every document still carrying ``selected_integrations`` this merges the two
lists (``integration_ids`` first, then any new ids from
``selected_integrations``), de-duped and order-preserving, then drops the legacy
key. Ids are lowercased to match what the create path persists. Ids are NOT
validated against the OAuth catalog — custom integrations are keyed by an opaque
uuid and would be discarded by such a filter.

Idempotent: once the legacy key is unset a document is skipped, so re-running is
safe.

Run from repo root (dry run prints what would change):
    cd apps/api && uv run python scripts/migrate_workflow_integration_fields.py
Apply the changes:
    cd apps/api && uv run python scripts/migrate_workflow_integration_fields.py --apply
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
