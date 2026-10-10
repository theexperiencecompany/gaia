"""
ARQ worker tasks for executing scheduled tracked todos.

Handles:
- Acquiring Redis locks to prevent double-execution
- Retry logic with exponential backoff
- Agent execution from the todo's canvas, activity and references
- Recurrence scheduling (re-enqueue after success)
- Safety-net cron for orphaned todos
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
import random
from typing import cast
from uuid import uuid4

from arq import Retry
from arq.connections import ArqRedis

from app.agents.core.background.session import TodoRun
from app.agents.core.background.todo_run import TodoRunRequest, run_todo_on_executor
from app.agents.core.background.todo_run_delivery import (
    FinishedTodoRun,
    finish_todo_run,
    hand_unfinished_run_to_job,
    report_unfinished_run,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import (
    EXECUTE_TRACKED_TODO_TASK,
    FAILED_LABEL,
    LOCK_DEFER_BACKOFF,
    LOCK_TTL_SECONDS,
    MAX_RETRY_ATTEMPTS,
    PAUSED_RUN_RECHECK,
    RETRY_BACKOFF,
    RUN_LOCK_KEY,
    TODO_ANCHORED_RECURRENCES,
    TODO_INTERVAL_RECURRENCES,
    TODO_RUN_FINISH_MAX_TRIES,
    TODO_RUN_FINISH_RETRY_DELAY,
    TODO_SCHEDULE_FIRE_GRACE,
    TRIGGER_TODO_FEATURE_KEY,
    TodoActivityEvent,
)
from app.db.repositories.todos import todo_repository
from app.decorators import enforce_daily_cost_budget
from app.decorators.entitlements import capture_paywall_block, is_paid
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.scheduler_models import DeactivationReason
from app.models.todo_models import ExternalRefSource, TodoDocument, TodoUpdate
from app.models.trigger_subscription_models import TriggerOrigin
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.notification_service import notification_service
from app.services.todo_activity import record_activity
from app.services.todos.inbox_desk import with_desk_notes
from app.services.tracked_todo_service import tracked_todo_service
from app.services.triggers.subscription_service import teardown_subscriptions
from app.services.triggers.todo_trigger_window import (
    buffer_todo_trigger_event,
    drain_todo_trigger_events,
    hold_trigger_event_while_paused,
    open_trigger_window,
    reschedule_todo_trigger_drain,
    trigger_window,
    trigger_window_end,
)
from app.utils.auth_utils import OwnerNotFoundError, require_owner
from app.utils.cron_utils import CronError, get_next_run_time
from app.utils.occurrence import occurrence_stamp, parse_occurrence_stamp
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.queue import enqueue_worker_job
from app.workers.task_envelope import ArqJobContext
from app.workers.tasks.todo_run_context import collect_run_context
from app.workers.tasks.todo_run_prompt import build_execution_prompt
from shared.py.analytics.catalog.attribution import Trigger
from shared.py.analytics.context import analytics_context, worker_context
from shared.py.wide_events import log

#: The surface a paywalled tracked-todo run is attributed to in the funnel.
PAYWALL_FEATURE_TRACKED_TODO = "tracked_todo"


async def _load_user_with_tz(user_id: str) -> tuple[AuthenticatedUser, Timezone]:
    """Fetch the owner once and resolve their home timezone; OwnerNotFoundError when there is no owner.

    Timezone.parse keeps a stored ±HH:MM offset from crashing ZoneInfo and reads
    an unset zone as UTC.
    """
    # The full context: narrowing to the fields read here would drop
    # onboarding, which construct_langchain_messages needs.
    user_data = await require_owner(user_id)
    return user_data, Timezone.parse(user_data.timezone)


async def _retire_ownerless_todo(doc: TodoDocument) -> str:
    """Archive a todo whose owner is not a user, then clear its schedule so it never fires again.

    A failed archive raises with the schedule kept, so the next fire retries the retirement.
    """
    if not await tracked_todo_service.archive_tracked_todo(
        doc.id, doc.user_id, reason="its owner is not a GAIA user"
    ):
        raise RuntimeError(f"Could not archive todo {doc.id}, whose owner is not a GAIA user")
    await todo_repository.update(doc.id, user_id=doc.user_id, update=TodoUpdate(scheduled_at=None))
    return f"no_owner:{doc.id}"


async def execute_tracked_todo(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    todo_id: str,
    origin: TriggerOrigin | None = None,
    scheduled_for: int | None = None,
    coalesced: list[TriggerOrigin] | None = None,
    trigger_window: int | None = None,
) -> str:
    """Execute a tracked todo on its schedule, on a trigger, or for the events its window held.

    Holds a Redis lock for the run. A trigger run also takes every event held for
    the todo, and every run ends by scheduling a drain for events that landed
    meanwhile. All but todo_id are parameters because ARQ's ctx is the worker's.
    """
    log.set(
        todo_id=todo_id,
        trigger_origin=origin.trigger_name if origin else None,
        scheduled_for=scheduled_for,
    )
    log.info("tracked_todo.execute_started", todo_id=todo_id)

    if trigger_window is not None:
        log.set(trigger_window=trigger_window)
        later_window = await trigger_window_end(todo_id)
        if later_window is not None and later_window > trigger_window:
            # A run since opened a later window; the held events wait for its end.
            await reschedule_todo_trigger_drain(todo_id)
            return f"deferred:{todo_id} (trigger window open until {later_window})"

    pool = await RedisPoolManager.get_pool()
    acquired = await pool.set(
        RUN_LOCK_KEY.format(todo_id=todo_id), "1", nx=True, ex=LOCK_TTL_SECONDS
    )
    if not acquired:
        return await _handle_held_lock(todo_id, origin, coalesced or [])

    # The run is its schedule's or its trigger's (a window drain included), whoever armed it.
    is_trigger_run = origin is not None or trigger_window is not None
    fired_by = worker_context(Trigger.INTEGRATION_TRIGGER if is_trigger_run else Trigger.SCHEDULE)
    try:
        with analytics_context(fired_by):
            if origin is None and trigger_window is None:
                return await _execute_todo_with_retry(
                    todo_id, None, parse_occurrence_stamp(scheduled_for, todo_id)
                )
            events = await _take_trigger_events(todo_id, origin, coalesced or [])
            if not events:
                return f"skipped:{todo_id} (no held trigger events)"
            # A trigger run is not an occurrence of the schedule, so it is never stale.
            first, *rest = events
            return await _execute_todo_with_retry(todo_id, first, coalesced=rest)
    finally:
        await _release_run_lock(pool, todo_id)


async def _release_run_lock(pool: ArqRedis, todo_id: str) -> None:
    """Release a todo's run lock, whoever held it, then drain the events held meanwhile."""
    await pool.delete(RUN_LOCK_KEY.format(todo_id=todo_id))
    # After the release, so a drain scheduled for now cannot find this run's lock.
    await reschedule_todo_trigger_drain(todo_id)


