#!/usr/bin/env python3
"""
Cleanup script to remove old/invalid workflow steps from the database.
This removes workflows with malformed or outdated step structures.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add the backend directory to Python path so we can import from app
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))


from app.config.loggers import arq_worker_logger as logger  # noqa: E402
from app.db.mongodb.collections import workflows_collection  # noqa: E402


async def cleanup_old_workflow_steps():
    """Remove workflows with old/invalid step structures."""
    try:
        # Find workflows with invalid step structures
        # 1. Steps that don't have required fields
        # 2. Steps created more than 30 days ago without executions
        # 3. Steps with malformed tool configurations

        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Query for workflows to clean up
        cleanup_query = {
            "$or": [
                # Workflows older than 30 days with no executions
                {"created_at": {"$lt": thirty_days_ago}, "total_executions": 0},
                # Workflows with empty or malformed steps
                {"steps": {"$size": 0}},
                # Workflows with steps missing required fields
                {
                    "steps": {
                        "$elemMatch": {
                            "$or": [
                                {"tool_name": {"$exists": False}},
                                {"id": {"$exists": False}},
                                {"title": {"$exists": False}},
                            ]
                        }
                    }
                },
            ]
        }

        # Count workflows to be cleaned up
        workflows_to_cleanup = await workflows_collection.count_documents(cleanup_query)

        if workflows_to_cleanup == 0:
            logger.info("No workflows found that need cleanup.")
            return True

        logger.info(f"Found {workflows_to_cleanup} workflows that need cleanup.")

        # Show some examples before deletion (for safety)
        sample_workflows = (
            await workflows_collection.find(
                cleanup_query, {"title": 1, "created_at": 1, "total_executions": 1}
            )
            .limit(5)
            .to_list(length=5)
        )

        logger.info("Sample workflows to be cleaned up:")
        for wf in sample_workflows:
            logger.info(
                f"  - {wf.get('title', 'Untitled')} (created: {wf.get('created_at')}, executions: {wf.get('total_executions', 0)})"
            )

        # Ask for confirmation in interactive mode
        if sys.stdin.isatty():
            response = input(
                f"\nDo you want to delete {workflows_to_cleanup} workflows? (y/N): "
            )
            if response.lower() != "y":
                logger.info("Cleanup cancelled by user.")
                return False

        # Perform the cleanup
        result = await workflows_collection.delete_many(cleanup_query)

        logger.info(f"Cleanup completed. Deleted {result.deleted_count} workflows.")

        return True

    except Exception as e:
        logger.error(f"Cleanup failed with error: {str(e)}")
        return False


async def cleanup_orphaned_workflow_data():
    """Clean up workflows that reference non-existent users or have corrupt data."""
    try:
        # Find workflows with invalid user references or corrupt data
        invalid_query = {
            "$or": [
                {"user_id": {"$exists": False}},
                {"user_id": None},
                {"user_id": ""},
                {"title": {"$exists": False}},
                {"description": {"$exists": False}},
            ]
        }

        invalid_count = await workflows_collection.count_documents(invalid_query)

        if invalid_count == 0:
            logger.info("No orphaned or corrupt workflow data found.")
            return True

        logger.info(f"Found {invalid_count} workflows with corrupt/orphaned data.")

        # Delete invalid workflows
        result = await workflows_collection.delete_many(invalid_query)

        logger.info(f"Cleaned up {result.deleted_count} corrupt/orphaned workflows.")

        return True

    except Exception as e:
        logger.error(f"Orphaned data cleanup failed: {str(e)}")
        return False


async def run_all_cleanup():
    """Run all workflow cleanup operations."""
    logger.info("🧹 Starting workflow database cleanup...")

    cleanup_operations = [
        ("Clean up old workflow steps", cleanup_old_workflow_steps),
        ("Clean up orphaned workflow data", cleanup_orphaned_workflow_data),
    ]

    all_successful = True

    for cleanup_name, cleanup_func in cleanup_operations:
        logger.info(f"Running cleanup: {cleanup_name}")
        try:
            success = await cleanup_func()
            if success:
                logger.info(f"✅ {cleanup_name} completed successfully")
            else:
                logger.error(f"❌ {cleanup_name} failed")
                all_successful = False
        except Exception as e:
            logger.error(f"❌ {cleanup_name} failed with exception: {str(e)}")
            all_successful = False

    if all_successful:
        logger.info("🎉 All workflow cleanup operations completed successfully!")
    else:
        logger.error("💥 Some cleanup operations failed. Please check the logs above.")

    return all_successful


if __name__ == "__main__":
    result = asyncio.run(run_all_cleanup())
    sys.exit(0 if result else 1)
