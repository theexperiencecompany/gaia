"""ARQ tasks for proactive maintenance of tracked todos."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
import random
from typing import Literal, cast

from langchain_core.messages import BaseMessage, HumanMessage

from app.agents.llm.client import ainvoke_llm, metered_config, resolve_model
from app.agents.prompts.todo_prompts import HEALTH_CHECK_VERDICT_ONLY
from app.constants.outbox_attention import REPEAT_BACKOFF_SECONDS
from app.constants.todos import BLOCKING_LABELS, TodoActivityEvent
from app.db.repositories.outbox_items import outbox_items_repository
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument, TodoUpdate
from app.services.canvas_markdown import bounded_canvas
from app.services.outbox.holds import repeat_gap
from app.services.outbox.intake import submit
from app.services.outbox.models import NoticeOutcome, ProducerKind, SubjectKind
from app.services.outbox.system_notices import system_notice, system_report_id
from app.services.todo_activity import record_activity
from app.services.tracked_todo_service import tracked_todo_service
from app.services.user_service import get_user_by_id
from app.utils.timezone import as_utc, is_within_local_daytime
from shared.py.wide_events import log

DORMANT_DAYS = 5
WAITING_LABEL_MAX_DAYS = 8
MAX_HEALTH_CHECKS_PER_USER = 10  # Max agent health-check calls per user per sweep
# Legacy-migration page size: the cursor loop pages to a short page, so the
# scan is complete no matter how many tracked todos exist.
_MIGRATION_PAGE_SIZE = 200

# What the sweep files for a todo is named by the day, so it files at most one notice a day for
# each; how often the user is told again is the outbox's repeat back-off.
KIND_EXPIRED = "todo_expired"
KIND_OVERDUE = "todo_overdue"
KIND_DORMANT_DIGEST = "todo_dormant_digest"

# Quiet hours: only push proactive notifications during the user's local daytime
# so reminders never arrive in the middle of the night.
DAYTIME_START_HOUR = 9
DAYTIME_END_HOUR = 21

# What a tier's health check decided, so the caller's counter branches are checked.
ExpiredOutcome = Literal["archived", "notified"]
DormantOutcome = Literal["requeued", "needs_attention"]


async def maintenance_sweep_tracked_todos(_ctx: Mapping[str, object]) -> str:
    """Cron task: scan active tracked todos and apply tiered staleness handling.

    Tiers:
    - Expired (expires_at <= now): health-check agent archives or notifies.
    - Overdue (due_date <= now, no upcoming schedule): individual notification.
    - Dormant (no update in DORMANT_DAYS): agent re-queues or bundles a digest.
    """
    now = datetime.now(UTC)
    log.info("maintenance_sweep.scan_started")

    todos = await todo_repository.list_active_tracked_all_users(limit=200)
    migrated = await _normalize_all_canvases()
    expired, overdue, dormant = await _classify_tracked_todos(now, todos)

    # Track health-check calls per user to cap LLM usage per sweep
    health_checks_used: dict[str, int] = {}
    # Cache the daytime decision per user for the duration of this sweep.
    daytime_cache: dict[str, bool] = {}

    archived, notified_expired = await _process_expired(
        expired, now, health_checks_used, daytime_cache
    )
    notified_overdue = await _process_overdue(overdue, now, daytime_cache)
    requeued, needs_attention_todos = await _process_dormant(
        dormant, now, health_checks_used, daytime_cache
    )

    if needs_attention_todos:
        await _send_dormant_digest(needs_attention_todos, now)

    summary = (
        f"archived:{archived} notified_expired:{notified_expired} "
        f"notified_overdue:{notified_overdue} requeued:{requeued} "
        f"digest_items:{len(needs_attention_todos)}"
    )
    log.set(
        migrated_canvases=migrated,
        archived=archived,
        notified_expired=notified_expired,
        notified_overdue=notified_overdue,
        requeued=requeued,
        digest_items=len(needs_attention_todos),
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


async def _normalize_all_canvases() -> int:
    """Cursor every tracked todo, active or completed, through canvas normalization.

    The tier classification scans active todos only, so this loop covers completed
    ones too; normalization is idempotent, so re-scans are safe.
    """
    migrated = 0
    after_id: str | None = None
    while True:
        page = await todo_repository.list_tracked_for_legacy_migration(
            limit=_MIGRATION_PAGE_SIZE, after_id=after_id
        )
        if not page:
            break
        migrated += await _normalize_stored_canvases(page)
        if len(page) < _MIGRATION_PAGE_SIZE:
            break
        after_id = page[-1].id
    return migrated


async def _normalize_stored_canvases(todos: list[TodoDocument]) -> int:
    """Offer every scanned todo to canvas normalization."""
    migrated = 0
    for todo in todos:
        try:
            if await tracked_todo_service.normalize_stored_canvas(todo):
                migrated += 1
        except Exception as exc:
            log.warning(
                "maintenance_sweep.canvas_normalization_failed",
                todo_id=todo.id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
    return migrated


def _notice_day(now: datetime) -> str:
    return now.date().isoformat()


async def _in_back_off(user_id: str, kind: str, key: str, now: datetime) -> bool:
    """Whether the ledger says a notice of one kind for key was filed too recently to check and say it again."""
    filed = await outbox_items_repository.list_filed_with_prefix(
        user_id, system_report_id(kind, f"{key}:"), limit=len(REPEAT_BACKOFF_SECONDS) + 1
    )
    if not filed:
        return False
    last_filed_at = as_utc(filed[0].created_at)
    return last_filed_at is not None and now < last_filed_at + repeat_gap(len(filed))


async def _classify_tracked_todos(
    now: datetime, todos: list[TodoDocument]
) -> tuple[list[TodoDocument], list[TodoDocument], list[TodoDocument]]:
    """Bucket active tracked todos into expired/overdue/dormant tiers.

    A todo still inside the back-off its earlier notices set is skipped, so it costs no health check.
    Each tier is capped at 20 entries per sweep.
    """
    expired: list[TodoDocument] = []
    overdue: list[TodoDocument] = []
    dormant: list[TodoDocument] = []

    for todo in todos:
        if todo.expires_at and todo.expires_at <= now:
            if not await _in_back_off(todo.user_id, KIND_EXPIRED, todo.id, now):
                expired.append(todo)
        elif todo.due_date and todo.due_date <= now and not _has_upcoming_schedule(todo, now):
            if not await _in_back_off(todo.user_id, KIND_OVERDUE, todo.id, now):
                overdue.append(todo)
        elif _is_dormant(todo, now) and not await _in_back_off(
            todo.user_id, KIND_DORMANT_DIGEST, todo.user_id, now
        ):
            dormant.append(todo)

    # Cap at 20 per tier per sweep
    return expired[:20], overdue[:20], dormant[:20]


async def _process_expired(
    expired: list[TodoDocument],
    now: datetime,
    health_checks_used: dict[str, int],
    daytime_cache: dict[str, bool],
) -> tuple[int, int]:
    """Run the health-check agent on expired todos; archive or file a notice for each.

    Returns (archived_count, notified_count).
    """
    archived = 0
    notified_expired = 0
    for todo in expired:
        uid = todo.user_id
        # Defer to a daytime sweep: retried later.
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
            continue
        # Counted before the call: a failed check has still spent the budget.
        health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
        try:
            result = await _health_check_expired(todo, now)
        except Exception as exc:
            # One todo must never abort the sweep for every other user: an
            # oversized canvas once raised here and killed the whole cron. No
            # notice was filed, so this todo is retried next sweep.
            log.error(
                "maintenance_sweep.expired_health_check_error",
                todo_id=todo.id,
                user_id=uid,
                error_type=type(exc).__name__,
            )
            continue
        if result == "archived":
            archived += 1
        elif result == "notified":
            notified_expired += 1
    return archived, notified_expired


async def _process_overdue(
    overdue: list[TodoDocument],
    now: datetime,
    daytime_cache: dict[str, bool],
) -> int:
    """File a notice for each overdue todo. Returns how many were filed."""
    notified_overdue = 0
    for todo in overdue:
        uid = todo.user_id
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        try:
            await _notify_overdue(todo, now)
        except Exception as exc:
            # Same containment as the health-check tiers: one todo's failure
            # cannot cost every other user their sweep.
            log.error(
                "maintenance_sweep.overdue_error",
                todo_id=todo.id,
                user_id=uid,
                error_type=type(exc).__name__,
            )
            continue
        notified_overdue += 1
    return notified_overdue


async def _process_dormant(
    dormant: list[TodoDocument],
    now: datetime,
    health_checks_used: dict[str, int],
    daytime_cache: dict[str, bool],
) -> tuple[int, list[TodoDocument]]:
    """Re-queue dormant todos via the agent, else collect them for the digest.

    Returns (requeued_count, needs_attention_todos).
    """
    requeued = 0
    needs_attention: list[TodoDocument] = []
    for todo in dormant:
        uid = todo.user_id
        if not await _is_user_daytime(uid, now, daytime_cache):
            continue
        if health_checks_used.get(uid, 0) >= MAX_HEALTH_CHECKS_PER_USER:
            needs_attention.append(todo)
            continue
        # Counted before the call: a failed check has still spent the budget.
        health_checks_used[uid] = health_checks_used.get(uid, 0) + 1
        try:
            result = await _health_check_dormant(todo)
        except Exception as exc:
            # One todo must never abort the sweep for others (an oversized canvas
            # once did). It retries next sweep
            # rather than being digested on a check that failed.
            log.error(
                "maintenance_sweep.dormant_health_check_error",
                todo_id=todo.id,
                user_id=uid,
                error_type=type(exc).__name__,
            )
            continue
        if result == "requeued":
            requeued += 1
        else:
            needs_attention.append(todo)

    return requeued, needs_attention


def _has_upcoming_schedule(todo: TodoDocument, now: datetime) -> bool:
    """Return True if the todo has a genuine upcoming execution.

    A recurring todo with a stale scheduled_at (>2 days old) is NOT considered
    to have an upcoming schedule: it's likely orphaned.
    """
    scheduled_at = todo.scheduled_at
    if scheduled_at and scheduled_at > now:
        return True

    # Recurrence alone doesn't count if the last scheduled_at is stale
    if todo.recurrence:
        if scheduled_at:
            days_since_scheduled = (now - scheduled_at).days
            if days_since_scheduled <= 2:
                # Recently executed recurring todo: next run is coming
                return True
        # Recurrence set but scheduled_at is missing or stale: orphaned
        return False

    return False


def _is_dormant(todo: TodoDocument, now: datetime) -> bool:
    """Return True if the todo has been idle for more than DORMANT_DAYS.

    Also requires no upcoming schedule and no blocking label — unless that
    label has sat past WAITING_LABEL_MAX_DAYS, at which point it's stuck and
    should surface anyway.
    """
    updated_at = todo.updated_at
    if not updated_at:
        return False

    idle_days = (now - updated_at).days
    if idle_days <= DORMANT_DAYS:
        return False

    if _has_upcoming_schedule(todo, now):
        return False

    blocking = BLOCKING_LABELS.intersection(todo.labels)
    if not blocking:
        return True

    # Blocking label present: only surface if it has been stuck too long
    # Use idle_days as proxy for label age (label changes trigger updated_at)
    return idle_days > WAITING_LABEL_MAX_DAYS


async def _health_check_expired(todo: TodoDocument, now: datetime) -> ExpiredOutcome:
    """
    Run a health-check agent call for an expired todo.

    Returns "archived" if the agent decides it expired cleanly, "notified" if a
    notice was filed.
    """
    todo_id = todo.id
    user_id = todo.user_id
    title = todo.title

    canvas = bounded_canvas(await _read_canvas(todo))

    prompt = (
        f"A tracked todo has expired.\n"
        f"Title: {title}\n"
        f"Canvas:\n{canvas}\n\n"
        "Did this expire cleanly (i.e. no further action is needed)? "
        f"{HEALTH_CHECK_VERDICT_ONLY} Respond with exactly one of:\n"
        "ARCHIVE: <brief reason>\n"
        "NOTIFY: <why it needs the user's attention>"
    )

    response = await _health_check_verdict(user_id, prompt)

    if response.startswith("ARCHIVE:"):
        reason = response[len("ARCHIVE:") :].strip()
        await tracked_todo_service.archive_tracked_todo(todo_id, user_id, reason)
        log.info("maintenance_sweep.expired_archived", todo_id=todo_id, reason=reason)
        return "archived"

    message = response[len("NOTIFY:") :].strip() if response.startswith("NOTIFY:") else response
    await _file_todo_notice(
        todo,
        KIND_EXPIRED,
        message or f"The tracked todo '{title}' has expired and may need attention.",
        f"'{title}' has expired and may need your attention.",
        now,
    )
    await record_activity(
        todo_id, user_id, TodoActivityEvent.MAINTENANCE, "reported this todo as expired"
    )
    log.info("maintenance_sweep.expired_notified", todo_id=todo_id)
    return "notified"


async def _health_check_dormant(todo: TodoDocument) -> DormantOutcome:
    """
    Run a health-check agent call for a dormant todo.

    Returns "requeued" if the agent identifies a clear next action,
    "needs_attention" otherwise (will be bundled into the digest).
    """
    todo_id = todo.id
    user_id = todo.user_id
    title = todo.title
    updated_at = todo.updated_at
    now = datetime.now(UTC)

    idle_days = (now - updated_at).days if updated_at else DORMANT_DAYS

    canvas = bounded_canvas(await _read_canvas(todo))

    prompt = (
        f"A tracked todo has been dormant for {idle_days} days.\n"
        f"Title: {title}\n"
        f"Canvas:\n{canvas}\n\n"
        "Is there a clear, concrete next action that can be taken right now? "
        f"{HEALTH_CHECK_VERDICT_ONLY} Respond with exactly one of:\n"
        "EXECUTE: <specific action to perform immediately>\n"
        "NEEDS_ATTENTION: <brief summary of why this needs human review>"
    )

    response = await _health_check_verdict(user_id, prompt)

    if response.startswith("EXECUTE:"):
        jitter_seconds = random.randint(10, 120)  # nosec B311  # NOSONAR python:S2245: non-crypto scheduling jitter
        scheduled_at = now + timedelta(seconds=jitter_seconds)
        # Stored first: the run drops a fire its todo's scheduled_at doesn't name,
        # and the safety net can only recover a job whose time is on the todo.
        await todo_repository.update(
            todo_id, user_id=user_id, update=TodoUpdate(scheduled_at=scheduled_at)
        )
        await tracked_todo_service.schedule_execution(todo_id, scheduled_at)
        action = response[len("EXECUTE:") :].strip()
        await record_activity(
            todo_id,
            user_id,
            TodoActivityEvent.MAINTENANCE,
            f"re-queued after {idle_days} idle days to: {action}",
        )
        log.info(
            "maintenance_sweep.dormant_requeued",
            todo_id=todo_id,
            scheduled_at=scheduled_at.isoformat(),
        )
        return "requeued"

    log.info("maintenance_sweep.dormant_needs_attention", todo_id=todo_id)
    return "needs_attention"


async def _notify_overdue(todo: TodoDocument, now: datetime) -> None:
    """File that a todo is overdue and label it needs-follow-up."""
    todo_id = todo.id
    user_id = todo.user_id
    title = todo.title
    due_date = todo.due_date

    days_overdue = (now - due_date).days if due_date else 0

    await _file_todo_notice(
        todo,
        KIND_OVERDUE,
        f"'{title}' was due {days_overdue} day{'s' if days_overdue != 1 else ''} ago and has no "
        "scheduled follow-up.",
        f"'{title}' was due {days_overdue} day{'s' if days_overdue != 1 else ''} ago and has "
        "nothing scheduled to follow up.",
        now,
    )

    # Add needs-follow-up label
    await todo_repository.add_labels(todo_id, user_id=user_id, labels=["needs-follow-up"])
    await record_activity(
        todo_id,
        user_id,
        TodoActivityEvent.MAINTENANCE,
        f"reported it {days_overdue} day(s) overdue with nothing scheduled",
    )

    log.info(
        "maintenance_sweep.overdue_notified",
        todo_id=todo_id,
        days_overdue=days_overdue,
    )


async def _send_dormant_digest(todos: list[TodoDocument], now: datetime) -> None:
    """File one digest notice per user for all their dormant todos that need attention."""
    by_user: dict[str, list[TodoDocument]] = {}
    for todo in todos:
        if todo.user_id:
            by_user.setdefault(todo.user_id, []).append(todo)

    for user_id, user_todos in by_user.items():
        await _send_user_dormant_digest(user_id, user_todos, now)


async def _send_user_dormant_digest(
    user_id: str, user_todos: list[TodoDocument], now: datetime
) -> None:
    """File one dormant-todo digest notice for a single user."""
    facts = [
        f"'{todo.title}' has been idle for "
        f"{(now - todo.updated_at).days if todo.updated_at else DORMANT_DAYS} days."
        for todo in user_todos
    ]
    count = len(user_todos)
    try:
        await submit(
            system_notice(
                user_id=user_id,
                producer=ProducerKind.TODO,
                subject_kind=SubjectKind.TODO_RUN,
                kind=KIND_DORMANT_DIGEST,
                key=f"{user_id}:{_notice_day(now)}",
                label="Dormant todos",
                outcome=NoticeOutcome.INFO,
                facts=facts,
                display=f"{count} todo{'s have' if count != 1 else ' has'} gone quiet and may need "
                "your attention: " + ", ".join(f"'{todo.title}'" for todo in user_todos) + ".",
            )
        )
        log.info("maintenance_sweep.dormant_digest_filed", user_id=user_id, todo_count=count)
    except Exception as exc:
        log.warning(
            "maintenance_sweep.dormant_digest_failed",
            user_id=user_id,
            error=str(exc),
        )


async def _read_canvas(todo: TodoDocument) -> str:
    """Read canvas content for the given todo. Returns empty string on failure."""
    from app.services.todo_canvas_storage import read_canvas

    user_id = todo.user_id
    todo_id = todo.id
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


async def _health_check_verdict(user_id: str, prompt: str) -> str:
    """Ask a bare model, with no tools bound, for the health-check verdict and return it stripped.

    The sweep acts on the verdict itself, so the check must have no way to act:
    not the comms agent, no tool. A model failure propagates to the per-todo
    containment, which logs it and retries the todo next sweep.
    """
    response = await ainvoke_llm(
        resolve_model(),
        [HumanMessage(content=prompt)],
        label="todo_health_check",
        config=metered_config(user_id),
    )
    return cast(BaseMessage, response).text.strip()


async def _file_todo_notice(
    todo: TodoDocument, kind: str, fact: str, display: str, now: datetime
) -> None:
    """File the notice of one kind for a todo, named by the day: the sweep's back-off keeps it to one a day at most."""
    await submit(
        system_notice(
            user_id=todo.user_id,
            producer=ProducerKind.TODO,
            subject_kind=SubjectKind.TODO_RUN,
            kind=kind,
            key=f"{todo.id}:{_notice_day(now)}",
            label=todo.title,
            outcome=NoticeOutcome.INFO,
            facts=[fact],
            display=display,
        )
    )


async def _is_user_daytime(user_id: str, now: datetime, cache: dict[str, bool]) -> bool:
    """Whether it is currently daytime for user_id (cached per sweep).

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
            timezone_name = user.timezone
    except Exception as exc:
        log.warning("maintenance_sweep.user_tz_lookup_failed", user_id=user_id, error=str(exc))

    result = is_within_local_daytime(now, timezone_name, DAYTIME_START_HOUR, DAYTIME_END_HOUR)
    cache[user_id] = result
    return result
