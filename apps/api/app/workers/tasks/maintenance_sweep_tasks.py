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
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.services.model_service import get_default_model
from app.services.notification_service import notification_service
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import is_within_local_daytime
from shared.py.wide_events import log, wide_task

DORMANT_DAYS = 5
WAITING_LABEL_MAX_DAYS = 8
MAX_HEALTH_CHECKS_PER_USER = 10  # Max agent health-check calls per user per sweep

# Escalating backoff between repeat notifications for the same todo: notify, then
# wait 1 day, then 3, then 7 before each repeat. After the schedule is exhausted
# the todo is muted for MUTE_DAYS so a permanently-stuck todo stops nagging.
NOTIFICATION_BACKOFF_DAYS = (1, 3, 7)
NOTIFICATION_MUTE_DAYS = 30
# Strike counter lives longer than the cooldown so the escalation level survives
# between notifications; it resets only after this much silence.
STRIKE_TTL_DAYS = 30
SECONDS_PER_DAY = 86400

# Quiet hours: only push proactive notifications during the user's local daytime
# so reminders never arrive in the middle of the night.
DAYTIME_START_HOUR = 9
DAYTIME_END_HOUR = 21

BLOCKING_LABELS = {"waiting-for-reply", "waiting-for-approval", "blocked"}
UNTITLED_TODO_TITLE = "Untitled Todo"


async def maintenance_sweep_tracked_todos(_ctx: dict) -> str:
    """Cron task: scan active tracked todos and apply tiered staleness handling.

    Tiers:
    - Expired (expires_at <= now): health-check agent archives or notifies.
    - Overdue (due_date <= now, no upcoming schedule): individual notification.
    - Dormant (no update in DORMANT_DAYS): agent re-queues or bundles a digest.
    """
    async with wide_task("maintenance_sweep_tracked_todos"):
        now = datetime.now(UTC)
        log.info("maintenance_sweep.scan_started")

        pool = await RedisPoolManager.get_pool()

        expired, overdue, dormant = await _classify_tracked_todos(pool, now)

        # Track health-check calls per user to cap LLM usage per sweep
        health_checks_used: dict[str, int] = {}
        # Cache the daytime decision per user for the duration of this sweep.
        daytime_cache: dict[str, bool] = {}

        archived, notified_expired = await _process_expired(
            expired, pool, now, health_checks_used, daytime_cache
        )
        notified_overdue = await _process_overdue(overdue, pool, now, daytime_cache)
        requeued, needs_attention_todos = await _process_dormant(
            dormant, pool, now, health_checks_used, daytime_cache
        )

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


async def _classify_tracked_todos(
    pool: Any, now: datetime
) -> tuple[list[dict], list[dict], list[dict]]:
    """Scan active tracked todos and bucket them into expired/overdue/dormant tiers.

    Todos still inside their notification backoff are skipped. Each tier is capped
    at 20 entries per sweep.
    """
    cursor = todos_collection.find({"completed": False, "labels": "gaia-tracked"}).limit(200)

    expired: list[dict] = []
    overdue: list[dict] = []
    dormant: list[dict] = []

    async for doc in cursor:
        todo_id = str(doc["_id"])

        # Skip todos still inside their (escalating) notification backoff.
        if await pool.exists(_cooldown_key(todo_id)):
            continue

        if doc.get("expires_at") and doc["expires_at"] <= now:
            expired.append(doc)
        elif (
            doc.get("due_date") and doc["due_date"] <= now and not _has_upcoming_schedule(doc, now)
        ):
            overdue.append(doc)
        elif _is_dormant(doc, now):
            dormant.append(doc)

    # Cap at 20 per tier per sweep
    return expired[:20], overdue[:20], dormant[:20]


async def _process_expired(
    expired: list[dict],
    pool: Any,
    now: datetime,
    health_checks_used: dict[str, int],
    daytime_cache: dict[str, bool],
) -> tuple[int, int]:
    """Run the health-check agent on expired todos; archive or notify each.

    Returns ``(archived_count, notified_count)``.
    """
    archived = 0
    notified_expired = 0
    for doc in expired:
        uid = doc["user_id"]
        # Defer to a daytime sweep — no cooldown consumed, retried later.
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
            continue
        result = await _health_check_expired(doc, pool)
        health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
        if result == "archived":
            archived += 1
        elif result == "notified":
            notified_expired += 1
    return archived, notified_expired


async def _process_overdue(
    overdue: list[dict],
    pool: Any,
    now: datetime,
    daytime_cache: dict[str, bool],
) -> int:
    """Send an individual notification for each overdue todo. Returns notified count."""
    notified_overdue = 0
    for doc in overdue:
        uid = doc["user_id"]
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        if await _notify_overdue(doc, pool):
            notified_overdue += 1
    return notified_overdue


