"""ARQ tasks for proactive maintenance of tracked todos."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import random
from typing import Any
from uuid import uuid4

from bson import ObjectId

from app.agents.core.agent import call_agent_silent
from app.db.mongodb.collections import todos_collection
from app.models.message_models import MessageRequestWithHistory
from app.models.notification.notification_models import (
    ChannelConfig,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.services.model_service import get_default_model
from app.services.notification_service import notification_service
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.redis_utils import RedisPoolManager
from shared.py.wide_events import log, wide_task

DORMANT_DAYS = 5
WAITING_LABEL_MAX_DAYS = 8
NOTIFICATION_COOLDOWN_SECONDS = 86400  # 24 hours
MAX_HEALTH_CHECKS_PER_USER = 10  # Max agent health-check calls per user per sweep

BLOCKING_LABELS = {"waiting-for-reply", "waiting-for-approval", "blocked"}
UNTITLED_TODO_TITLE = "Untitled Todo"


async def maintenance_sweep_tracked_todos(_ctx: dict) -> str:
    """
    Cron task: scan active tracked todos and apply tiered staleness handling.

    Three tiers:
    - Expired: expires_at <= now → health-check agent decides archive or notify
    - Overdue: due_date <= now with no upcoming schedule → individual notification
    - Dormant: no update in DORMANT_DAYS days → health-check agent re-queues or bundles digest
    """
    async with wide_task("maintenance_sweep_tracked_todos"):
        now = datetime.now(UTC)
        log.info("maintenance_sweep.scan_started")

        pool = await RedisPoolManager.get_pool()

        cursor = todos_collection.find({"completed": False, "labels": "gaia-tracked"}).limit(200)

        expired: list[dict] = []
        overdue: list[dict] = []
        dormant: list[dict] = []

        async for doc in cursor:
            todo_id = str(doc["_id"])

            # Check 24h cooldown
            cooldown_key = f"gaia_maintenance_notified:{todo_id}"
            if await pool.exists(cooldown_key):
                continue

            if doc.get("expires_at") and doc["expires_at"] <= now:
                expired.append(doc)
            elif (
                doc.get("due_date")
                and doc["due_date"] <= now
                and not _has_upcoming_schedule(doc, now)
            ):
                overdue.append(doc)
            elif _is_dormant(doc, now):
                dormant.append(doc)

        # Cap at 20 per tier per sweep
        expired = expired[:20]
        overdue = overdue[:20]
        dormant = dormant[:20]

        archived = 0
        notified_expired = 0
        notified_overdue = 0
        requeued = 0
        needs_attention_todos: list[dict] = []

        # Track health-check calls per user to cap LLM usage per sweep
        health_checks_used: dict[str, int] = {}

        for doc in expired:
            uid = doc["user_id"]
            if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
                continue
            result = await _health_check_expired(doc, pool)
            health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
            if result == "archived":
                archived += 1
            else:
                notified_expired += 1

        for doc in overdue:
            await _notify_overdue(doc, pool)
            notified_overdue += 1

        for doc in dormant:
            uid = doc["user_id"]
            if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
                needs_attention_todos.append(doc)
                continue
            result = await _health_check_dormant(doc, pool)
            health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
            if result == "requeued":
                requeued += 1
            else:
                needs_attention_todos.append(doc)

        if needs_attention_todos:
            await _send_dormant_digest(needs_attention_todos)

        summary = (
            f"archived:{archived} notified_expired:{notified_expired} "
            f"notified_overdue:{notified_overdue} requeued:{requeued} "
            f"digest_items:{len(needs_attention_todos)}"
        )
        log.info(
            "maintenance_sweep.done",
            archived=archived,
            notified_expired=notified_expired,
            notified_overdue=notified_overdue,
            requeued=requeued,
            digest_items=len(needs_attention_todos),
        )
        return summary


def _has_upcoming_schedule(doc: dict, now: datetime) -> bool:
    """Return True if the todo has a genuine upcoming execution.

    A recurring todo with a stale scheduled_at (>2 days old) is NOT considered
    to have an upcoming schedule — it's likely orphaned.
    """
    scheduled_at: datetime | None = doc.get("scheduled_at")
    if scheduled_at and scheduled_at > now:
        return True

    # Recurrence alone doesn't count if the last scheduled_at is stale
    if doc.get("recurrence"):
        if scheduled_at:
            days_since_scheduled = (now - scheduled_at).days
            if days_since_scheduled <= 2:
                # Recently executed recurring todo — next run is coming
                return True
        # Recurrence set but scheduled_at is missing or stale — orphaned
        return False

    return False


def _is_dormant(doc: dict, now: datetime) -> bool:
    """
    Return True if the todo has been idle for more than DORMANT_DAYS.

    A todo is dormant when:
    - updated_at is more than DORMANT_DAYS ago
    - no upcoming schedule
    - no blocking label — UNLESS the blocking label has been there
      for more than WAITING_LABEL_MAX_DAYS days (at which point it
      is considered stuck and should surface)
    """
    updated_at: datetime | None = doc.get("updated_at")
    if not updated_at:
        return False

    idle_days = (now - updated_at).days
    if idle_days <= DORMANT_DAYS:
        return False

    if _has_upcoming_schedule(doc, now):
        return False

    labels: list[str] = doc.get("labels", [])
    blocking = BLOCKING_LABELS.intersection(labels)
    if not blocking:
        return True

    # Blocking label present — only surface if it has been stuck too long
    # Use idle_days as proxy for label age (label changes trigger updated_at)
    if idle_days > WAITING_LABEL_MAX_DAYS:
        return True

    return False


async def _health_check_expired(doc: dict, pool: Any) -> str:
    """
    Run a health-check agent call for an expired todo.

    Returns "archived" if the agent decides it expired cleanly, "notified" otherwise.
    """
    todo_id = str(doc["_id"])
    user_id: str = doc.get("user_id", "")
    title: str = doc.get("title", UNTITLED_TODO_TITLE)

    canvas = await _read_canvas(doc)

    prompt = (
        f"A tracked todo has expired.\n"
        f"Title: {title}\n"
        f"Canvas:\n{canvas}\n\n"
        "Did this expire cleanly (i.e. no further action is needed)? "
        "Respond with exactly one of:\n"
        "ARCHIVE: <brief reason>\n"
        "NOTIFY: <message to send to the user>"
    )

    response = await _call_health_check_agent(todo_id, user_id, prompt)

    if response.startswith("ARCHIVE:"):
        reason = response[len("ARCHIVE:") :].strip()
        await tracked_todo_service.archive_tracked_todo(todo_id, user_id, reason)
        await _set_cooldown(pool, todo_id)
        log.info("maintenance_sweep.expired_archived", todo_id=todo_id, reason=reason)
        return "archived"

    # Default: notify
    message = response[len("NOTIFY:") :].strip() if response.startswith("NOTIFY:") else response
    await _send_individual_notification(
        user_id=user_id,
        title=f"Expired: {title}",
        body=message or f"Your tracked todo '{title}' has expired and may need attention.",
        todo_id=todo_id,
        notification_type=NotificationType.WARNING,
    )
    await _set_cooldown(pool, todo_id)
    log.info("maintenance_sweep.expired_notified", todo_id=todo_id)
    return "notified"


async def _health_check_dormant(doc: dict, pool: Any) -> str:
    """
    Run a health-check agent call for a dormant todo.

    Returns "requeued" if the agent identifies a clear next action,
    "needs_attention" otherwise (will be bundled into the digest).
    """
    todo_id = str(doc["_id"])
    user_id: str = doc.get("user_id", "")
    title: str = doc.get("title", UNTITLED_TODO_TITLE)
    updated_at: datetime | None = doc.get("updated_at")
    now = datetime.now(UTC)

    idle_days = (now - updated_at).days if updated_at else DORMANT_DAYS

    canvas = await _read_canvas(doc)

    prompt = (
        f"A tracked todo has been dormant for {idle_days} days.\n"
        f"Title: {title}\n"
        f"Canvas:\n{canvas}\n\n"
        "Is there a clear, concrete next action that can be taken right now? "
        "Respond with exactly one of:\n"
        "EXECUTE: <specific action to perform immediately>\n"
        "NEEDS_ATTENTION: <brief summary of why this needs human review>"
    )

    response = await _call_health_check_agent(todo_id, user_id, prompt)

    if response.startswith("EXECUTE:"):
        jitter_seconds = random.randint(10, 120)  # nosec B311 — non-crypto scheduling jitter
        scheduled_at = now + timedelta(seconds=jitter_seconds)
        await tracked_todo_service.schedule_execution(todo_id, scheduled_at)
        action = response[len("EXECUTE:") :].strip()
        await tracked_todo_service.system_log(
            todo_id,
            user_id,
            "maintenance_requeued",
            f"Dormant todo re-queued by maintenance sweep (idle {idle_days}d). Action: {action}",
        )
        await _set_cooldown(pool, todo_id)
        log.info(
            "maintenance_sweep.dormant_requeued",
            todo_id=todo_id,
            scheduled_at=scheduled_at.isoformat(),
        )
        return "requeued"

    await _set_cooldown(pool, todo_id)
    log.info("maintenance_sweep.dormant_needs_attention", todo_id=todo_id)
    return "needs_attention"


async def _notify_overdue(doc: dict, pool: Any) -> None:
    """Send an individual notification for an overdue todo and label it needs-follow-up."""
    todo_id = str(doc["_id"])
    user_id: str = doc.get("user_id", "")
    title: str = doc.get("title", UNTITLED_TODO_TITLE)
    due_date: datetime | None = doc.get("due_date")
    now = datetime.now(UTC)

    days_overdue = (now - due_date).days if due_date else 0

    await _send_individual_notification(
        user_id=user_id,
        title=f"Overdue: {title}",
        body=f"'{title}' was due {days_overdue} day{'s' if days_overdue != 1 else ''} ago and has no scheduled follow-up.",
        todo_id=todo_id,
        notification_type=NotificationType.WARNING,
    )

    # Add needs-follow-up label
    await todos_collection.update_one(
        {"_id": ObjectId(todo_id)},
        {
            "$addToSet": {"labels": "needs-follow-up"},
            "$set": {"updated_at": now},
        },
    )

    await _set_cooldown(pool, todo_id)
    log.info(
        "maintenance_sweep.overdue_notified",
        todo_id=todo_id,
        days_overdue=days_overdue,
    )


async def _send_dormant_digest(todos: list[dict]) -> None:
    """Send a single digest notification for all dormant todos that need attention."""
    if not todos:
        return

    now = datetime.now(UTC)

    # Collect user_ids — send one digest per user
    by_user: dict[str, list[dict]] = {}
    for doc in todos:
        uid: str = doc.get("user_id", "")
        if uid:
            by_user.setdefault(uid, []).append(doc)

    for user_id, user_todos in by_user.items():
        lines: list[str] = []
        for doc in user_todos:
            title: str = doc.get("title", UNTITLED_TODO_TITLE)
            updated_at: datetime | None = doc.get("updated_at")
            idle_days = (now - updated_at).days if updated_at else DORMANT_DAYS
            lines.append(f"- {title} (idle {idle_days}d)")

        count = len(user_todos)
        body = "\n".join(lines)

        try:
            await notification_service.create_notification(
                NotificationRequest(
                    user_id=user_id,
                    source=NotificationSourceEnum.BACKGROUND_JOB,
                    type=NotificationType.INFO,
                    priority=2,
                    content=NotificationContent(
                        title=f"{count} dormant todo{'s' if count != 1 else ''} need attention",
                        body=body,
                    ),
                    channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
                    metadata={"todo_count": count},
                )
            )
            log.info(
                "maintenance_sweep.dormant_digest_sent",
                user_id=user_id,
                todo_count=count,
            )
        except Exception as exc:
            log.warning(
                "maintenance_sweep.dormant_digest_failed",
                user_id=user_id,
                error=str(exc),
            )


async def _read_canvas(doc: dict) -> str:
    """Read canvas.md from VFS for the given todo. Returns empty string on failure."""
    # Deferred import to avoid circular dependency
    from app.services.vfs.mongo_vfs import MongoVFS

    vfs_path: str | None = doc.get("vfs_path")
    user_id: str = doc.get("user_id", "")
    if not vfs_path or not user_id:
        return ""

    try:
        content = await MongoVFS().read(path=f"{vfs_path}/canvas.md", user_id=user_id)
        return content or ""
    except Exception as exc:
        log.warning(
            "maintenance_sweep.canvas_read_failed",
            todo_id=str(doc.get("_id")),
            error=str(exc),
        )
        return ""


async def _call_health_check_agent(todo_id: str, user_id: str, prompt: str) -> str:
    """
    Call call_agent_silent with a health-check prompt.

    Returns the agent's response string, or "NEEDS_ATTENTION: Health check failed"
    if the agent call errors.
    """

    try:
        user_data = await get_user_by_id(user_id)
        if user_data:
            user_data["user_id"] = user_id
        else:
            user_data = {"user_id": user_id, "name": "User"}
    except Exception as exc:
        log.warning("maintenance_sweep.user_fetch_failed", user_id=user_id, error=str(exc))
        user_data = {"user_id": user_id, "name": "User"}

    user_model_config = None
    try:
        user_model_config = await get_default_model()
    except Exception as exc:
        log.warning(
            "maintenance_sweep.model_config_failed",
            todo_id=todo_id,
            error=str(exc),
        )

    user_time = datetime.now(UTC)
    conversation_id = str(uuid4())

    request = MessageRequestWithHistory(
        message=prompt,
        messages=[],
        fileIds=[],
        fileData=[],
        selectedTool=None,
    )

    try:
        complete_message, _tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            user_time=user_time,
            user_model_config=user_model_config,
            trigger_context={
                "trigger_type": "maintenance_health_check",
                "todo_id": todo_id,
            },
        )
    except Exception as exc:
        log.warning(
            "maintenance_sweep.health_check_agent_failed",
            todo_id=todo_id,
            error=str(exc),
        )
        return "NEEDS_ATTENTION: Health check failed"

    if complete_message and complete_message.startswith("Error when calling silent agent:"):
        return "NEEDS_ATTENTION: Health check failed"

    return (complete_message or "").strip()


async def _send_individual_notification(
    user_id: str,
    title: str,
    body: str,
    todo_id: str,
    notification_type: NotificationType,
) -> None:
    """Send a single in-app notification for a specific todo."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=notification_type,
                content=NotificationContent(
                    title=title,
                    body=body,
                ),
                channels=[ChannelConfig(channel_type="inapp", enabled=True, priority=1)],
                metadata={"todo_id": todo_id},
            )
        )
    except Exception as exc:
        log.warning(
            "maintenance_sweep.notification_failed",
            todo_id=todo_id,
            error=str(exc),
        )


async def _set_cooldown(pool: Any, todo_id: str) -> None:
    """Set a 24h Redis cooldown key so this todo is not processed again soon."""
    cooldown_key = f"gaia_maintenance_notified:{todo_id}"
    await pool.set(cooldown_key, "1", ex=NOTIFICATION_COOLDOWN_SECONDS)
