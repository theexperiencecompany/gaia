"""
ARQ worker tasks for executing scheduled tracked todos.

Handles:
- Acquiring Redis locks to prevent double-execution
- Retry logic with exponential backoff
- Workflow-based and agent-based execution paths
- Recurrence scheduling (re-enqueue after success)
- Safety-net cron for orphaned todos
"""

import random
from datetime import datetime, timedelta, timezone
from uuid import uuid5, NAMESPACE_URL
from zoneinfo import ZoneInfo

from bson import ObjectId
from croniter import croniter
from shared.py.wide_events import log, wide_task

from app.db.mongodb.collections import todos_collection
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.notification_service import notification_service
from app.services.model_service import get_user_selected_model
from app.services.user_service import get_user_by_id
from app.services.vfs.mongo_vfs import MongoVFS


MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [timedelta(hours=1), timedelta(hours=4)]
LOCK_TTL_SECONDS = 1800


async def execute_tracked_todo(ctx: dict, todo_id: str) -> str:
    """
    ARQ task: execute a single scheduled tracked todo.

    Acquires a Redis lock to prevent concurrent execution, then delegates
    to the retry/execution helper. The lock is always released in the
    finally block.
    """
    async with wide_task("execute_tracked_todo", todo_id=todo_id):
        log.info(f"execute_tracked_todo: starting for todo {todo_id}")

        # Deferred import to avoid circular dependency
        from app.utils.redis_utils import RedisPoolManager

        pool = await RedisPoolManager.get_pool()
        lock_key = f"gaia_todo_exec:{todo_id}"

        acquired = await pool.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            log.info(f"execute_tracked_todo: lock held, skipping todo {todo_id}")
            return f"skipped:{todo_id} (lock held)"

        try:
            return await _execute_todo_with_retry(ctx, todo_id, pool)
        finally:
            await pool.delete(lock_key)


async def _execute_todo_with_retry(ctx: dict, todo_id: str, pool) -> str:
    """
    Fetch the todo document, run the appropriate execution path, and
    handle retry / recurrence logic on the result.
    """
    doc = await todos_collection.find_one({"_id": ObjectId(todo_id)})
    if not doc:
        log.warning(f"_execute_todo_with_retry: todo {todo_id} not found")
        return f"not_found:{todo_id}"

    if doc.get("completed"):
        log.info(f"_execute_todo_with_retry: todo {todo_id} already completed")
        return f"completed:{todo_id}"

    user_id: str = doc.get("user_id", "")
    retry_count: int = doc.get("gaia_retry_count", 0)

    try:
        await _run_execution(doc, user_id)

        # Reset retry counter on success
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id)},
            {"$set": {"gaia_retry_count": 0, "updated_at": datetime.now(timezone.utc)}},
        )

        # Re-enqueue if recurring
        if doc.get("recurrence"):
            next_run = _compute_next_run(doc["recurrence"])
            if next_run:
                await todos_collection.update_one(
                    {"_id": ObjectId(todo_id)},
                    {"$set": {"scheduled_at": next_run, "updated_at": datetime.now(timezone.utc)}},
                )
                await pool.enqueue_job(
                    "execute_tracked_todo",
                    todo_id,
                    _defer_until=next_run,
                )
                log.info(f"_execute_todo_with_retry: re-enqueued todo {todo_id} at {next_run}")

        return f"success:{todo_id}"

    except Exception as exc:
        log.exception(f"_execute_todo_with_retry: execution failed for todo {todo_id}: {exc}")
        new_retry_count = retry_count + 1
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id)},
            {"$set": {"gaia_retry_count": new_retry_count, "updated_at": datetime.now(timezone.utc)}},
        )

        if new_retry_count >= MAX_RETRY_ATTEMPTS:
            await _mark_todo_failed(todo_id, user_id, doc)
            return f"failed:{todo_id} (max retries reached)"

        # Compute backoff delay
        backoff_index = min(new_retry_count - 1, len(RETRY_BACKOFF) - 1)
        backoff = RETRY_BACKOFF[backoff_index]
        next_attempt = datetime.now(timezone.utc) + backoff
        await pool.enqueue_job(
            "execute_tracked_todo",
            todo_id,
            _defer_until=next_attempt,
        )
        log.info(
            f"_execute_todo_with_retry: re-enqueued todo {todo_id} for retry at {next_attempt} "
            f"(attempt {new_retry_count}/{MAX_RETRY_ATTEMPTS})"
        )
        return f"retry:{todo_id} (attempt {new_retry_count})"


