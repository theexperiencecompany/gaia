"""
ARQ worker tasks for executing scheduled tracked todos.

Handles:
- Acquiring Redis locks to prevent double-execution
- Retry logic with exponential backoff
- Workflow-based and agent-based execution paths
- Recurrence scheduling (re-enqueue after success)
- Safety-net cron for orphaned todos
"""

from datetime import UTC, datetime, timedelta
import random
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from bson import ObjectId
from croniter import croniter

from app.agents.core.agent import call_agent_silent
from app.db.mongodb.collections import todos_collection
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.model_service import get_default_model
from app.services.notification_service import notification_service
from app.services.todo_canvas_storage import read_canvas
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log, wide_task

MAX_RETRY_ATTEMPTS = 3
RETRY_BACKOFF = [timedelta(hours=1), timedelta(hours=4)]
LOCK_TTL_SECONDS = 1800


async def _load_user_with_tz(user_id: str) -> tuple[dict, ZoneInfo]:
    """Fetch user record once and resolve their IANA timezone.

    Mirrors the pattern used in workflow_tasks._execute_workflow_as_chat_session
    so we keep one consistent way to read a user's timezone in worker code.
    Returns (user_data with user_id populated, ZoneInfo). Falls back to UTC if
    the user record or timezone is missing.
    """
    try:
        user_data = await get_user_by_id(user_id)
        if user_data:
            user_data["user_id"] = user_id
            return user_data, ZoneInfo(user_data.get("timezone") or "UTC")
        return {"user_id": user_id}, ZoneInfo("UTC")
    except Exception as e:
        log.warning("tracked_todo.load_user_failed", user_id=user_id, error=str(e))
        return {"user_id": user_id}, ZoneInfo("UTC")