async def _take_trigger_events(
    todo_id: str, origin: TriggerOrigin | None, coalesced: list[TriggerOrigin]
) -> list[TriggerOrigin]:
    """Return the events this fire carries, then every event held for the todo."""
    carried = [origin, *coalesced] if origin is not None else coalesced
    held = await drain_todo_trigger_events(todo_id)
    # None is a Redis outage, already logged; the held events stay for the next drain.
    return carried if held is None else [*carried, *held]


async def _handle_held_lock(
    todo_id: str, origin: TriggerOrigin | None, coalesced: list[TriggerOrigin]
) -> str:
    """Skip a scheduled run when the lock is held; hold a trigger fire's events for the next run.

    The next scan picks a scheduled run back up. A trigger fire has no next scan,
    and self-wiring lands its reply exactly while the run that sent the email is
    finishing, so the events wait in the todo's buffer for the drain run.
    """
    if origin is None:
        log.info("tracked_todo.execute_lock_held", todo_id=todo_id)
        return f"skipped:{todo_id} (lock held)"

    for event in [origin, *coalesced]:
        if await buffer_todo_trigger_event(todo_id, event):
            continue
        log.error(
            "tracked_todo.trigger_event_lost_lock_held",
            todo_id=todo_id,
            trigger_name=event.trigger_name,
            subscription_id=event.subscription_id,
        )
        doc = await todo_repository.get_by_id(todo_id)
        if doc is not None:
            await record_activity(
                todo_id,
                doc.user_id,
                TodoActivityEvent.RUN_SKIPPED,
                f"dropped a {event.trigger_name} event: a run was going and it could not be held",
            )
    log.info("tracked_todo.trigger_fire_held", todo_id=todo_id, events=1 + len(coalesced))
    return f"held:{todo_id} (lock held)"


