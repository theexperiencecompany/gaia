"""Quick test script for email memory processing."""

import asyncio
import sys
from pathlib import Path


# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.provider_registration import unified_startup  # noqa: E402
from app.agents.memory.email_processor import process_gmail_to_memory  # noqa: E402
from app.services.composio.composio_service import init_composio_service  # noqa: E402

init_composio_service()

USER_ID = "691e0aadf86f5e1ba347711d"


async def main():
    await unified_startup(context="main_app")

    print(f"Testing email memory processing for user: {USER_ID}")
    print("-" * 60)

    # Reset processing flags before testing
    from app.db.mongodb.collections import users_collection
    from bson import ObjectId

    print("Resetting email_memory_processed flags...")
    await users_collection.update_one(
        {"_id": ObjectId(USER_ID)},
        {
            "$unset": {
                "email_memory_processed": "",
                "email_memory_processed_at": "",
                "email_memory_count": "",
            }
        },
    )
    print("✓ Flags reset\n")

    result = await process_gmail_to_memory(USER_ID)

    print("\n" + "=" * 60)
    print("RESULTS:")
    print(f"  Total fetched: {result['total']}")
    print(f"  Successfully stored: {result['successful']}")
    print(f"  Failed: {result['failed']}")
    print(f"  Profiles stored: {result['profiles_stored']}")
    print(f"  Processing complete: {result['processing_complete']}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