async def execute_tracked_todo(ctx: dict, todo_id: str) -> str:
    """
    ARQ task: execute a single scheduled tracked todo.

    Acquires a Redis lock to prevent concurrent execution, then delegates
    to the retry/execution helper. The lock is always released in the
    finally block.
    """
    async with wide_task("execute_tracked_todo", todo_id=todo_id):
        log.info("tracked_todo.execute_started", todo_id=todo_id)

        pool = await RedisPoolManager.get_pool()
        lock_key = f"gaia_todo_exec:{todo_id}"

        acquired = await pool.set(lock_key, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            log.info("tracked_todo.execute_lock_held", todo_id=todo_id)
            return f"skipped:{todo_id} (lock held)"

        try:
            return await _execute_todo_with_retry(todo_id, pool)
        finally:
            await pool.delete(lock_key)


async def _execute_todo_with_retry(todo_id: str, pool: Any) -> str:
    """
    Fetch the todo document, run the appropriate execution path, and
    handle retry / recurrence logic on the result.
    """
    doc = await todos_collection.find_one({"_id": ObjectId(todo_id)})
    if not doc:
        log.warning("tracked_todo.execute_not_found", todo_id=todo_id)
        return f"not_found:{todo_id}"

    if doc.get("completed"):
        log.info("tracked_todo.execute_already_completed", todo_id=todo_id)
        return f"completed:{todo_id}"

    # Skip expired todos — let maintenance sweep handle gracefully
    if doc.get("expires_at") and doc["expires_at"] <= datetime.now(UTC):
        log.info(
            "tracked_todo.execute_expired",
            todo_id=todo_id,
            expires_at=doc["expires_at"].isoformat(),
        )
        return f"expired:{todo_id}"

    # Skip failed todos — user must manually reset before re-execution
    if "failed" in doc.get("labels", []):
        log.info("tracked_todo.execute_marked_failed", todo_id=todo_id)
        return f"skipped:{todo_id} (marked failed)"

    user_id: str = doc.get("user_id", "")
    retry_count: int = doc.get("gaia_retry_count", 0)

    if not user_id:
        log.error("tracked_todo.execute_missing_user_id", todo_id=todo_id)
        return f"error:{todo_id} (missing user_id)"

    # Single user fetch per run — pattern matches workflow_tasks.py:416–427.
    # Reused for both agent execution (timezone/model config) and the next-run
    # computation below, so a tz change takes effect on the next fire without
    # an extra DB round-trip.
    user_data, user_tz = await _load_user_with_tz(user_id)

    try:
        await _run_execution(doc, user_id, user_data=user_data, user_tz=user_tz)

        # Reset retry counter on success
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id)},
            {"$set": {"gaia_retry_count": 0, "updated_at": datetime.now(UTC)}},
        )

        # Re-enqueue if recurring. Recurrence is always evaluated in the
        # user's stored timezone (looked up once at the top of this run).
        if doc.get("recurrence"):
            next_run = _compute_next_run(
                doc["recurrence"], str(user_tz), anchor=doc.get("scheduled_at")
            )
            if next_run:
                await todos_collection.update_one(
                    {"_id": ObjectId(todo_id)},
                    {
                        "$set": {
                            "scheduled_at": next_run,
                            "updated_at": datetime.now(UTC),
                        }
                    },
                )
                await pool.enqueue_job(
                    "execute_tracked_todo",
                    todo_id,
                    _defer_until=next_run,
                )
                log.info(
                    "tracked_todo.re_enqueued",
                    todo_id=todo_id,
                    next_run=next_run.isoformat(),
                )

        return f"success:{todo_id}"

    except Exception as exc:
        log.exception("tracked_todo.execution_failed", todo_id=todo_id, error=str(exc))
        new_retry_count = retry_count + 1
        await todos_collection.update_one(
            {"_id": ObjectId(todo_id)},
            {
                "$set": {
                    "gaia_retry_count": new_retry_count,
                    "updated_at": datetime.now(UTC),
                }
            },
        )

        if new_retry_count >= MAX_RETRY_ATTEMPTS:
            await _mark_todo_failed(todo_id, user_id, doc)
            return f"failed:{todo_id} (max retries reached)"

        # Compute backoff delay
        backoff_index = min(new_retry_count - 1, len(RETRY_BACKOFF) - 1)
        backoff = RETRY_BACKOFF[backoff_index]
        next_attempt = datetime.now(UTC) + backoff
        await pool.enqueue_job(
            "execute_tracked_todo",
            todo_id,
            _defer_until=next_attempt,
        )
        log.info(
            "tracked_todo.retry_enqueued",
            todo_id=todo_id,
            next_attempt=next_attempt.isoformat(),
            attempt=new_retry_count,
            max_attempts=MAX_RETRY_ATTEMPTS,
        )
        return f"retry:{todo_id} (attempt {new_retry_count})"


async def _run_execution(doc: dict, user_id: str, *, user_data: dict, user_tz: ZoneInfo) -> None:
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
        success = await WorkflowQueueService.queue_workflow_execution(workflow_id, user_id, context)
        if not success:
            raise RuntimeError(f"Failed to queue workflow {workflow_id} for todo {doc['_id']}")
        log.info(
            "tracked_todo.workflow_queued",
            workflow_id=workflow_id,
            todo_id=str(doc["_id"]),
        )
    else:
        await _execute_via_agent(doc, user_id, user_data=user_data, user_tz=user_tz)


