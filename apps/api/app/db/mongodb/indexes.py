"""
Comprehensive database indexes for all MongoDB collections.
Follows MongoDB indexing best practices for optimal query performance.

Index Strategy:
- User-centric compound indexes for multi-tenant queries
- Sparse indexes for optional fields to reduce storage
- Text search indexes for content discovery
- Unique constraints for data integrity
- ESR (Equality, Sort, Range) ordering for compound indexes
"""

import asyncio
from typing import Dict, List

from app.config.loggers import app_logger as logger
from app.db.mongodb.collections import (
    ai_models_collection,
    blog_collection,
    calendars_collection,
    conversations_collection,
    device_tokens_collection,
    files_collection,
    goals_collection,
    integrations_collection,
    mail_collection,
    notes_collection,
    notifications_collection,
    payments_collection,
    plans_collection,
    projects_collection,
    reminders_collection,
    subscriptions_collection,
    todos_collection,
    usage_snapshots_collection,
    user_integrations_collection,
    users_collection,
    workflow_executions_collection,
    workflows_collection,
)


async def create_all_indexes():
    """
    Create all database indexes for optimal performance.
    This is the main function called during application startup.

    Indexes are created with best practices:
    - User-specific compound indexes for multi-tenant queries
    - Date-based sorting indexes for pagination
    - Text search indexes for full-text search
    - Unique indexes for data integrity    - Compound indexes ordered by: equality → range → sort
    """
    try:
        logger.info("Starting comprehensive database index creation...")

        # Create all indexes concurrently for better performance
        index_tasks = [
            create_user_indexes(),
            create_conversation_indexes(),
            create_todo_indexes(),
            create_project_indexes(),
            create_goal_indexes(),
            create_note_indexes(),
            create_file_indexes(),
            create_mail_indexes(),
            create_calendar_indexes(),
            create_blog_indexes(),
            create_notification_indexes(),
            create_reminder_indexes(),
            create_workflow_indexes(),
            create_payment_indexes(),
            create_usage_indexes(),
            create_ai_models_indexes(),
            create_integration_indexes(),
            create_user_integration_indexes(),
            create_device_token_indexes(),
            create_workflow_execution_indexes(),
        ]

        # Execute all index creation tasks concurrently
        results = await asyncio.gather(*index_tasks, return_exceptions=True)

        collection_names = [
            "users",
            "conversations",
            "todos",
            "projects",
            "goals",
            "notes",
            "files",
            "mail",
            "calendar",
            "blog",
            "notifications",
            "reminders",
            "workflows",
            "payments",
            "usage",
            "ai_models",
            "integrations",
            "user_integrations",
            "device_tokens",
            "workflow_executions",
        ]

        index_results = {}
        for i, (collection_name, result) in enumerate(zip(collection_names, results)):
            if isinstance(result, Exception):
                logger.error(
                    f"Failed to create indexes for {collection_name}: {str(result)}"
                )
                index_results[collection_name] = f"FAILED: {str(result)}"
            else:
                index_results[collection_name] = "SUCCESS"

        # Log summary
        successful = sum(1 for result in index_results.values() if result == "SUCCESS")
        total = len(index_results)

        logger.info(
            f"Database index creation completed: {successful}/{total} collections successful"
        )

        # Log any failures
        failed_collections = [
            name for name, result in index_results.items() if result != "SUCCESS"
        ]
        if failed_collections:
            logger.warning(
                f"Failed to create indexes for collections: {failed_collections}"
            )

    except Exception as e:
        logger.error(f"Critical error during database index creation: {str(e)}")
        raise


async def create_user_indexes():
    """Create indexes for users collection."""
    try:
        # Create all user indexes concurrently
        await asyncio.gather(
            # Email unique index (primary lookup method)
            users_collection.create_index("email", unique=True),
            # Onboarding status with creation date
            users_collection.create_index(
                [("onboarding.completed", 1), ("created_at", -1)]
            ),
            # Cache cleanup index (sparse since not all users have cached_at)
            users_collection.create_index("cached_at", sparse=True),
            # Activity tracking index for inactive user queries
            users_collection.create_index("last_active_at", sparse=True),
            # Inactive email tracking index (sparse since not all users have this field)
            users_collection.create_index("last_inactive_email_sent", sparse=True),
        )

    except Exception as e:
        logger.error(f"Error creating user indexes: {str(e)}")
        raise