async def _hold_fire_events_for_catch_up(
    todo_id: str, origin: TriggerOrigin, coalesced: Sequence[TriggerOrigin]
) -> None:
    """Hold drained fire events again for the catch-up drain instead of dropping them."""
    # Buffering schedules the drain itself, so this is also the catch-up arrangement.
    for event in [origin, *coalesced]:
        if not await buffer_todo_trigger_event(todo_id, event):
            log.error(
                "tracked_todo.trigger_event_lost_paused",
                todo_id=todo_id,
                trigger_name=event.trigger_name,
                subscription_id=event.subscription_id,
            )


async def _paused_result(
    doc: TodoDocument,
    user_tz: Timezone,
    origin: TriggerOrigin | None,
    coalesced: Sequence[TriggerOrigin],
) -> str | None:
    """Skip a run the account cannot make, holding fire events for the catch-up drain."""
    if not (paused := await _paused_reason(doc)):
        return None
    # Like a lapsed workflow: skip this occurrence, keep the schedule, run again once it clears.
    if origin is None:
        await _advance_schedule(
            doc, user_tz.value, one_time_rerun_at=datetime.now(UTC) + PAUSED_RUN_RECHECK
        )
    else:
        await _hold_fire_events_for_catch_up(doc.id, origin, coalesced)
    await record_activity(doc.id, doc.user_id, TodoActivityEvent.RUN_SKIPPED, paused)
    log.set(tracked_todo={"paused": paused})
    return f"paused:{doc.id}"


async def _execute_todo_with_retry(
    todo_id: str,
    origin: TriggerOrigin | None = None,
    armed_for: datetime | None = None,
    coalesced: Sequence[TriggerOrigin] = (),
) -> str:
    """Fetch the todo, execute it, and handle retry/recurrence logic on the result."""
    doc = await todo_repository.get_by_id(todo_id)
    if not doc:
        log.warning("tracked_todo.execute_not_found", todo_id=todo_id)
        return f"not_found:{todo_id}"

    if skipped := await _skip_reason(doc, origin, armed_for):
        return skipped
    user_id = doc.user_id
    retry_count = doc.gaia_retry_count

    owner = await _owner_ready_to_run(doc, origin, coalesced)
    if isinstance(owner, str):
        return owner
    user_data, user_tz = owner

    # Cost wall before any LLM work: a trigger fire is not a user action. The
    # window opens first, so a walled run still counts as its window's one run.
    if origin is not None:
        log.set(trigger_events=1 + len(coalesced))
        await open_trigger_window(trigger_window(doc))
        await enforce_daily_cost_budget(user_id, feature_key=TRIGGER_TODO_FEATURE_KEY)

    try:
        await _execute_on_executor(
            doc, user_data=user_data, user_tz=user_tz, origin=origin, coalesced=coalesced
        )
    except Exception as exc:
        log.exception("tracked_todo.execution_failed", todo_id=todo_id, error=str(exc))
        new_retry_count = retry_count + 1
        if new_retry_count < MAX_RETRY_ATTEMPTS:
            return await _schedule_retry(doc, new_retry_count, origin, coalesced)
        if doc.recurrence:
            await _give_up_occurrence(doc, user_tz.value, origin)
            return f"gave_up:{todo_id} (max retries reached; the next occurrence is armed)"
        await todo_repository.update(
            todo_id, user_id=user_id, update=TodoUpdate(gaia_retry_count=new_retry_count)
        )
        await _mark_todo_failed(todo_id, user_id, doc)
        return f"failed:{todo_id} (max retries reached)"

    # The run is delivered: a failure queueing what follows must not run it again.
    # A watch firing is not the todo's schedule, so only a scheduled run moves it on.
    advanced = origin is None and await _advance_schedule(doc, user_tz.value)
    if not advanced:
        await todo_repository.update(
            todo_id, user_id=user_id, update=TodoUpdate(gaia_retry_count=0)
        )
    return f"success:{todo_id}"


