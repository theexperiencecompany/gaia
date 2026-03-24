"""
One-time migration: generate slugs for all existing public workflows without one.

Run from repo root:
    cd apps/api && uv run python scripts/migrate_workflow_slugs.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.mongodb.collections import workflows_collection  # noqa: E402
from shared.py.utils.slugify import slugify  # noqa: E402


async def migrate() -> None:
    """Generate slugs for all public workflows that don't have one."""
    query = {"is_public": True, "slug": {"$in": [None, ""]}}

    total = await workflows_collection.count_documents(query)
    if total == 0:
        print("No public workflows found without a slug. Nothing to migrate.")
        return

    print(f"Found {total} public workflow(s) without a slug. Migrating...")

    updated = 0
    skipped = 0

    async for workflow in workflows_collection.find(query, {"_id": 1, "title": 1}):
        workflow_id = workflow["_id"]
        title = workflow.get("title", "")

        if not title:
            print(f"  Skipping workflow {workflow_id}: empty title")
            skipped += 1
            continue

        base_slug = slugify(title)

        # Ensure uniqueness by appending a counter suffix when collisions exist
        slug = base_slug
        counter = 1
        while (
            await workflows_collection.count_documents(
                {"slug": slug, "_id": {"$ne": workflow_id}}
            )
            > 0
        ):
            slug = f"{base_slug}-{counter}"
            counter += 1

        await workflows_collection.update_one(
            {"_id": workflow_id},
            {"$set": {"slug": slug}},
        )
        print(f"  {workflow_id}: '{title}' -> '{slug}'")
        updated += 1

    print(f"\nMigration complete. Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    asyncio.run(migrate())