async def _execute_via_agent(doc: dict, user_id: str, *, user_data: dict, user_tz: ZoneInfo) -> str:
    """
    Execute the todo using call_agent_silent directly (no workflow needed).

    Returns the first 200 chars of the agent response.
    """
    todo_id = str(doc["_id"])
    user_time = datetime.now(user_tz)

    user_model_config = None
    try:
        user_model_config = await get_default_model()
    except Exception as exc:
        log.warning("tracked_todo.model_config_failed", todo_id=todo_id, error=str(exc))

    # Read canvas content from the todo's Mongo-backed canvas field
    canvas_content: str | None = None
    try:
        canvas_content = await read_canvas(todo_id, user_id)
    except Exception as exc:
        log.warning(
            "tracked_todo.canvas_read_failed",
            todo_id=todo_id,
            error=str(exc),
        )

    # Read referenced canvases for institutional memory
    reference_context = ""
    ref_ids: list[str] = doc.get("references", [])
    if ref_ids:
        ref_parts: list[str] = []
        for ref_id in ref_ids[:5]:  # Cap at 5 to avoid context bloat
            try:
                ref_doc = await todos_collection.find_one({"_id": ObjectId(ref_id)})
                if ref_doc:
                    ref_canvas = await read_canvas(ref_id, user_id)
                    if ref_canvas and "## Learnings" in ref_canvas:
                        learnings_start = ref_canvas.index("## Learnings")
                        next_section = ref_canvas.find("\n## ", learnings_start + 1)
                        learnings = (
                            ref_canvas[learnings_start:next_section]
                            if next_section != -1
                            else ref_canvas[learnings_start:]
                        )
                        ref_parts.append(
                            f'From past todo "{ref_doc.get("title", "Unknown")}":\n{learnings.strip()}'
                        )
            except Exception as e:
                log.debug("execute_todo.reference_read_failed", ref_id=ref_id, error=str(e))
                continue
        if ref_parts:
            reference_context = (
                "\n\nPast experience (from similar completed todos):\n" + "\n\n".join(ref_parts)
            )

    # Build prompt
    title: str = doc.get("title", "Untitled Todo")
    description: str = doc.get("description", "")
    prompt_parts = [f"Execute the following scheduled task: {title}"]
    if description:
        prompt_parts.append(f"Details: {description}")
    if canvas_content:
        prompt_parts.append(f"Canvas context:\n{canvas_content}")
    if reference_context:
        prompt_parts.append(reference_context)
    prompt = "\n\n".join(prompt_parts)

    # Generate a fresh conversation_id for each execution to prevent
    # history accumulation in PostgreSQL. Each execution is independent.
    conversation_id = str(uuid4())

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
        "active_todo_id": todo_id,
        "execution_mode": "background",
    }

    # Structural paper trail — write a start marker to the canvas Timeline
    # BEFORE the agent runs, so the run leaves evidence even if the LLM forgets.
    short_conv = conversation_id[:8]
    start_iso = datetime.now(UTC).isoformat()
    await tracked_todo_service.append_canvas_timeline(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"▶ {start_iso} — scheduled run started (conversation_id={short_conv})",
    )

    complete_message: str = ""
    try:
        complete_message, _tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            user_time=user_time,
            user_model_config=user_model_config,
            trigger_context=trigger_context,
        )

        if complete_message and complete_message.startswith("Error when calling silent agent:"):
            raise RuntimeError(complete_message)
    except Exception as exc:
        # End marker: failure
        fail_iso = datetime.now(UTC).isoformat()
        await tracked_todo_service.append_canvas_timeline(
            todo_id=todo_id,
            user_id=user_id,
            entry=f"✗ {fail_iso} — scheduled run failed ({type(exc).__name__})",
        )
        raise

    # End marker: success
    end_iso = datetime.now(UTC).isoformat()
    summary = (complete_message or "").strip().replace("\n", " ")[:120]
    await tracked_todo_service.append_canvas_timeline(
        todo_id=todo_id,
        user_id=user_id,
        entry=f"✓ {end_iso} — scheduled run finished (summary={summary!r})",
    )

    log.info("tracked_todo.agent_completed", todo_id=todo_id)
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
            "$set": {"updated_at": datetime.now(UTC)},
        },
    )
    log.info("tracked_todo.marked_failed", todo_id=todo_id)

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
                metadata={
                    "todo_id": todo_id,
                    "retry_count": MAX_RETRY_ATTEMPTS,
                },
            )
        )
    except Exception as notify_exc:
        log.warning(
            "tracked_todo.failure_notification_failed",
            todo_id=todo_id,
            error=str(notify_exc),
        )