async def _schedule_retry(
    doc: TodoDocument,
    attempt: int,
    origin: TriggerOrigin | None,
    coalesced: Sequence[TriggerOrigin],
) -> str:
    """Queue the next attempt of a failed run on the backoff ladder."""
    if not 1 <= attempt <= len(RETRY_BACKOFF):
        raise ValueError(
            f"retry attempt {attempt} has no rung on the {len(RETRY_BACKOFF)}-rung ladder"
        )
    backoff = RETRY_BACKOFF[attempt - 1]
    next_attempt = datetime.now(UTC) + backoff
    if origin is None:
        # Parked on the backoff target: left in the past, scheduled_at matches
        # the safety net's due-query, which fires it on the next 30-minute scan.
        await todo_repository.update(
            doc.id,
            user_id=doc.user_id,
            update=TodoUpdate(gaia_retry_count=attempt, scheduled_at=next_attempt),
        )
        await tracked_todo_service.schedule_execution(doc.id, next_attempt)
    else:
        await todo_repository.update(
            doc.id, user_id=doc.user_id, update=TodoUpdate(gaia_retry_count=attempt)
        )
        # Carries origin and every event it coalesced, or the retry loses the payloads
        # it was woken for; no occurrence job id, which would fold it into a scheduled run.
        await enqueue_worker_job(
            await RedisPoolManager.get_pool(),
            EXECUTE_TRACKED_TODO_TASK,
            doc.id,
            origin,
            coalesced=list(coalesced),
            _defer_until=next_attempt,
        )
    await record_activity(
        doc.id,
        doc.user_id,
        TodoActivityEvent.RETRY_SCHEDULED,
        f"attempt {attempt + 1} of {MAX_RETRY_ATTEMPTS} at {next_attempt.isoformat()}",
    )
    log.info(
        "tracked_todo.retry_enqueued",
        todo_id=doc.id,
        next_attempt=next_attempt.isoformat(),
        attempt=attempt,
        max_attempts=MAX_RETRY_ATTEMPTS,
    )
    return f"retry:{doc.id} (attempt {attempt})"


async def _owner_ready_to_run(
    doc: TodoDocument, origin: TriggerOrigin | None, coalesced: Sequence[TriggerOrigin]
) -> tuple[AuthenticatedUser, Timezone] | str:
    """Return the owner and their timezone for a fire that runs, or the result of one that does not.

    One user fetch per run, reused for the next-run computation so a timezone change
    applies at once. The owner check comes first: a todo with no owner is retired,
    not paused for a plan nobody holds.
    """
    try:
        user_data, user_tz = await _load_user_with_tz(doc.user_id)
    except OwnerNotFoundError as missing:
        log.error(
            "tracked_todo.owner_not_a_user", todo_id=doc.id, user_id=doc.user_id, error=str(missing)
        )
        return await _retire_ownerless_todo(doc)
    if withheld := await _withheld_result(doc, origin, coalesced):
        return withheld
    if paused := await _paused_result(doc, user_tz, origin, coalesced):
        return paused
    return user_data, user_tz


async def _withheld_result(
    doc: TodoDocument, origin: TriggerOrigin | None, coalesced: Sequence[TriggerOrigin]
) -> str | None:
    """Return the result of a fire the todo's pause or its owner's lapsed plan withholds, or None."""
    if doc.pause_reason is not None:
        log.info("tracked_todo.execute_paused", todo_id=doc.id, pause_reason=doc.pause_reason)
        await _hold_events_while_paused(doc.id, origin, coalesced)
        return f"paused:{doc.id}"
    if not await is_paid(doc.user_id):
        return await _pause_unpaid(doc, origin, coalesced)
    return None


async def _hold_events_while_paused(
    todo_id: str, origin: TriggerOrigin | None, coalesced: Sequence[TriggerOrigin]
) -> None:
    """Keep a paused todo's trigger events for the resume to replay; a scheduled fire carries none."""
    events = [origin, *coalesced] if origin is not None else list(coalesced)
    for event in events:
        if not await hold_trigger_event_while_paused(todo_id, event):
            log.error(
                "tracked_todo.trigger_event_lost_paused",
                todo_id=todo_id,
                trigger_name=event.trigger_name,
                subscription_id=event.subscription_id,
            )


async def _pause_unpaid(
    doc: TodoDocument, origin: TriggerOrigin | None, coalesced: Sequence[TriggerOrigin]
) -> str:
    """Pause a todo whose owner is not paid, so the paywall blocks it once rather than every fire."""
    log.warning("tracked_todo.paused_subscription_required", todo_id=doc.id, user_id=doc.user_id)
    capture_paywall_block(doc.user_id, PAYWALL_FEATURE_TRACKED_TODO)
    await todo_repository.update(
        doc.id,
        user_id=doc.user_id,
        update=TodoUpdate(pause_reason=DeactivationReason.SUBSCRIPTION_LAPSED),
    )
    await record_activity(
        doc.id,
        doc.user_id,
        TodoActivityEvent.RUN_SKIPPED,
        "paused: runs need an active subscription, and resume when it starts",
    )
    await _hold_events_while_paused(doc.id, origin, coalesced)
    return f"paused:{doc.id} (subscription required)"