async def create_conversation_indexes():
    """Create indexes for conversations collection."""
    try:
        # Create all conversation indexes concurrently
        await asyncio.gather(
            # Primary compound index for user conversations with sorting (most critical)
            conversations_collection.create_index([("user_id", 1), ("createdAt", -1)]),
            # For specific conversation lookups (extremely critical for performance)
            conversations_collection.create_index(
                [("user_id", 1), ("conversation_id", 1)]
            ),
            # For starred conversations queries
            conversations_collection.create_index(
                [("user_id", 1), ("starred", 1), ("createdAt", -1)]
            ),
            # For message pinning operations (nested array queries)
            conversations_collection.create_index(
                [("user_id", 1), ("messages.message_id", 1)]
            ),
            # For message pinning aggregations
            conversations_collection.create_index(
                [("user_id", 1), ("messages.pinned", 1)]
            ),
        )

    except Exception as e:
        logger.error(f"Error creating conversation indexes: {str(e)}")
        raise


async def create_todo_indexes():
    """Create indexes for todos collection."""
    try:
        # Create all todo indexes concurrently
        await asyncio.gather(
            # Primary compound index for user todos with sorting
            todos_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # Project-based queries
            todos_collection.create_index([("user_id", 1), ("project_id", 1)]),
            # Enhanced compound indexes for complex filtering
            todos_collection.create_index(
                [("user_id", 1), ("completed", 1), ("created_at", -1)]
            ),
            todos_collection.create_index(
                [("user_id", 1), ("priority", 1), ("created_at", -1)]
            ),
            todos_collection.create_index([("user_id", 1), ("due_date", 1)]),
            # For overdue queries (critical for performance) - sparse for due_date
            todos_collection.create_index(
                [("user_id", 1), ("due_date", 1), ("completed", 1)], sparse=True
            ),
            # For project + completion status queries
            todos_collection.create_index(
                [("user_id", 1), ("project_id", 1), ("completed", 1)]
            ),
            # For label-based filtering (sparse since not all todos have labels)
            todos_collection.create_index([("user_id", 1), ("labels", 1)], sparse=True),
            # Text search index for title and description
            todos_collection.create_index([("title", "text"), ("description", "text")]),
            # For subtask operations (sparse since not all todos have subtasks)
            todos_collection.create_index(
                [("user_id", 1), ("subtasks.id", 1)], sparse=True
            ),
        )

    except Exception as e:
        logger.error(f"Error creating todo indexes: {str(e)}")
        raise