def _compute_next_run(
    recurrence: str,
    recurrence_tz: str | None = None,
    anchor: datetime | None = None,
) -> datetime | None:
    """
    Compute the next scheduled run time from a recurrence string.

    Evaluated in the user's timezone (recurrence_tz, IANA name). Returned as
    a UTC-aware datetime suitable for ARQ's _defer_until.

    Supports named shortcuts:
    - "daily"    → next occurrence at the anchor's local wall-clock time
    - "weekly"   → next occurrence at the anchor's local weekday + time
    - "every_4h" → +4 hours (interval)
    - "every_1h" → +1 hour (interval)

    "daily"/"weekly" are anchored to ``anchor`` (the original scheduled_at) so
    a late run does NOT drift the wall-clock time forward. The next fire keeps
    the anchor's local time-of-day and advances by whole days/weeks until it is
    strictly in the future. Without an anchor we fall back to a plain delta.

    Falls back to croniter for cron expressions (e.g. "0 9 * * *"), which are
    evaluated in recurrence_tz so "9am" means user-local 9am.
    Returns None if the recurrence string is unrecognised.
    """
    try:
        tz = ZoneInfo(recurrence_tz) if recurrence_tz else UTC
    except Exception:
        log.warning(
            "tracked_todo.next_run_invalid_tz",
            recurrence_tz=recurrence_tz,
            fallback="UTC",
        )
        tz = UTC

    now_utc = datetime.now(UTC)

    interval_shortcuts: dict[str, timedelta] = {
        "every_4h": timedelta(hours=4),
        "every_1h": timedelta(hours=1),
    }
    if recurrence in interval_shortcuts:
        # Intervals are deltas from "now" — drift is acceptable/expected.
        return now_utc + interval_shortcuts[recurrence]

    anchored_steps: dict[str, timedelta] = {
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
    }
    if recurrence in anchored_steps:
        step = anchored_steps[recurrence]
        if anchor is None:
            # No anchor available — fall back to a plain delta from now.
            return now_utc + step
        # Anchor to the original local wall-clock time. Advance whole
        # days/weeks from the anchor until strictly after now, preserving
        # the time-of-day (and weekday for weekly).
        anchor_local = anchor.astimezone(tz)
        next_local = anchor_local
        if next_local <= now_utc.astimezone(tz):
            elapsed = now_utc.astimezone(tz) - anchor_local
            steps_to_skip = (elapsed // step) + 1
            next_local = anchor_local + step * steps_to_skip
        return next_local.astimezone(UTC)

    # Cron expression — evaluate in the user's local timezone.
    try:
        now_local = now_utc.astimezone(tz)
        cron = croniter(recurrence, now_local)
        next_dt: datetime = cron.get_next(datetime)
        if next_dt.tzinfo is None:
            next_dt = next_dt.replace(tzinfo=tz)
        return next_dt.astimezone(UTC)
    except Exception:
        log.warning("tracked_todo.next_run_unrecognised", recurrence=recurrence)
        return None


async def safety_net_check_orphaned_todos(_ctx: dict) -> str:
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
    async with wide_task("safety_net_check_orphaned_todos"):
        now = datetime.now(UTC)
        log.info("tracked_todo.safety_net_scan_started")

        cursor = todos_collection.find(
            {
                "scheduled_at": {"$lte": now},
                "completed": False,
                "labels": "gaia-tracked",
                "gaia_retry_count": {"$lt": MAX_RETRY_ATTEMPTS},
            }
        ).limit(100)

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
            log.info(
                "tracked_todo.safety_net_re_enqueued",
                todo_id=todo_id,
                run_at=run_at.isoformat(),
            )

        log.info(
            "tracked_todo.safety_net_done",
            re_enqueued=re_enqueued,
            skipped=skipped,
        )
        return f"re_enqueued:{re_enqueued} skipped:{skipped}"