async def _give_up_occurrence(
    doc: TodoDocument, user_tz: str, origin: TriggerOrigin | None
) -> None:
    """Record and report a recurring todo's failed occurrence, then arm its next one.

    Labelling it failed would stop every later run until a human noticed, for an
    outage that is usually gone by the next occurrence.
    """
    await record_activity(
        doc.id,
        doc.user_id,
        TodoActivityEvent.OCCURRENCE_GIVEN_UP,
        f"gave up after {MAX_RETRY_ATTEMPTS} failed attempts; the next occurrence runs as "
        "scheduled",
    )
    await _notify_run_failed(
        doc,
        f"This run of '{doc.title}' failed after {MAX_RETRY_ATTEMPTS} attempts. "
        "It runs again at its next scheduled time.",
    )
    # A watch's run is not the schedule's occurrence: only the retry count is its to clear.
    advanced = origin is None and await _advance_schedule(doc, user_tz)
    if not advanced:
        await todo_repository.update(
            doc.id, user_id=doc.user_id, update=TodoUpdate(gaia_retry_count=0)
        )
    log.info("tracked_todo.occurrence_given_up", todo_id=doc.id)


async def _advance_schedule(
    doc: TodoDocument, user_tz: str, *, one_time_rerun_at: datetime | None = None
) -> bool:
    """Move scheduled_at to the next run and queue it; False when it was rescheduled mid-run.

    A one-time todo's schedule ends unless one_time_rerun_at names its next try.
    scheduled_at must name the next execution or the safety net re-queues the todo every scan.
    """
    next_run = (
        _compute_next_run(doc.recurrence, user_tz, anchor=doc.scheduled_at)
        if doc.recurrence
        else one_time_rerun_at
    )
    advanced = await todo_repository.update_if_scheduled_at(
        doc.id,
        doc.user_id,
        expected=doc.scheduled_at,
        update=TodoUpdate(gaia_retry_count=0, scheduled_at=next_run),
    )
    if advanced is None:
        # The run or the user set a new time while it ran; that time and its queued fire stand.
        log.info("tracked_todo.rescheduled_during_run", todo_id=doc.id)
        return False
    if next_run:
        await tracked_todo_service.schedule_execution(doc.id, next_run)
        await record_activity(
            doc.id,
            doc.user_id,
            TodoActivityEvent.SCHEDULED,
            f"next run {next_run.isoformat()} ({doc.recurrence or 'once'})",
        )
        log.info("tracked_todo.re_enqueued", todo_id=doc.id, next_run=next_run.isoformat())
    return True


# Todos whose every run reads Gmail: the desk triages it, a thread todo fetches its thread.
_GMAIL_REF_SOURCES = frozenset({ExternalRefSource.INBOX_DESK, ExternalRefSource.GMAIL_THREAD})


async def _paused_reason(doc: TodoDocument) -> str | None:
    """Say why the todo cannot run right now: Gmail work without Gmail connected."""
    needs_gmail = doc.external_ref is not None and doc.external_ref.source in _GMAIL_REF_SOURCES
    if needs_gmail and GMAIL_INTEGRATION_ID not in await get_connected_integration_ids(doc.user_id):
        return "skipped: Gmail is not connected"
    return None