async def create_project_indexes():
    """Create indexes for projects collection."""
    try:
        # Create all project indexes concurrently
        await asyncio.gather(
            # Primary compound index for user projects
            projects_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For default project lookup
            projects_collection.create_index([("user_id", 1), ("is_default", 1)]),
            # For project name searches
            projects_collection.create_index([("user_id", 1), ("name", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating project indexes: {str(e)}")
        raise


async def create_goal_indexes():
    """Create indexes for goals collection."""
    try:
        # Create all goal indexes concurrently
        await asyncio.gather(
            # Primary index for user goals
            goals_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For progress tracking
            goals_collection.create_index([("user_id", 1), ("progress", 1)]),
            # For todo integration queries
            goals_collection.create_index([("user_id", 1), ("todo_project_id", 1)]),
            goals_collection.create_index([("user_id", 1), ("todo_id", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating goal indexes: {str(e)}")
        raise


async def create_note_indexes():
    """Create indexes for notes collection."""
    try:
        # Create all note indexes concurrently
        await asyncio.gather(
            # For user-specific note queries
            notes_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For individual note lookups
            notes_collection.create_index([("user_id", 1), ("_id", 1)]),
            # For auto-created notes filtering (sparse since not all notes have this field)
            notes_collection.create_index(
                [("user_id", 1), ("auto_created", 1)], sparse=True
            ),
            # Text search index for content search
            notes_collection.create_index([("plaintext", "text"), ("title", "text")]),
        )

    except Exception as e:
        logger.error(f"Error creating note indexes: {str(e)}")
        raise


async def create_file_indexes():
    """Create indexes for files collection."""
    try:
        # Create all file indexes concurrently
        await asyncio.gather(
            # For user file queries
            files_collection.create_index([("user_id", 1), ("uploaded_at", -1)]),
            # For specific file lookups (critical)
            files_collection.create_index([("user_id", 1), ("file_id", 1)]),
            # For conversation-based file queries
            files_collection.create_index([("user_id", 1), ("conversation_id", 1)]),
            # For file type filtering
            files_collection.create_index([("user_id", 1), ("content_type", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating file indexes: {str(e)}")
        raise


async def create_mail_indexes():
    """Create indexes for mail collection."""
    try:
        # Create all mail indexes concurrently
        await asyncio.gather(
            # Compound unique index for user + message lookups (most common query pattern)
            mail_collection.create_index(
                [("user_id", 1), ("message_id", 1)], unique=True
            ),
            # For user-specific queries with sorting (e.g., listing emails by analysis date)
            mail_collection.create_index([("user_id", 1), ("analyzed_at", -1)]),
            # For user-specific importance filtering
            mail_collection.create_index(
                [("user_id", 1), ("is_important", 1), ("analyzed_at", -1)]
            ),
        )

    except Exception as e:
        logger.error(f"Error creating mail indexes: {str(e)}")
        raise


async def create_calendar_indexes():
    """Create indexes for calendar collection."""
    try:
        # Create all calendar indexes concurrently
        await asyncio.gather(
            # For user calendar preferences
            calendars_collection.create_index("user_id"),
            # For event queries
            calendars_collection.create_index([("user_id", 1), ("event_date", 1)]),
            # For calendar selection queries
            calendars_collection.create_index(
                [("user_id", 1), ("selected_calendars", 1)]
            ),
        )

    except Exception as e:
        logger.error(f"Error creating calendar indexes: {str(e)}")
        raise


async def create_blog_indexes():
    """Create indexes for blog collection."""
    try:
        # Create all blog indexes concurrently
        await asyncio.gather(
            # Unique slug index
            blog_collection.create_index("slug", unique=True),
            # Date-based sorting
            blog_collection.create_index([("date", -1)]),
            # Category filtering
            blog_collection.create_index("category"),
            # Author queries
            blog_collection.create_index("authors"),
            # Compound index for published blogs
            blog_collection.create_index([("date", -1), ("category", 1)]),
            # Text search index
            blog_collection.create_index(
                [
                    ("title", "text"),
                    ("content", "text"),
                    ("description", "text"),
                    ("tags", "text"),
                ]
            ),
        )

    except Exception as e:
        logger.error(f"Error creating blog indexes: {str(e)}")
        raise


async def create_notification_indexes():
    """Create indexes for notifications collection."""
    try:
        # Create all notification indexes concurrently
        await asyncio.gather(
            # For user-specific notifications
            notifications_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For unread notifications
            notifications_collection.create_index(
                [("user_id", 1), ("read", 1), ("created_at", -1)]
            ),
            # For notification type filtering
            notifications_collection.create_index([("user_id", 1), ("type", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating notification indexes: {str(e)}")
        raise


async def create_reminder_indexes():
    """Create indexes for the reminders collection."""
    try:
        await asyncio.gather(
            reminders_collection.create_index([("user_id", 1)]),
            reminders_collection.create_index([("status", 1)]),
            reminders_collection.create_index([("scheduled_at", 1)]),
            reminders_collection.create_index([("type", 1)]),
            reminders_collection.create_index([("user_id", 1), ("status", 1)]),
            reminders_collection.create_index([("status", 1), ("scheduled_at", 1)]),
            reminders_collection.create_index([("user_id", 1), ("type", 1)]),
        )
    except Exception as e:
        logger.error(f"Error creating reminder indexes: {e}")
        raise


async def create_workflow_indexes():
    """Create indexes for workflows collection for optimal query performance."""
    try:
        # Create all workflow indexes concurrently
        await asyncio.gather(
            # Primary compound index for user workflows with sorting (most critical)
            workflows_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For activation status queries
            workflows_collection.create_index([("user_id", 1), ("activated", 1)]),
            # For workflow listing with status and sorting
            workflows_collection.create_index(
                [("user_id", 1), ("activated", 1), ("created_at", -1)]
            ),
            # For execution history and monitoring queries
            workflows_collection.create_index(
                [("user_id", 1), ("last_executed_at", 1)]
            ),
            # For scheduled workflow queries (critical for scheduler)
            workflows_collection.create_index(
                [
                    ("activated", 1),
                    ("trigger_config.type", 1),
                    ("trigger_config.enabled", 1),
                ]
            ),
            workflows_collection.create_index(
                [
                    ("user_id", 1),
                    ("activated", 1),
                    ("trigger_config.type", 1),
                    ("trigger_config.enabled", 1),
                ]
            ),
            # Compound index for scheduled workflows with next run time
            workflows_collection.create_index(
                [
                    ("activated", 1),
                    ("trigger_config.type", 1),
                    ("trigger_config.enabled", 1),
                    ("trigger_config.next_run", 1),
                ]
            ),
            # For workflow execution status queries
            workflows_collection.create_index(
                [("user_id", 1), ("total_executions", 1)]
            ),
            workflows_collection.create_index(
                [("user_id", 1), ("successful_executions", 1)]
            ),
            # For workflow search and filtering by title
            workflows_collection.create_index([("user_id", 1), ("title", 1)]),
            # For performance monitoring queries
            workflows_collection.create_index([("user_id", 1), ("updated_at", -1)]),
            # Text search index for workflow content
            workflows_collection.create_index(
                [("title", "text"), ("description", "text"), ("goal", "text")]
            ),
            # For source-based queries (where workflows were created from)
            workflows_collection.create_index([("user_id", 1), ("source", 1)]),
            # Sparse index for workflow steps (only workflows with steps)
            workflows_collection.create_index("steps", sparse=True),
            # Sparse index for composio trigger IDs (for efficient webhook routing)
            workflows_collection.create_index(
                "trigger_config.composio_trigger_ids", sparse=True
            ),
            # Community workflows indexes
            workflows_collection.create_index([("is_public", 1), ("created_at", -1)]),
            workflows_collection.create_index([("created_by", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating workflow indexes: {str(e)}")
        raise


async def create_workflow_execution_indexes():
    """Create indexes for workflow_executions collection."""
    try:
        await asyncio.gather(
            workflow_executions_collection.create_index(
                [("workflow_id", 1), ("user_id", 1), ("started_at", -1)]
            ),
            workflow_executions_collection.create_index(
                [("user_id", 1), ("started_at", -1)]
            ),
            workflow_executions_collection.create_index("execution_id", unique=True),
            workflow_executions_collection.create_index(
                [("workflow_id", 1), ("status", 1)]
            ),
        )
    except Exception as e:
        logger.error(f"Error creating workflow execution indexes: {str(e)}")
        raise


async def create_payment_indexes():
    """Create indexes for payment-related collections."""
    try:
        # Create payment collection indexes
        await asyncio.gather(
            # Payment indexes - for successful payments only
            payments_collection.create_index("dodo_payment_id", unique=True),
            payments_collection.create_index("dodo_subscription_id", sparse=True),
            payments_collection.create_index("customer_email"),
            payments_collection.create_index("status"),
            payments_collection.create_index(
                [("customer_email", 1), ("created_at", -1)]
            ),
            payments_collection.create_index("webhook_processed_at", sparse=True),
            # Subscription indexes - for active subscriptions only
            subscriptions_collection.create_index("user_id"),
            subscriptions_collection.create_index("dodo_subscription_id", unique=True),
            subscriptions_collection.create_index("product_id"),
            subscriptions_collection.create_index("status"),
            subscriptions_collection.create_index([("user_id", 1), ("status", 1)]),
            subscriptions_collection.create_index([("user_id", 1), ("created_at", -1)]),
            subscriptions_collection.create_index("webhook_processed_at", sparse=True),
            # Plans indexes
            plans_collection.create_index("is_active"),
            plans_collection.create_index("dodo_product_id", sparse=True),
            plans_collection.create_index([("is_active", 1), ("amount", 1)]),
            plans_collection.create_index([("name", 1), ("duration", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating payment indexes: {str(e)}")
        raise


async def create_usage_indexes():
    """
    Create indexes for usage_snapshots collection for optimal query performance.
    Includes TTL index for automatic cleanup after 90 days.

    Query patterns:
    - Find latest usage by user_id (sorted by created_at desc)
    - Find usage history by user_id and date range
    - Automatic cleanup via TTL index
    """
    try:
        await asyncio.gather(
            # Primary query: get latest usage by user
            usage_snapshots_collection.create_index(
                [("user_id", 1), ("created_at", -1)], name="user_latest_usage"
            ),
            # Usage history queries by user and date range
            usage_snapshots_collection.create_index(
                [("user_id", 1), ("created_at", 1)], name="user_usage_history"
            ),
            # Hourly aggregation queries (for the new upsert strategy)
            usage_snapshots_collection.create_index(
                [("user_id", 1), ("snapshot_date", 1)], name="user_snapshot_hour"
            ),
            # TTL index for automatic cleanup after 90 days (7,776,000 seconds)
            usage_snapshots_collection.create_index(
                "created_at",
                name="created_at_ttl",
                expireAfterSeconds=7776000,  # 90 days
            ),
            # Plan type filtering
            usage_snapshots_collection.create_index(
                "plan_type", name="plan_type_filter"
            ),
        )

    except Exception as e:
        logger.error(f"Error creating usage indexes: {str(e)}")
        raise


async def create_ai_models_indexes():
    """
    Create indexes for ai_models collection for optimal query performance.

    Query patterns:
    - Find models by ID (primary lookup)
    - Find active models by plan availability
    - Find default models
    - Pricing lookups
    """
    try:
        await asyncio.gather(
            # Primary model lookup
            ai_models_collection.create_index("model_id", unique=True),
            # Active models filtering
            ai_models_collection.create_index("is_active"),
            # Default model lookup
            ai_models_collection.create_index([("is_default", 1), ("is_active", 1)]),
            # Plan availability queries
            ai_models_collection.create_index("available_in_plans"),
            # Combined active + plan queries (most common)
            ai_models_collection.create_index(
                [("is_active", 1), ("available_in_plans", 1)]
            ),
            # Pricing queries (for cost calculation)
            ai_models_collection.create_index(
                [("model_id", 1), ("is_active", 1)], name="model_pricing_lookup"
            ),
            # Provider filtering
            ai_models_collection.create_index("model_provider"),
            ai_models_collection.create_index("inference_provider"),
        )

    except Exception as e:
        logger.error(f"Error creating AI models indexes: {str(e)}")
        raise


async def _create_index_safe(collection, keys, **kwargs):
    """
    Create an index safely, handling IndexOptionsConflict gracefully.

    MongoDB raises IndexOptionsConflict (code 85) when an index with the same
    key pattern already exists but with a different name. This is fine - the
    index functionality exists, so we skip silently.
    """
    try:
        await collection.create_index(keys, **kwargs)
    except Exception as e:
        error_str = str(e)
        # IndexOptionsConflict (code 85) - index exists with different name
        if "IndexOptionsConflict" in error_str or "'code': 85" in error_str:
            return  # Silently skip - equivalent index already exists
        raise


async def create_integration_indexes():
    """
    Create indexes for integrations collection.

    Query patterns:
    - List all integrations (marketplace browsing)
    - Filter by source (platform vs custom)
    - Filter by category
    - Featured integrations lookup
    - Public custom integrations for marketplace
    """
    try:
        await asyncio.gather(
            # Primary unique index on integration_id
            _create_index_safe(
                integrations_collection,
                "integration_id",
                unique=True,
                name="integration_id_unique",
            ),
            # Source filtering (platform vs custom)
            _create_index_safe(integrations_collection, "source", name="source_1"),
            # Category filtering for marketplace browsing
            _create_index_safe(integrations_collection, "category", name="category_1"),
            # Featured integrations display
            _create_index_safe(
                integrations_collection,
                [("is_featured", 1), ("display_priority", -1)],
                name="featured_priority",
            ),
            # Public custom integrations for marketplace
            _create_index_safe(
                integrations_collection,
                [("source", 1), ("is_public", 1), ("created_at", -1)],
                name="source_public_created",
            ),
            # Creator lookup for custom integrations
            _create_index_safe(
                integrations_collection,
                "created_by",
                sparse=True,
                name="created_by_sparse",
            ),
            # Text search for integration discovery
            _create_index_safe(
                integrations_collection,
                [("name", "text"), ("description", "text")],
                name="text_search",
            ),
            # Community marketplace listing (public integrations sorted by popularity)
            _create_index_safe(
                integrations_collection,
                [("is_public", 1), ("clone_count", -1), ("published_at", -1)],
                name="public_popular",
            ),
        )

    except Exception as e:
        logger.error(f"Error creating integration indexes: {str(e)}")
        raise


async def create_user_integration_indexes():
    """
    Create indexes for user_integrations collection.

    Query patterns:
    - Get all integrations for a user
    - Get user's connected integrations only
    - Check if user has added a specific integration
    """
    try:
        await asyncio.gather(
            # Primary compound index for user's integrations
            _create_index_safe(
                user_integrations_collection,
                [("user_id", 1), ("integration_id", 1)],
                unique=True,
                name="user_integration_unique",
            ),
            # User's integrations with status filtering
            _create_index_safe(
                user_integrations_collection,
                [("user_id", 1), ("status", 1), ("created_at", -1)],
                name="user_status_created",
            ),
            # Recent additions lookup
            _create_index_safe(
                user_integrations_collection,
                [("user_id", 1), ("created_at", -1)],
                name="user_created",
            ),
            # Connected integrations only (for tool loading)
            _create_index_safe(
                user_integrations_collection,
                [("user_id", 1), ("status", 1)],
                name="user_status",
            ),
        )

    except Exception as e:
        logger.error(f"Error creating user integration indexes: {str(e)}")
        raise


async def create_device_token_indexes():
    """Create indexes for device_tokens collection for push notifications."""
    try:
        await asyncio.gather(
            # Primary lookup by user
            device_tokens_collection.create_index("user_id"),
            # Unique token constraint
            device_tokens_collection.create_index("token", unique=True),
            # For active token queries
            device_tokens_collection.create_index([("user_id", 1), ("is_active", 1)]),
        )

    except Exception as e:
        logger.error(f"Error creating device token indexes: {str(e)}")
        raise


async def get_index_status() -> Dict[str, List[str]]:
    """
    Get the current index status for all collections.
    Useful for monitoring and debugging index usage.

    Returns:
        Dict mapping collection names to lists of index names
    """
    try:
        collections = {
            "users": users_collection,
            "conversations": conversations_collection,
            "todos": todos_collection,
            "projects": projects_collection,
            "goals": goals_collection,
            "notes": notes_collection,
            "files": files_collection,
            "mail": mail_collection,
            "calendar": calendars_collection,
            "blog": blog_collection,
            "notifications": notifications_collection,
            "reminders": reminders_collection,
            "workflows": workflows_collection,
        }

        # Get all collection indexes concurrently
        async def get_collection_indexes(name: str, collection):
            try:
                indexes = await collection.list_indexes().to_list(length=None)
                return name, [idx.get("name", "unnamed") for idx in indexes]
            except Exception as e:
                logger.error(f"Failed to get indexes for {name}: {str(e)}")
                return name, [f"ERROR: {str(e)}"]

        # Execute all index status queries concurrently
        tasks = [
            get_collection_indexes(name, collection)
            for name, collection in collections.items()
        ]
        results = await asyncio.gather(*tasks)

        # Convert results to dictionary
        index_status = dict(results)

        return index_status

    except Exception as e:
        logger.error(f"Error getting index status: {str(e)}")
        return {"error": [str(e)]}


async def log_index_summary():
    """Log a summary of all collection indexes for monitoring purposes."""
    try:
        index_status = await get_index_status()

        logger.info("=== DATABASE INDEX SUMMARY ===")

        total_indexes = 0
        for collection_name, indexes in index_status.items():
            if not indexes or (len(indexes) == 1 and indexes[0].startswith("ERROR")):
                logger.warning(f"{collection_name}: No indexes or error")
            else:
                index_count = len(indexes)
                total_indexes += index_count
                logger.info(
                    f"INDEX CREATED: {collection_name}: {index_count} indexes - {', '.join(indexes)}"
                )

        logger.info(f"Total indexes across all collections: {total_indexes}")
        logger.info("=== END INDEX SUMMARY ===")

    except Exception as e:
        logger.error(f"Error logging index summary: {str(e)}")