async def _process_dormant(
    dormant: list[dict],
    pool: Any,
    now: datetime,
    health_checks_used: dict[str, int],
    daytime_cache: dict[str, bool],
) -> tuple[int, list[dict]]:
    """Re-queue dormant todos via the agent, else collect them for the digest.

    Applies the escalating backoff once per surviving todo and drops any now muted.
    Returns ``(requeued_count, needs_attention_todos)``.
    """
    requeued = 0
    # Collect dormant todos that need human attention, then apply the
    # escalating backoff once per todo and drop any that are now muted.
    needs_attention_candidates: list[dict] = []
    for doc in dormant:
        uid = doc["user_id"]
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
            needs_attention_candidates.append(doc)
            continue
        result = await _health_check_dormant(doc, pool)
        health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
        if result == "requeued":
            requeued += 1
        else:
            needs_attention_candidates.append(doc)

    needs_attention_todos: list[dict] = []
    for doc in needs_attention_candidates:
        if await _register_notification(pool, str(doc["_id"])):
            needs_attention_todos.append(doc)

    return requeued, needs_attention_todos


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

    Returns "archived" if the agent decides it expired cleanly, "notified" if a
    notification was sent, or "muted" when the escalating backoff is exhausted.
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
        # Archived todos leave the active set; a short cooldown just avoids a
        # redundant re-scan before the archive propagates.
        await _set_cooldown(pool, todo_id, NOTIFICATION_BACKOFF_DAYS[0])
        log.info("maintenance_sweep.expired_archived", todo_id=todo_id, reason=reason)
        return "archived"

    # Default: notify, subject to the escalating backoff.
    if not await _register_notification(pool, todo_id):
        log.info("maintenance_sweep.expired_muted", todo_id=todo_id)
        return "muted"

    message = response[len("NOTIFY:") :].strip() if response.startswith("NOTIFY:") else response
    await _send_individual_notification(
        user_id=user_id,
        title=f"Expired: {title}",
        body=message or f"Your tracked todo '{title}' has expired and may need attention.",
        todo_id=todo_id,
        notification_type=NotificationType.WARNING,
    )
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
        jitter_seconds = random.randint(10, 120)  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
        scheduled_at = now + timedelta(seconds=jitter_seconds)
        await tracked_todo_service.schedule_execution(todo_id, scheduled_at)
        action = response[len("EXECUTE:") :].strip()
        await tracked_todo_service.system_log(
            todo_id,
            user_id,
            "maintenance_requeued",
            f"Dormant todo re-queued by maintenance sweep (idle {idle_days}d). Action: {action}",
        )
        # Re-queued for execution, not notified — a short cooldown avoids
        # re-processing before the scheduled run; no escalation strike consumed.
        await _set_cooldown(pool, todo_id, NOTIFICATION_BACKOFF_DAYS[0])
        log.info(
            "maintenance_sweep.dormant_requeued",
            todo_id=todo_id,
            scheduled_at=scheduled_at.isoformat(),
        )
        return "requeued"

    # The caller registers the escalating backoff for needs-attention todos
    # (so muted ones are dropped from the digest), so don't set a cooldown here.
    log.info("maintenance_sweep.dormant_needs_attention", todo_id=todo_id)
    return "needs_attention"


async def _notify_overdue(doc: dict, pool: Any) -> bool:
    """Notify about an overdue todo and label it needs-follow-up.

    Returns True if a notification was sent, False when the escalating backoff
    is exhausted and the todo is muted.
    """
    todo_id = str(doc["_id"])
    user_id: str = doc.get("user_id", "")
    title: str = doc.get("title", UNTITLED_TODO_TITLE)
    due_date: datetime | None = doc.get("due_date")
    now = datetime.now(UTC)

    if not await _register_notification(pool, todo_id):
        log.info("maintenance_sweep.overdue_muted", todo_id=todo_id)
        return False

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

    log.info(
        "maintenance_sweep.overdue_notified",
        todo_id=todo_id,
        days_overdue=days_overdue,
    )
    return True