async def _skip_reason(
    doc: TodoDocument, origin: TriggerOrigin | None, armed_for: datetime | None
) -> str | None:
    """Return the result of a fire this todo must not run, or None when it runs."""
    todo_id = doc.id
    if doc.completed:
        log.info("tracked_todo.execute_already_completed", todo_id=todo_id)
        return f"completed:{todo_id}"

    # Skip expired todos — let maintenance sweep handle gracefully. Clearing the
    # schedule stops the safety net re-queueing this skip every 30 minutes.
    if doc.expires_at and doc.expires_at <= datetime.now(UTC):
        log.info(
            "tracked_todo.execute_expired",
            todo_id=todo_id,
            expires_at=doc.expires_at.isoformat(),
        )
        if doc.scheduled_at is not None:
            await todo_repository.update(
                todo_id, user_id=doc.user_id, update=TodoUpdate(scheduled_at=None)
            )
            await record_activity(
                todo_id,
                doc.user_id,
                TodoActivityEvent.RUN_SKIPPED,
                f"not run: the todo expired at {doc.expires_at.isoformat()}",
            )
        return f"expired:{todo_id}"

    # Skip failed todos — user must manually reset before re-execution
    if FAILED_LABEL in doc.labels:
        log.info("tracked_todo.execute_marked_failed", todo_id=todo_id)
        return f"skipped:{todo_id} (marked failed)"

    if origin is None and not _fires_current_schedule(doc, armed_for):
        scheduled = doc.scheduled_at.isoformat() if doc.scheduled_at else None
        log.warning(
            "tracked_todo.stale_fire_skipped",
            todo_id=todo_id,
            scheduled_at=scheduled,
            armed_for=armed_for.isoformat() if armed_for else None,
        )
        await record_activity(
            todo_id,
            doc.user_id,
            TodoActivityEvent.RUN_SKIPPED,
            "dropped a leftover fire from an earlier schedule "
            f"(now scheduled: {scheduled or 'nothing'})",
        )
        return f"stale_occurrence:{todo_id}"
    return None


def _fires_current_schedule(doc: TodoDocument, armed_for: datetime | None) -> bool:
    """Whether a scheduled fire is for the occurrence the todo's scheduled_at names.

    ARQ cannot cancel a deferred job, so a reschedule leaves the old one queued. A
    stamped fire must match to the second; an unstamped one, queued before jobs
    carried their occurrence, cannot say which it was for and runs only when due.
    """
    if doc.scheduled_at is None:
        return False
    if armed_for is None:
        return doc.scheduled_at <= datetime.now(UTC) + TODO_SCHEDULE_FIRE_GRACE
    return occurrence_stamp(doc.scheduled_at) == occurrence_stamp(armed_for)


def _woken_by(origin: TriggerOrigin | None, coalesced: Sequence[TriggerOrigin]) -> str:
    """Name what woke a run, for its activity.md entries."""
    if origin is None:
        return "scheduled run"
    if not coalesced:
        return f"run on {origin.trigger_name}"
    names = ", ".join(sorted({event.trigger_name for event in [origin, *coalesced]}))
    return f"run on {1 + len(coalesced)} events ({names})"


def _trigger_type(origin: TriggerOrigin | None) -> TriggerType:
    """Name what woke this run: its own schedule, or a watch that fired."""
    return TriggerType.SCHEDULED_TODO if origin is None else TriggerType.TODO_TRIGGER


async def _execute_on_executor(
    doc: TodoDocument,
    *,
    user_data: AuthenticatedUser,
    user_tz: Timezone,
    origin: TriggerOrigin | None = None,
    coalesced: Sequence[TriggerOrigin] = (),
) -> None:
    """Run the todo on the executor; its delivery step writes the finish entry and any message."""
    doc = await with_desk_notes(doc)
    todo_id = doc.id
    user_id = doc.user_id
    prompt = build_execution_prompt(
        doc,
        context=await collect_run_context(doc),
        origin=origin,
        coalesced=coalesced,
        local_now=datetime.now(user_tz.tzinfo),
    )

    # A fresh conversation per run: runs are independent, and history must not
    # accumulate in the checkpointer.
    conversation_id = str(uuid4())
    woken_by = _woken_by(origin, coalesced)
    await record_activity(
        todo_id,
        user_id,
        TodoActivityEvent.RUN_STARTED,
        f"{woken_by} (conversation {conversation_id[:8]})",
    )
    try:
        await run_todo_on_executor(
            TodoRunRequest(
                user=user_data,
                todo_run=TodoRun(todo_id=todo_id, trigger_type=_trigger_type(origin)),
                todo_title=doc.title,
                task=prompt,
                conversation_id=conversation_id,
            )
        )
    except Exception as exc:
        await record_activity(
            todo_id,
            user_id,
            TodoActivityEvent.RUN_FAILED,
            f"{woken_by} failed ({type(exc).__name__}: {str(exc)[:160]})",
        )
        raise
    log.info("tracked_todo.run_completed", todo_id=todo_id)