async def _run_execution(doc: dict, user_id: str) -> None:
    """
    Dispatch execution to the correct path:
    - If the todo has a workflow_id, queue the workflow.
    - Otherwise, run the agent directly.
    """
    workflow_id: str | None = doc.get("workflow_id")

    if workflow_id:
        # Deferred import to avoid circular dependency
        from app.services.workflow.queue_service import WorkflowQueueService

        context = {
            "trigger_type": "scheduled_todo",
            "todo_id": str(doc["_id"]),
        }
        await WorkflowQueueService.queue_workflow_execution(workflow_id, user_id, context)
        log.info(f"_run_execution: queued workflow {workflow_id} for todo {doc['_id']}")
    else:
        await _execute_via_agent(doc, user_id)


async def _execute_via_agent(doc: dict, user_id: str) -> str:
    """
    Execute the todo using call_agent_silent directly (no workflow needed).

    Returns the first 200 chars of the agent response.
    """
    # Deferred import to avoid circular dependency
    from app.agents.core.agent import call_agent_silent

    todo_id = str(doc["_id"])

    # Fetch full user record for timezone and model config
    try:
        user_data = await get_user_by_id(user_id)
        if user_data:
            user_data["user_id"] = user_id
            user_tz = ZoneInfo(user_data.get("timezone", "UTC"))
        else:
            user_data = {"user_id": user_id}
            user_tz = ZoneInfo("UTC")
        user_time = datetime.now(user_tz)
    except Exception as exc:
        log.warning(f"_execute_via_agent: could not fetch user {user_id}: {exc}")
        user_data = {"user_id": user_id}
        user_time = datetime.now(timezone.utc)

    user_model_config = None
    try:
        user_model_config = await get_user_selected_model(user_id)
    except Exception as exc:
        log.warning(f"_execute_via_agent: could not get user model config: {exc}")

    # Read canvas content from VFS if a path is stored on the todo
    canvas_content: str | None = None
    vfs_path: str | None = doc.get("vfs_path")
    if vfs_path:
        try:
            canvas_content = await MongoVFS().read(path=vfs_path, user_id=user_id)
        except Exception as exc:
            log.warning(f"_execute_via_agent: could not read VFS canvas at {vfs_path}: {exc}")

    # Build prompt
    title: str = doc.get("title", "Untitled Todo")
    description: str = doc.get("description", "")
    prompt_parts = [f"Execute the following scheduled task: {title}"]
    if description:
        prompt_parts.append(f"Details: {description}")
    if canvas_content:
        prompt_parts.append(f"Canvas context:\n{canvas_content}")
    prompt = "\n\n".join(prompt_parts)

    # Generate a stable conversation_id from the todo_id so the agent
    # has thread continuity across retries without persisting a separate
    # conversation document. Using uuid5 (NAMESPACE_URL) for determinism.
    conversation_id = str(uuid5(NAMESPACE_URL, f"todo_execution:{todo_id}"))

    request = MessageRequestWithHistory(
        message=prompt,
        messages=[],
        fileIds=[],
        fileData=[],
        selectedTool=None,
    )

    trigger_context = {
        "trigger_type": "scheduled_todo",
        "todo_id": todo_id,
        "todo_title": title,
    }

    complete_message, _tool_data = await call_agent_silent(
        request=request,
        conversation_id=conversation_id,
        user=user_data,
        user_time=user_time,
        user_model_config=user_model_config,
        trigger_context=trigger_context,
    )

    log.info(f"_execute_via_agent: agent completed for todo {todo_id}")
    return complete_message[:200] if complete_message else ""