def _todo_redirect_action(label: str, todo_id: str | None) -> NotificationAction:
    """Build a primary REDIRECT action to the todos page.

    Deep-links the specific todo via ``?todoId`` when one is given (single-item
    notifications), otherwise lands on the todos list (multi-item digest).
    """
    url = f"/todos?todoId={todo_id}" if todo_id else "/todos"
    return NotificationAction(
        type=ActionType.REDIRECT,
        label=label,
        style=ActionStyle.PRIMARY,
        config=ActionConfig(
            redirect=RedirectConfig(url=url, open_in_new_tab=False, close_notification=True)
        ),
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
        await _send_user_dormant_digest(user_id, user_todos, now)


async def _send_user_dormant_digest(user_id: str, user_todos: list[dict], now: datetime) -> None:
    """Send one dormant-todo digest notification to a single user."""
    lines: list[str] = []
    for doc in user_todos:
        title: str = doc.get("title", UNTITLED_TODO_TITLE)
        updated_at: datetime | None = doc.get("updated_at")
        idle_days = (now - updated_at).days if updated_at else DORMANT_DAYS
        lines.append(f"- {title} (idle {idle_days}d)")

    count = len(user_todos)
    body = "\n".join(lines)
    # Deep-link the single todo; land on the list when the digest bundles several.
    action = _todo_redirect_action(
        "View todo" if count == 1 else "Review todos",
        str(user_todos[0]["_id"]) if count == 1 else None,
    )

    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.INFO,
                priority=2,
                content=NotificationContent(
                    title=(
                        f"{count} dormant todo needs attention"
                        if count == 1
                        else f"{count} dormant todos need attention"
                    ),
                    body=body,
                    actions=[action],
                ),
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
    """Read canvas content for the given todo. Returns empty string on failure."""
    from app.services.todo_canvas_storage import read_canvas

    user_id: str = doc.get("user_id", "")
    todo_id = str(doc.get("_id") or "")
    if not user_id or not todo_id:
        return ""

    try:
        content = await read_canvas(todo_id, user_id)
        return content or ""
    except Exception as exc:
        log.warning(
            "maintenance_sweep.canvas_read_failed",
            todo_id=todo_id,
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
    """Send a single notification for a specific todo across the user's enabled channels."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=notification_type,
                content=NotificationContent(
                    title=title,
                    body=body,
                    actions=[_todo_redirect_action("View todo", todo_id)],
                ),
                metadata={"todo_id": todo_id},
            )
        )
    except Exception as exc:
        log.warning(
            "maintenance_sweep.notification_failed",
            todo_id=todo_id,
            error=str(exc),
        )


def _cooldown_key(todo_id: str) -> str:
    """Redis key whose presence throttles re-processing of a todo."""
    return f"gaia_maintenance_notified:{todo_id}"


def _strike_key(todo_id: str) -> str:
    """Redis key holding the escalation level (notification count) for a todo."""
    return f"gaia_maintenance_strikes:{todo_id}"


async def _set_cooldown(pool: Any, todo_id: str, days: int) -> None:
    """Throttle re-processing of a todo for ``days`` days."""
    await pool.set(_cooldown_key(todo_id), "1", ex=days * SECONDS_PER_DAY)


async def _register_notification(pool: Any, todo_id: str) -> bool:
    """Advance a todo's escalating notification backoff.

    Returns True if a notification should be sent now and sets the next cooldown
    from ``NOTIFICATION_BACKOFF_DAYS``. Returns False once the schedule is
    exhausted — the todo is muted for ``NOTIFICATION_MUTE_DAYS`` and the caller
    must not send. The strike counter outlives each cooldown so the escalation
    level survives between notifications, resetting only after ``STRIKE_TTL_DAYS``
    of silence.
    """
    strike_key = _strike_key(todo_id)
    raw = await pool.get(strike_key)
    if isinstance(raw, bytes):
        raw = raw.decode()
    strike = (int(raw) + 1) if raw else 1

    if strike > len(NOTIFICATION_BACKOFF_DAYS):
        await _set_cooldown(pool, todo_id, NOTIFICATION_MUTE_DAYS)
        return False

    await pool.set(strike_key, str(strike), ex=STRIKE_TTL_DAYS * SECONDS_PER_DAY)
    await _set_cooldown(pool, todo_id, NOTIFICATION_BACKOFF_DAYS[strike - 1])
    return True


async def _is_user_daytime(user_id: str, now: datetime, cache: dict[str, bool]) -> bool:
    """Whether it is currently daytime for ``user_id`` (cached per sweep).

    Proactive notifications are deferred outside the user's local daytime window
    so they never arrive overnight. Fails open (returns True) when the user or
    timezone can't be resolved.
    """
    if user_id in cache:
        return cache[user_id]

    timezone_name: str | None = None
    try:
        user = await get_user_by_id(user_id)
        if user:
            timezone_name = user.get("timezone")
    except Exception as exc:
        log.warning("maintenance_sweep.user_tz_lookup_failed", user_id=user_id, error=str(exc))

    result = is_within_local_daytime(now, timezone_name, DAYTIME_START_HOUR, DAYTIME_END_HOUR)
    cache[user_id] = result
    return result