async def resume_tracked_todo(
    ctx: Mapping[str, object],  # noqa: ARG001 -- ARQ injects ctx positionally into every registered task
    todo_id: str,
    conversation_id: str,
    approval_id: str,
    receipt: str,
    attempt: int = 0,
) -> str:
    """Continue a parked execution in its OWN conversation after an approval.

    A resume must inherit the parked run's thread — its reasoning, partial tool
    results, and checkpoint live there. Reusing the conversation is the deliberate
    exception to the fresh-uuid rule: resumes are human-gated and rare.
    """
    log.set(todo_id=todo_id, approval_id=approval_id)
    pool = await RedisPoolManager.get_pool()
    acquired = await pool.set(
        RUN_LOCK_KEY.format(todo_id=todo_id), "1", nx=True, ex=LOCK_TTL_SECONDS
    )
    if not acquired:
        if attempt >= len(LOCK_DEFER_BACKOFF):
            log.warning("tracked_todo.resume_lock_held", todo_id=todo_id)
            return f"resume_dropped:{todo_id} (lock held)"
        retry_at = datetime.now(UTC) + LOCK_DEFER_BACKOFF[attempt]
        await enqueue_worker_job(
            pool,
            "resume_tracked_todo",
            todo_id,
            conversation_id,
            approval_id,
            receipt,
            attempt + 1,
            _defer_until=retry_at,
        )
        return f"resume_deferred:{todo_id} (lock held)"

    try:
        return await _resume_holding_lock(todo_id, conversation_id, approval_id, receipt)
    finally:
        await _release_run_lock(pool, todo_id)


async def _resume_holding_lock(
    todo_id: str, conversation_id: str, approval_id: str, receipt: str
) -> str:
    """Continue the parked run under the lock its caller holds; a failure is recorded and raised."""
    doc = await todo_repository.get_by_id(todo_id)
    if not doc:
        return f"not_found:{todo_id}"
    if doc.completed:
        return f"completed:{todo_id}"
    try:
        user_data, _ = await _load_user_with_tz(doc.user_id)
    except OwnerNotFoundError as missing:
        log.error(
            "tracked_todo.owner_not_a_user", todo_id=doc.id, user_id=doc.user_id, error=str(missing)
        )
        return await _retire_ownerless_todo(doc)
    user_id = doc.user_id

    try:
        await enforce_daily_cost_budget(user_id, feature_key=TRIGGER_TODO_FEATURE_KEY)

        await record_activity(
            todo_id,
            user_id,
            TodoActivityEvent.APPROVAL_GRANTED,
            f"{approval_id}: {receipt}; continuing the run in its own thread",
        )

        message = (
            f"Approval {approval_id} was granted: {receipt} "
            "The action has run — verify with a read if you need certainty, "
            "never re-run the granted call blind. Continue the run from here."
        )
        # The parked conversation, so the executor continues its own thread.
        await run_todo_on_executor(
            TodoRunRequest(
                user=user_data,
                todo_run=TodoRun(todo_id=todo_id, trigger_type=_trigger_type(None)),
                todo_title=doc.title,
                task=message,
                conversation_id=conversation_id,
            )
        )
        return f"resumed:{todo_id}"
    except Exception as exc:
        await record_activity(
            todo_id,
            user_id,
            TodoActivityEvent.RUN_FAILED,
            f"approval resume failed ({type(exc).__name__}: {str(exc)[:160]})",
        )
        raise


async def finish_tracked_todo_run(ctx: ArqJobContext, undone: FinishedTodoRun) -> str:
    """Finish the delivery a tracked todo run's own attempt could not: send, then record.

    The todo is never run again for it. Each try picks up only what is still
    undone, so a message already sent is not sent twice.
    """
    # The envelope already puts the job id (the run's) and job_try on the event.
    log.set(todo_id=undone.todo_id)
    user, _ = await _load_user_with_tz(undone.user_id)
    left = await finish_todo_run(undone, user)
    if left is None:
        return f"finished:{undone.todo_id}"
    if left.finish_entry != undone.finish_entry:
        # Sent on this try, entry not written: a replay of this job would send again.
        await hand_unfinished_run_to_job(left)
        return f"sent:{undone.todo_id} (entry handed on)"
    job_try = ctx["job_try"]
    if job_try < TODO_RUN_FINISH_MAX_TRIES:
        raise Retry(defer=TODO_RUN_FINISH_RETRY_DELAY * 2 ** (job_try - 1))
    report_unfinished_run(left, f"still failing after {job_try} tries")
    return f"failed:{undone.todo_id} (gave up)"