async def _mark_todo_failed(todo_id: str, user_id: str, doc: dict) -> None:
    """
    Mark the todo as permanently failed by adding a 'failed' label,
    then send an in-app notification to the user.
    """
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id)},
        {
            "$addToSet": {"labels": "failed"},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )
    log.info(f"_mark_todo_failed: marked todo {todo_id} as failed")

    title: str = doc.get("title", "Untitled Todo")
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.ERROR,
                content=NotificationContent(
                    title=f"Scheduled Task Failed: {title}",
                    body=(
                        f"Your scheduled task '{title}' could not be completed after "
                        f"{MAX_RETRY_ATTEMPTS} attempts. Please check the task and try again."
                    ),
                ),
                channels=[
                    ChannelConfig(channel_type="inapp", enabled=True, priority=1)
                ],
                metadata={
                    "todo_id": todo_id,
                    "retry_count": MAX_RETRY_ATTEMPTS,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(f"_mark_todo_failed: could not send failure notification: {notify_exc}")


def _compute_next_run(recurrence: str) -> datetime | None:
    """
    Compute the next scheduled run time from a recurrence string.

    Supports named shortcuts:
    - "daily"    → +1 day
    - "weekly"   → +7 days
    - "every_4h" → +4 hours
    - "every_1h" → +1 hour

    Falls back to croniter for cron expressions (e.g. "0 9 * * *").
    Returns None if the recurrence string is unrecognised.
    """
    now = datetime.now(timezone.utc)
    shortcuts: dict[str, timedelta] = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "every_4h": timedelta(hours=4),
        "every_1h": timedelta(hours=1),
    }

    if recurrence in shortcuts:
        return now + shortcuts[recurrence]

    # Try cron expression
    try:
        cron = croniter(recurrence, now)
        next_dt: datetime = cron.get_next(datetime)
        # croniter returns naive datetimes; attach UTC
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=timezone.utc)
        return next_dt
    except Exception:
        log.warning(f"_compute_next_run: unrecognised recurrence expression '{recurrence}'")
        return None


async def safety_net_check_orphaned_todos(ctx: dict) -> str:
    """
    Cron safety net: find scheduled tracked todos that should have run but
    were never picked up (e.g. worker was down, job was lost).

    Queries todos where:
    - scheduled_at <= now
    - completed = False
    - labels includes "gaia-tracked"
    - gaia_retry_count < MAX_RETRY_ATTEMPTS

    For each, checks whether the execution lock already exists; if not,
    re-enqueues with a random 0–60 second jitter to spread load.
    """
    # Deferred import to avoid circular dependency
    from app.utils.redis_utils import RedisPoolManager

    async with wide_task("safety_net_check_orphaned_todos"):
        now = datetime.now(timezone.utc)
        log.info("safety_net_check_orphaned_todos: scanning for orphaned todos")

        cursor = todos_collection.find(
            {
                "scheduled_at": {"$lte": now},
                "completed": False,
                "labels": "gaia-tracked",
                "gaia_retry_count": {"$lt": MAX_RETRY_ATTEMPTS},
            }
        )

        pool = await RedisPoolManager.get_pool()
        re_enqueued = 0
        skipped = 0

        async for doc in cursor:
            todo_id = str(doc["_id"])
            lock_key = f"gaia_todo_exec:{todo_id}"

            lock_exists = await pool.exists(lock_key)
            if lock_exists:
                skipped += 1
                continue

            # Random jitter: 0–60 seconds
            jitter_seconds = random.randint(0, 60)  # nosec B311 — non-crypto scheduling jitter
            run_at = now + timedelta(seconds=jitter_seconds)
            await pool.enqueue_job("execute_tracked_todo", todo_id, _defer_until=run_at)
            re_enqueued += 1
            log.info(f"safety_net_check_orphaned_todos: re-enqueued todo {todo_id} at {run_at}")

        log.info(
            f"safety_net_check_orphaned_todos: done — re_enqueued={re_enqueued} skipped={skipped}"
        )
        return f"re_enqueued:{re_enqueued} skipped:{skipped}"
