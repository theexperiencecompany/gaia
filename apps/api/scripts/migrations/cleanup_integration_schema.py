"""
Migration: Cleanup Integration Schema

This migration:
1. Drops redundant indexes from the integrations collection
2. Removes deprecated fields from all documents
3. Migrates integration_id format to short UUID for new integrations

Run with: python -m scripts.migrations.cleanup_integration_schema
"""

import asyncio
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from motor.motor_asyncio import AsyncIOMotorClient

from app.config.settings import settings


async def get_database():
    """Get MongoDB database connection."""
    client = AsyncIOMotorClient(settings.MONGO_DB)
    return client["GAIA"]


async def drop_redundant_indexes(db):
    """Drop indexes that are no longer needed."""
    integrations = db["integrations"]

    indexes_to_drop = [
        "slug_public_lookup",  # No more slug field
        "slug_unique_sparse",  # No more slug field
        "source_1",  # Redundant - covered by source_1_is_public_1_created_at_-1
        "name_text_description_text",  # ChromaDB semantic search replaced this
        "marketplace_browse",  # Redundant - public_popular covers use case
    ]

    existing_indexes = await integrations.index_information()

    for index_name in indexes_to_drop:
        if index_name in existing_indexes:
            print(f"Dropping index: {index_name}")
            try:
                await integrations.drop_index(index_name)
                print(f"  ✓ Dropped {index_name}")
            except Exception as e:
                print(f"  ✗ Failed to drop {index_name}: {e}")
        else:
            print(f"  - Index {index_name} does not exist, skipping")


async def remove_deprecated_fields(db):
    """Remove deprecated fields from all integration documents."""
    integrations = db["integrations"]

    fields_to_remove = {
        "slug": "",
        "cloned_from": "",
        "og_title": "",
        "og_description": "",
        "creator_name": "",
        "creator_picture": "",
    }

    print("\nRemoving deprecated fields from all documents...")

    # Count documents with these fields
    count_with_fields = await integrations.count_documents(
        {"$or": [{field: {"$exists": True}} for field in fields_to_remove.keys()]}
    )
    print(f"  Found {count_with_fields} documents with deprecated fields")

    if count_with_fields > 0:
        result = await integrations.update_many({}, {"$unset": fields_to_remove})
        print(f"  ✓ Updated {result.modified_count} documents")
    else:
        print("  - No documents to update")


async def verify_cleanup(db):
    """Verify the cleanup was successful."""
    integrations = db["integrations"]

    print("\nVerification:")

    # Check indexes
    indexes = await integrations.index_information()
    print(f"  Remaining indexes: {len(indexes)}")
    for name in indexes.keys():
        print(f"    - {name}")

    # Check for deprecated fields
    deprecated_fields = [
        "slug",
        "cloned_from",
        "og_title",
        "og_description",
        "creator_name",
        "creator_picture",
    ]
    for field in deprecated_fields:
        count = await integrations.count_documents({field: {"$exists": True}})
        if count > 0:
            print(f"  ✗ Warning: {count} documents still have '{field}' field")
        else:
            print(f"  ✓ No documents have '{field}' field")


async def run_migration():
    """Run the full migration."""
    print("=" * 60)
    print("Integration Schema Cleanup Migration")
    print("=" * 60)

    db = await get_database()

    # Step 1: Drop redundant indexes
    print("\n[Step 1] Dropping redundant indexes...")
    await drop_redundant_indexes(db)

    # Step 2: Remove deprecated fields
    print("\n[Step 2] Removing deprecated fields...")
    await remove_deprecated_fields(db)

    # Step 3: Verify
    print("\n[Step 3] Verifying cleanup...")
    await verify_cleanup(db)

    print("\n" + "=" * 60)
    print("Migration completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_migration())