async def _mark_todo_failed(todo_id: str, user_id: str, doc: TodoDocument) -> None:
    """Mark the todo as permanently failed and notify the user in-app."""
    await todo_repository.add_labels(todo_id, user_id=user_id, labels=[FAILED_LABEL])
    # The execution path skips failed todos until a manual reset, so leaving the
    # subscriptions armed would burn events on a todo that can never run.
    await teardown_subscriptions(todo_id, user_id, reason="failed")
    await record_activity(
        todo_id,
        user_id,
        TodoActivityEvent.MARKED_FAILED,
        f"stopped after {MAX_RETRY_ATTEMPTS} failed attempts; runs resume once the failed "
        "label is removed",
    )
    log.info("tracked_todo.marked_failed", todo_id=todo_id)
    await _notify_run_failed(
        doc,
        f"Your scheduled task '{doc.title}' could not be completed after "
        f"{MAX_RETRY_ATTEMPTS} attempts. Please check the task and try again.",
    )


async def _notify_run_failed(doc: TodoDocument, body: str) -> None:
    """Tell the user in-app that a run used up its attempts; a failed send is only logged."""
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=doc.user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                type=NotificationType.ERROR,
                content=NotificationContent(title=f"Scheduled Task Failed: {doc.title}", body=body),
                metadata={"todo_id": doc.id, "retry_count": MAX_RETRY_ATTEMPTS},
            )
        )
    except Exception as notify_exc:
        log.warning(
            "tracked_todo.failure_notification_failed",
            todo_id=doc.id,
            error=str(notify_exc),
        )


def _compute_next_run(
    recurrence: str,
    recurrence_tz: str | None = None,
    anchor: datetime | None = None,
) -> datetime | None:
    """Compute the next scheduled run time from a recurrence string.

    Evaluated in recurrence_tz (IANA name); returns a UTC-aware datetime for
    ARQ's _defer_until. "daily"/"weekly" anchor to the original scheduled_at
    so a late run doesn't drift the wall-clock time forward; falls back to
    croniter for cron expressions. Returns None if unrecognised.
    """
    # Canonical, offset-safe zone resolution (a stored ±HH:MM won't crash here).
    home_tz = Timezone.parse(recurrence_tz)
    tz = home_tz.tzinfo

    now_utc = datetime.now(UTC)

    if recurrence in TODO_INTERVAL_RECURRENCES:
        # Intervals are deltas from "now" — drift is acceptable/expected.
        return now_utc + TODO_INTERVAL_RECURRENCES[recurrence]

    if recurrence in TODO_ANCHORED_RECURRENCES:
        step = TODO_ANCHORED_RECURRENCES[recurrence]
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

    # Cron expression — evaluate in the user's local timezone via the canonical
    # helper (single source of cron-in-zone math + observability).
    try:
        return get_next_run_time(recurrence, now_utc, home_tz)
    except CronError:
        log.warning("tracked_todo.next_run_unrecognised", recurrence=recurrence)
        return None


async def safety_net_check_orphaned_todos(_ctx: Mapping[str, object]) -> str:
    """Find scheduled tracked todos that should have run but were never picked up.

    Re-enqueues each one not already locked, with a random 0-60s jitter to
    spread load. The job is armed for the todo's scheduled_at, so a job still
    queued for that occurrence absorbs the enqueue instead of gaining a twin.
    """
    now = datetime.now(UTC)

    candidates = await todo_repository.find_due_tracked_all_users(
        now=now, max_retries=MAX_RETRY_ATTEMPTS, limit=100
    )
    log.set(tracked_todo={"candidates": len(candidates)})

    pool = await RedisPoolManager.get_pool()
    re_enqueued = 0
    skipped = 0

    for doc in candidates:
        todo_id = doc.id
        lock_exists = await pool.exists(RUN_LOCK_KEY.format(todo_id=todo_id))
        if lock_exists:
            skipped += 1
            continue

        jitter_seconds = random.randint(0, 60)  # nosec B311  # NOSONAR python:S2245 — non-crypto scheduling jitter
        run_at = now + timedelta(seconds=jitter_seconds)
        # Set by construction: the due query selects on scheduled_at <= now.
        armed_for = cast(datetime, doc.scheduled_at)
        if await tracked_todo_service.schedule_execution(todo_id, armed_for, defer_until=run_at):
            re_enqueued += 1
        else:
            skipped += 1

    log.set_ns("tracked_todo", re_enqueued=re_enqueued, skipped=skipped)
    return f"re_enqueued:{re_enqueued} skipped:{skipped}"
