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
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.errors import OperationFailure

from app.constants.log_tags import LogTag
from app.db.mongodb.collections import get_async_collection
from app.db.repositories.integrations import integration_repository
from shared.py.wide_events import log

# Mirrors pymongo's private `_IndexKeyHint` (pymongo.operations) — the shape
# every `create_index` call in this module actually passes: a single field
# name, or an ordered list of (field, direction | "text") pairs.
IndexKeys = str | list[tuple[str, int | str]]


async def create_all_indexes() -> None:
    """Create all database indexes. Called during application startup."""
    try:
        log.set(db={"operation": "create_indexes", "collection": "all"})
        log.info(f"{LogTag.MONGO} Starting comprehensive database index creation...")

        # Create all indexes concurrently for better performance
        index_tasks = [
            create_user_indexes(),
            create_conversation_indexes(),
            create_todo_indexes(),
            create_project_indexes(),
            create_note_indexes(),
            create_file_indexes(),
            create_mail_indexes(),
            create_calendar_indexes(),
            create_blog_indexes(),
            create_notification_indexes(),
            create_reminder_indexes(),
            create_workflow_indexes(),
            create_payment_indexes(),
            create_processed_webhook_indexes(),
            create_usage_indexes(),
            create_ai_models_indexes(),
            create_integration_indexes(),
            create_user_integration_indexes(),
            create_integration_instructions_indexes(),
            create_device_token_indexes(),
            create_installed_skills_indexes(),
            create_workflow_execution_indexes(),
            create_bot_session_indexes(),
            create_e2b_sandbox_indexes(),
            create_hil_approvals_indexes(),
            create_pending_platform_registration_indexes(),
        ]

        # Execute all index creation tasks concurrently
        results = await asyncio.gather(*index_tasks, return_exceptions=True)

        collection_names = [
            "users",
            "conversations",
            "todos",
            "projects",
            "notes",
            "files",
            "mail",
            "calendar",
            "blog",
            "notifications",
            "reminders",
            "workflows",
            "payments",
            "processed_webhooks",
            "usage",
            "ai_models",
            "integrations",
            "user_integrations",
            "integration_instructions",
            "device_tokens",
            "skills",
            "workflow_executions",
            "bot_sessions",
            "e2b_sandboxes",
            "hil_approvals",
            "pending_platform_registrations",
        ]

        index_results = {}
        for i, (collection_name, result) in enumerate(zip(collection_names, results)):
            if isinstance(result, Exception):
                log.error(
                    f"{LogTag.MONGO} Failed to create indexes for collection",
                    collection_name=collection_name,
                    result=result,
                )
                index_results[collection_name] = f"FAILED: {result!s}"
            else:
                index_results[collection_name] = "SUCCESS"

        # Log summary
        successful = sum(1 for result in index_results.values() if result == "SUCCESS")
        total = len(index_results)

        log.info(
            f"{LogTag.MONGO} Database index creation completed",
            successful=successful,
            total=total,
        )

        # Log any failures
        failed_collections = [name for name, result in index_results.items() if result != "SUCCESS"]
        if failed_collections:
            log.warning(
                f"{LogTag.MONGO} Failed to create indexes for collections",
                failed_collections=failed_collections,
            )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Critical error during database index creation",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_user_indexes() -> None:
    """Create indexes for users collection."""
    users_collection = get_async_collection("users")
    try:
        # Create all user indexes concurrently
        await asyncio.gather(
            # Email unique index (primary lookup method)
            users_collection.create_index("email", unique=True),
            # Onboarding status with creation date
            users_collection.create_index([("onboarding.completed", 1), ("created_at", -1)]),
            # Cache cleanup index (sparse since not all users have cached_at)
            users_collection.create_index("cached_at", sparse=True),
            # Activity tracking index for inactive user queries
            users_collection.create_index("last_active_at", sparse=True),
            # Inactive email tracking index (sparse since not all users have this field)
            users_collection.create_index("last_inactive_email_sent", sparse=True),
            # Platform links indexes for bot authentication (unique + sparse: only bot users have these,
            # and a single platform account must not be linked to multiple GAIA users)
            users_collection.create_index("platform_links.discord.id", unique=True, sparse=True),
            users_collection.create_index("platform_links.slack.id", unique=True, sparse=True),
            users_collection.create_index("platform_links.telegram.id", unique=True, sparse=True),
            users_collection.create_index("platform_links.whatsapp.id", unique=True, sparse=True),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating user indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_conversation_indexes() -> None:
    """Create indexes for conversations collection."""
    conversations_collection = get_async_collection("conversations")
    try:
        # Create all conversation indexes concurrently
        await asyncio.gather(
            # Primary compound index for user conversations with sorting (most critical)
            conversations_collection.create_index([("user_id", 1), ("createdAt", -1)]),
            # For specific conversation lookups (extremely critical for performance)
            conversations_collection.create_index([("user_id", 1), ("conversation_id", 1)]),
            # For starred conversations queries
            conversations_collection.create_index(
                [("user_id", 1), ("starred", 1), ("createdAt", -1)]
            ),
            # For message pinning operations (nested array queries)
            conversations_collection.create_index([("user_id", 1), ("messages.message_id", 1)]),
            # For message pinning aggregations
            conversations_collection.create_index([("user_id", 1), ("messages.pinned", 1)]),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating conversation indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_todo_indexes() -> None:
    """Create indexes for todos collection."""
    todos_collection = get_async_collection("todos")
    try:
        # Create all todo indexes concurrently
        await asyncio.gather(
            # Primary compound index for user todos with sorting
            todos_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # Project-based queries
            todos_collection.create_index([("user_id", 1), ("project_id", 1)]),
            # Enhanced compound indexes for complex filtering
            todos_collection.create_index([("user_id", 1), ("completed", 1), ("created_at", -1)]),
            todos_collection.create_index([("user_id", 1), ("priority", 1), ("created_at", -1)]),
            todos_collection.create_index([("user_id", 1), ("due_date", 1)]),
            # For overdue queries (critical for performance) - sparse for due_date
            todos_collection.create_index(
                [("user_id", 1), ("due_date", 1), ("completed", 1)], sparse=True
            ),
            # For project + completion status queries
            todos_collection.create_index([("user_id", 1), ("project_id", 1), ("completed", 1)]),
            # For label-based filtering (sparse since not all todos have labels)
            todos_collection.create_index([("user_id", 1), ("labels", 1)], sparse=True),
            # Text search index for title and description
            todos_collection.create_index([("title", "text"), ("description", "text")]),
            # For subtask operations (sparse since not all todos have subtasks)
            todos_collection.create_index([("user_id", 1), ("subtasks.id", 1)], sparse=True),
            # For workflow_id lookups (sparse — most todos won't have workflow_id)
            todos_collection.create_index(
                [("user_id", 1), ("workflow_id", 1)], sparse=True, name="user_workflow"
            ),
            # For date range + created_at sort queries
            todos_collection.create_index(
                [("user_id", 1), ("due_date", 1), ("created_at", -1)],
                sparse=True,
                name="user_due_created",
            ),
            # For completed + due_date queries (overdue/today filters)
            todos_collection.create_index(
                [("user_id", 1), ("completed", 1), ("due_date", 1)],
                name="user_completed_due",
            ),
            # For project + due_date queries
            todos_collection.create_index(
                [("user_id", 1), ("project_id", 1), ("due_date", 1)],
                name="user_project_due",
            ),
            # For tracked-todo cron sweeps (safety-net + maintenance). Both
            # scan by gaia-tracked label + completion, then range on
            # scheduled_at / gaia_retry_count. ESR ordering: equality fields
            # first (labels, completed), then range fields.
            todos_collection.create_index(
                [
                    ("labels", 1),
                    ("completed", 1),
                    ("scheduled_at", 1),
                    ("gaia_retry_count", 1),
                ],
                name="tracked_sweep",
            ),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating todo indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_project_indexes() -> None:
    """Create indexes for projects collection."""
    projects_collection = get_async_collection("projects")
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
        log.error(
            f"{LogTag.MONGO} Error creating project indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_note_indexes() -> None:
    """Create indexes for notes collection."""
    notes_collection = get_async_collection("notes")
    try:
        # Create all note indexes concurrently
        await asyncio.gather(
            # For user-specific note queries
            notes_collection.create_index([("user_id", 1), ("created_at", -1)]),
            # For individual note lookups
            notes_collection.create_index([("user_id", 1), ("_id", 1)]),
            # For auto-created notes filtering (sparse since not all notes have this field)
            notes_collection.create_index([("user_id", 1), ("auto_created", 1)], sparse=True),
            # Text search index for content search
            notes_collection.create_index([("plaintext", "text"), ("title", "text")]),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating note indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_file_indexes() -> None:
    """Create indexes for files collection."""
    files_collection = get_async_collection("files")
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
        log.error(
            f"{LogTag.MONGO} Error creating file indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_mail_indexes() -> None:
    """Create indexes for mail collection."""
    mail_collection = get_async_collection("mail")
    try:
        # Create all mail indexes concurrently
        await asyncio.gather(
            # Unique index for email IDs
            mail_collection.create_index([("user_id", 1)]),
            # For thread-based queries
            mail_collection.create_index([("message_id", 1)]),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating mail indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_calendar_indexes() -> None:
    """Create indexes for calendar collection."""
    calendars_collection = get_async_collection("calendar")
    try:
        # Create all calendar indexes concurrently
        await asyncio.gather(
            # For user calendar preferences
            calendars_collection.create_index("user_id"),
            # For event queries
            calendars_collection.create_index([("user_id", 1), ("event_date", 1)]),
            # For calendar selection queries
            calendars_collection.create_index([("user_id", 1), ("selected_calendars", 1)]),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating calendar indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_blog_indexes() -> None:
    """Create indexes for blog collection."""
    blog_collection = get_async_collection("blog")
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
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating blog indexes", error=str(e), error_type=type(e).__name__
        )
        raise


async def create_notification_indexes() -> None:
    """Create indexes for notifications collection."""
    notifications_collection = get_async_collection("notifications")
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
        log.error(
            f"{LogTag.MONGO} Error creating notification indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_reminder_indexes() -> None:
    """Create indexes for the reminders collection."""
    reminders_collection = get_async_collection("reminders")
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
        log.error(
            f"{LogTag.MONGO} Error creating reminder indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_workflow_indexes() -> None:
    """Create indexes for workflows collection for optimal query performance."""
    workflows_collection = get_async_collection("workflows")
    try:
        # Drop the old non-unique slug index if present so the partial-unique
        # replacement below can take over. Mongo error code 27 = IndexNotFound.
        try:
            await workflows_collection.drop_index("slug_public_idx")
        except OperationFailure as e:
            if e.code != 27:
                raise

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
            workflows_collection.create_index([("user_id", 1), ("last_executed_at", 1)]),
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
            workflows_collection.create_index([("user_id", 1), ("total_executions", 1)]),
            workflows_collection.create_index([("user_id", 1), ("successful_executions", 1)]),
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
            workflows_collection.create_index("trigger_config.composio_trigger_ids", sparse=True),
            # Community workflows indexes
            workflows_collection.create_index([("is_public", 1), ("created_at", -1)]),
            workflows_collection.create_index([("created_by", 1)]),
            # Partial unique index to prevent duplicate system workflows per user
            # Only applies to documents where system_workflow_key is set
            workflows_collection.create_index(
                [("user_id", 1), ("system_workflow_key", 1)],
                unique=True,
                partialFilterExpression={"system_workflow_key": {"$type": 2}},
            ),
        )

        # Partial-unique index on slug for public workflows. Built outside
        # the gather so a pre-existing duplicate (legacy data) only logs a
        # warning instead of crashing startup — operators can de-dup and
        # restart to reapply.
        try:
            await workflows_collection.create_index(
                [("slug", 1)],
                unique=True,
                partialFilterExpression={"is_public": True, "slug": {"$type": 2}},
                name="slug_public_unique_idx",
            )
        except OperationFailure as e:
            log.warning(
                f"{LogTag.MONGO} Failed to create slug_public_unique_idx: . Likely duplicate public slugs in workflows; de-dup and restart.",
                error=str(e),
                error_type=type(e).__name__,
            )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating workflow indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_workflow_execution_indexes() -> None:
    """Create indexes for workflow_executions collection."""
    workflow_executions_collection = get_async_collection("workflow_executions")
    try:
        await asyncio.gather(
            workflow_executions_collection.create_index(
                [("workflow_id", 1), ("user_id", 1), ("started_at", -1)]
            ),
            workflow_executions_collection.create_index([("user_id", 1), ("started_at", -1)]),
            workflow_executions_collection.create_index("execution_id", unique=True),
            workflow_executions_collection.create_index([("workflow_id", 1), ("status", 1)]),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating workflow execution indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_payment_indexes() -> None:
    """Create indexes for payment-related collections."""
    payments_collection = get_async_collection("payments")
    plans_collection = get_async_collection("subscription_plans")
    subscriptions_collection = get_async_collection("subscriptions")
    try:
        # Create payment collection indexes
        await asyncio.gather(
            # Payment indexes - for successful payments only
            payments_collection.create_index("dodo_payment_id", unique=True),
            payments_collection.create_index("dodo_subscription_id", sparse=True),
            payments_collection.create_index("customer_email"),
            payments_collection.create_index("status"),
            payments_collection.create_index([("customer_email", 1), ("created_at", -1)]),
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
        log.error(
            f"{LogTag.MONGO} Error creating payment indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_processed_webhook_indexes() -> None:
    """
    Create indexes for processed_webhooks collection for idempotency.

    - Unique index for idempotency check
    - TTL index for automatic cleanup
    """
    processed_webhooks_collection = get_async_collection("processed_webhooks")
    try:
        await asyncio.gather(
            # Unique index on webhook_id - required for idempotency
            processed_webhooks_collection.create_index("webhook_id", unique=True),
            # TTL index to auto-delete old records after 30 days
            processed_webhooks_collection.create_index(
                "processed_at",
                expireAfterSeconds=2592000,  # 30 days
            ),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating processed webhook indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_pending_platform_registration_indexes() -> None:
    """
    Create indexes for the pending_platform_registrations collection.

    - Unique on (platform, platform_user_id): one account per handle
    - (user_id, platform): the per-user lookup on connect, link and unlink
    - created_at: the range scan the abandoned-registration sweep runs
    """
    pending_registrations_collection = get_async_collection("pending_platform_registrations")
    try:
        await asyncio.gather(
            pending_registrations_collection.create_index(
                [("platform", 1), ("platform_user_id", 1)], unique=True
            ),
            pending_registrations_collection.create_index([("user_id", 1), ("platform", 1)]),
            pending_registrations_collection.create_index("created_at"),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating pending platform registration indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_usage_indexes() -> None:
    """
    Create indexes for the usage_snapshots and usage_daily collections.
    Includes TTL index for automatic snapshot cleanup after 90 days.

    Query patterns:
    - Find latest usage by user_id (sorted by created_at desc)
    - Find usage history by user_id and date range
    - Heatmap: per-user trailing-window reads on usage_daily (user_id + date)
    - Percentile thresholds: cross-user aggregation on usage_daily (date range)
    - Automatic cleanup via TTL index
    """
    usage_daily_collection = get_async_collection("usage_daily")
    usage_snapshots_collection = get_async_collection("usage_snapshots")
    try:
        await asyncio.gather(
            # Heatmap upsert key + per-user range reads (unique per user-day)
            usage_daily_collection.create_index(
                [("user_id", 1), ("date", 1)], unique=True, name="user_day_unique"
            ),
            # Cross-user percentile threshold aggregation ($match on date range)
            usage_daily_collection.create_index("date", name="daily_date_range"),
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
            usage_snapshots_collection.create_index("plan_type", name="plan_type_filter"),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating usage indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_ai_models_indexes() -> None:
    """
    Create indexes for ai_models collection for optimal query performance.

    Query patterns:
    - Find models by ID (primary lookup)
    - Find active models by plan availability
    - Find default models
    - Pricing lookups
    """
    ai_models_collection = get_async_collection("ai_models")
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
            ai_models_collection.create_index([("is_active", 1), ("available_in_plans", 1)]),
            # Pricing queries (for cost calculation)
            ai_models_collection.create_index(
                [("model_id", 1), ("is_active", 1)], name="model_pricing_lookup"
            ),
            # Provider filtering
            ai_models_collection.create_index("model_provider"),
            ai_models_collection.create_index("inference_provider"),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating AI models indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def _create_index_safe(
    collection: AsyncIOMotorCollection[dict[str, Any]], keys: IndexKeys, **kwargs: Any
) -> None:
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


async def create_integration_indexes() -> None:
    """
    Create indexes for integrations collection.

    Query patterns:
    - List all integrations (marketplace browsing)
    - Filter by source (platform vs custom)
    - Filter by category
    - Featured integrations lookup
    - Public custom integrations for marketplace
    """
    integrations_collection = get_async_collection("integrations")
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
            # Slug-based lookup for public integrations (sparse: only published have slugs)
            _create_index_safe(
                integrations_collection,
                "slug",
                sparse=True,
                name="slug_sparse",
            ),
        )

        # Backfill slugs for existing public integrations that don't have one
        await _backfill_integration_slugs()

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating integration indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def _backfill_integration_slugs() -> None:
    """Populate slug field for public integrations missing it."""
    integrations_collection = get_async_collection("integrations")
    try:
        total_backfilled = 0
        while True:
            cursor = integrations_collection.find(
                {"is_public": True, "slug": {"$exists": False}},
                {"integration_id": 1, "name": 1, "category": 1},
            )
            docs = await cursor.to_list(length=500)
            if not docs:
                break

            log.info(
                f"{LogTag.MONGO} Backfilling slugs for public integrations", docs_count=len(docs)
            )
            for doc in docs:
                slug = await integration_repository.ensure_unique_slug(
                    name=doc.get("name", ""),
                    category=doc.get("category", "custom"),
                    integration_id=doc["integration_id"],
                )
                await integrations_collection.update_one(
                    {"integration_id": doc["integration_id"]},
                    {"$set": {"slug": slug}},
                )
            total_backfilled += len(docs)

        if total_backfilled:
            log.info(
                f"{LogTag.MONGO} Slug backfill complete: integrations updated",
                total_backfilled=total_backfilled,
            )
    except Exception as e:
        log.warning(
            f"{LogTag.MONGO} Slug backfill failed (non-fatal)",
            error=str(e),
            error_type=type(e).__name__,
        )


async def create_user_integration_indexes() -> None:
    """
    Create indexes for user_integrations collection.

    Query patterns:
    - Get all integrations for a user
    - Get user's connected integrations only
    - Check if user has added a specific integration
    """
    user_integrations_collection = get_async_collection("user_integrations")
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
        log.error(
            f"{LogTag.MONGO} Error creating user integration indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_integration_instructions_indexes() -> None:
    """
    Create indexes for integration_instructions collection.

    Query patterns:
    - Read one integration's instructions: user_id + integration_id (unique)
    - List all of a user's instructions for materialization
    """
    integration_instructions_collection = get_async_collection("integration_instructions")
    try:
        await _create_index_safe(
            integration_instructions_collection,
            [("user_id", 1), ("integration_id", 1)],
            unique=True,
            name="user_integration_instructions_unique",
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating integration instructions indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_device_token_indexes() -> None:
    """Create indexes for device_tokens collection for push notifications."""
    device_tokens_collection = get_async_collection("device_tokens")
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
        log.error(
            f"{LogTag.MONGO} Error creating device token indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_bot_session_indexes() -> None:
    """Create indexes for bot_sessions collection for optimal query performance and automatic cleanup."""
    bot_sessions_collection = get_async_collection("bot_sessions")
    try:
        await asyncio.gather(
            # Unique session key index (critical for session lookup)
            bot_sessions_collection.create_index("session_key", unique=True),
            # Compound index for platform user lookups
            bot_sessions_collection.create_index([("platform", 1), ("platform_user_id", 1)]),
            # Conversation ID index for conversation-based queries
            bot_sessions_collection.create_index("conversation_id"),
            # TTL index for automatic session cleanup after 30 days (2,592,000 seconds)
            bot_sessions_collection.create_index(
                "updated_at",
                expireAfterSeconds=2592000,  # 30 days
            ),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating bot session indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_installed_skills_indexes() -> None:
    """
    Create indexes for skills collection (flat schema).

    Query patterns:
    - Duplicate detection: user_id + name + target (unique)
    - Agent skills: enabled + target + $or[user_id, "system"] (get_skills_for_agent)
    - User listing: user_id + installed_at (list_skills)
    """
    skills_collection = get_async_collection("skills")
    try:
        await asyncio.gather(
            # Unique: one skill per name per target per user
            _create_index_safe(
                skills_collection,
                [
                    ("user_id", 1),
                    ("name", 1),
                    ("target", 1),
                ],
                unique=True,
                name="user_skill_name_target_unique",
            ),
            # Skills for an agent: target + enabled + user_id
            # Supports the unified $or query in get_skills_for_agent
            _create_index_safe(
                skills_collection,
                [
                    ("target", 1),
                    ("enabled", 1),
                    ("user_id", 1),
                ],
                name="target_enabled_user",
            ),
            # List all user skills sorted by install date
            _create_index_safe(
                skills_collection,
                [("user_id", 1), ("installed_at", -1)],
                name="user_installed_at",
            ),
        )

    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating installed_skills indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_hil_approvals_indexes() -> None:
    """Create indexes for the hil_approvals collection.

    (conversation_id, status) serves the pending-approval lookup that runs on
    every chat message while an approval is open; (status, expires_at) serves
    the timeout sweep's expiry pass. (status, resumed_at, decided_at) serves the
    sweep's crashed-resume pass (list_decided_unresumed): its resumed_at=null
    equality bound keeps the scan off the successfully-resumed records, which are
    the overwhelming majority and accumulate forever on this permanent audit
    trail. Without it that pass — running every minute — would scan the whole
    decided history. The collection is a permanent audit trail, so these queries
    must never fall back to a collection scan.
    """
    hil_approvals_collection = get_async_collection("hil_approvals")
    try:
        await asyncio.gather(
            hil_approvals_collection.create_index([("conversation_id", 1), ("status", 1)]),
            hil_approvals_collection.create_index([("status", 1), ("expires_at", 1)]),
            hil_approvals_collection.create_index(
                [("status", 1), ("resumed_at", 1), ("decided_at", 1)]
            ),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating hil_approvals indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise


async def create_e2b_sandbox_indexes() -> None:
    """
    Create indexes for e2b_sandboxes and e2b_warm_pool collections.

    Query patterns:
    - Sandbox lookup by user_id (1 sandbox per user, unique)
    - Sweeper: scan by last_used_at to find evictable sandboxes
    - Warm pool: claim a ready sandbox by (shard_id, state)
    """
    e2b_sandboxes_collection = get_async_collection("e2b_sandboxes")
    e2b_warm_pool_collection = get_async_collection("e2b_warm_pool")
    try:
        await asyncio.gather(
            e2b_sandboxes_collection.create_index("user_id", unique=True),
            e2b_sandboxes_collection.create_index("last_used_at"),
            e2b_sandboxes_collection.create_index([("shard_id", 1), ("state", 1)]),
            e2b_warm_pool_collection.create_index(
                [("shard_id", 1), ("state", 1), ("created_at", 1)]
            ),
            e2b_warm_pool_collection.create_index(
                "created_at",
                expireAfterSeconds=3600,  # 1 hour TTL on pool entries
            ),
        )
    except Exception as e:
        log.error(
            f"{LogTag.MONGO} Error creating e2b sandbox indexes",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise
