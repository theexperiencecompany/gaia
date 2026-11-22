"""A GAIA task's run on the app events that woke it: claimed, run in its chat, not settled.

A run carries the events its job was given and every event buffered for the task since,
and opens the task's event window, so events landing inside it ride the next run. A run
is not the task's schedule: it never moves the next check or the next repeat, which the
task's own runs and its subscriptions keep. Events that reach a task the system paused,
or whose owner's plan lapsed, are kept for its resume; a task that is done, stopped by the
user, failed or expired drops them. A failed run is retried with its events on the
backoff ladder, then a one-off task is marked failed.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agents.core.background.todo_run import (
    ExecutorBusyError,
    TodoRunCancelledError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.api.v1.middleware.tiered_rate_limiter import CostBudgetExceededException
from app.constants.tasks import (
    EXECUTOR_BUSY_RECHECK,
    RUN_TASK_JOB,
    TaskLogEvent,
    TaskRunStatus,
    TaskRunTrigger,
)
from app.constants.todos import (
    MAX_RETRY_ATTEMPTS,
    RETRY_BACKOFF,
    TRIGGER_TODO_FEATURE_KEY,
    TodoWakeKind,
)
from app.db.repositories.tasks import task_repository
from app.decorators import enforce_cost_budget
from app.decorators.entitlements import is_paid
from app.models.task_models import RepeatWhen, TaskDocument, TaskUpdate
from app.models.todo_wake_models import TodoRunWake
from app.models.trigger_subscription_models import TriggerOrigin
from app.models.user_models import AuthenticatedUser
from app.services.conversation_service import get_or_create_task_conversation
from app.services.tasks.event_window import (
    buffer_task_event,
    buffered_task_events,
    drain_task_events,
    event_window,
    event_window_end,
    keep_event_while_paused,
    open_event_window,
    reschedule_task_event_drain,
    stretch_event_window,
)
from app.services.tasks.gaia_run import (
    close_ownerless,
    finish_run,
    gmail_pause_reason,
    mark_failed,
    notify_occurrence_given_up,
    pause_unpaid,
    skip_reason,
    task_run_of,
)
from app.services.tasks.inbox_desk import is_inbox_desk, with_desk_notes
from app.services.tasks.run_brief import build_event_brief, collect_run_context
from app.services.tasks.run_records import close_run, open_run, record_event, record_skipped_run
from app.services.triggers.trigger_gate import GateHold, quiet_hours_hold
from app.services.user_service import get_quiet_hours
from app.utils.auth_utils import OwnerNotFoundError, require_owner
from app.utils.redis_utils import RedisPoolManager
from app.utils.timezone import Timezone
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


async def run_gaia_task_on_events(
    task: TaskDocument, carried: Sequence[TriggerOrigin], trigger_window: int | None
) -> str:
    """Run the task for the events its job carries, or for those its window buffered; return the result.

    trigger_window names the window a drain job was scheduled for; None for a job that
    carries its own events.
    """
    if trigger_window is not None and (deferred := await _defer_drain(task, trigger_window)):
        return deferred
    user = await _owner_ready_to_run(task, carried)
    if isinstance(user, str):
        return user
    claimed = await task_repository.claim_run(task.id, armed_for=None)
    if claimed is None:
        # Another run holds the task; its end schedules the drain these events wait on.
        for event in carried:
            await _buffer_or_raise(task, event)
        return f"held:{task.id} (a run is going)"
    ran: TaskRunStatus | None = None
    try:
        events = await _events_of(claimed, carried)
        if not events:
            return f"skipped:{task.id} (no events to run on)"
        ran, outcome = await _run_claimed(claimed, user, events)
        return outcome
    finally:
        await finish_run(claimed, ran)


async def _owner_ready_to_run(
    task: TaskDocument, carried: Sequence[TriggerOrigin]
) -> AuthenticatedUser | str:
    """Return the owner of a task that runs on its events now, or the result of a fire that does not.

    Events reaching a task the system paused, or whose owner's plan lapsed, are kept for
    its resume; a task that is done, stopped by the user, failed or expired drops them.
    """
    if task.pause_reason is not None:
        return await _keep_while_paused(task, carried, f"paused:{task.id}")
    if skipped := await skip_reason(task, TaskRunTrigger.APP_EVENT):
        log.set_ns("task_event", dropped=len(carried))
        return skipped
    try:
        user = await require_owner(task.user_id)
    except OwnerNotFoundError as missing:
        return await close_ownerless(task, missing)
    if not await is_paid(task.user_id):
        paused = await pause_unpaid(task, TaskRunTrigger.APP_EVENT)
        return await _keep_while_paused(task, carried, paused)
    if paused := await gmail_pause_reason(task):
        await record_skipped_run(task, TaskRunTrigger.APP_EVENT, paused)
        return await _keep_while_paused(task, carried, f"paused:{task.id}")
    return user


async def _defer_drain(task: TaskDocument, trigger_window: int) -> str | None:
    """Return why the drain of the window ending at trigger_window does not run now, or None.

    A desk's due briefing answers what it holds. Otherwise it waits for a later window a
    run has opened, which quiet hours stretch to their end when the task's gates hold
    every event it buffered.
    """
    if _briefing_due(task):
        return f"deferred:{task.id} (its scheduled run answers the held events)"
    if (hold := await _quiet_hours_hold(task)) is not None:
        await stretch_event_window(task.id, hold.until)
    later = await event_window_end(task.id)
    if later is not None and later > trigger_window:
        await reschedule_task_event_drain(task.id)
        return f"deferred:{task.id} (its event window is open until {later})"
    return None


def _briefing_due(task: TaskDocument) -> bool:
    """Whether the task is a desk whose scheduled run is due, which reads every held event."""
    return (
        is_inbox_desk(task)
        and isinstance(task.when, RepeatWhen)
        and task.when.next_run is not None
        and task.when.next_run <= datetime.now(UTC)
    )


async def _quiet_hours_hold(task: TaskDocument) -> GateHold | None:
    """Return the hold every buffered event waits on, or None when any may run now.

    An urgent event, or one from a subscription with no gate, may; a run that carries it carries all.
    """
    events = await buffered_task_events(task.id)
    if not events or any(event.quiet_hours_bypass for event in events):
        return None
    gates = {subscription.id: subscription.gate for subscription in task.subscriptions}
    holds = [
        await quiet_hours_hold(gates.get(subscription_id), task.user_id)
        for subscription_id in {event.subscription_id for event in events}
    ]
    return None if None in holds else holds[0]


async def _keep_while_paused(task: TaskDocument, events: Sequence[TriggerOrigin], said: str) -> str:
    """Keep the run's events for the task's resume; one that cannot be kept is logged as lost."""
    for event in events:
        if not await keep_event_while_paused(task.id, event):
            await record_event(
                task,
                TaskLogEvent.APP_EVENT_DROPPED,
                f"a {event.trigger_name} event reached the paused task and could not be kept",
            )
    return said


async def _buffer_or_raise(task: TaskDocument, event: TriggerOrigin) -> None:
    if not await buffer_task_event(task.id, event):
        await record_event(
            task,
            TaskLogEvent.APP_EVENT_DROPPED,
            f"a {event.trigger_name} event arrived while a run was going and could not be held",
        )
        raise RuntimeError(f"an event for busy task {task.id} could not be held")


async def _events_of(task: TaskDocument, carried: Sequence[TriggerOrigin]) -> list[TriggerOrigin]:
    """Return the events this run carries, then every event buffered for the task."""
    buffered = await drain_task_events(task.id)
    # None is a Redis outage, already logged; the buffered events stay for the next drain.
    return [*carried, *(buffered or [])]


async def _run_claimed(
    task: TaskDocument, user: AuthenticatedUser, events: list[TriggerOrigin]
) -> tuple[TaskRunStatus | None, str]:
    """Run the claimed task on its events; return how the run ended and the job's result."""
    # Opened before the cost wall, so a walled run still counts as its window's one run.
    await open_event_window(event_window(task))
    try:
        await enforce_cost_budget(task.user_id, feature_key=TRIGGER_TODO_FEATURE_KEY)
    except CostBudgetExceededException as walled:
        await record_skipped_run(task, TaskRunTrigger.APP_EVENT, f"skipped: {walled.message}")
        return None, f"walled:{task.id}"
    task = await with_desk_notes(task)
    zone = Timezone.parse(user.timezone)
    brief = build_event_brief(
        task,
        await collect_run_context(task, zone),
        events,
        datetime.now(zone.tzinfo),
        await get_quiet_hours(task.user_id),
    )
    conversation_id = await get_or_create_task_conversation(task.user_id, task.id, task.title)
    task_run = task_run_of(
        task,
        TaskRunTrigger.APP_EVENT,
        TodoRunWake(
            kind=TodoWakeKind.TRIGGER,
            trigger_names=sorted({event.trigger_name for event in events}),
            approval_summary=None,
        ),
    )

    async def opened() -> None:
        await open_run(task, task_run, conversation_id)

    try:
        await run_todo_on_executor(
            TodoRunRequest(
                user=user,
                todo_run=task_run,
                task=brief,
                conversation_id=conversation_id,
                fresh_thread=True,
                on_started=opened,
            )
        )
    except ExecutorBusyError:
        # Another run holds the task's chat: these events wait for it, they did not fail.
        await record_skipped_run(
            task, TaskRunTrigger.APP_EVENT, "waits: another run is going in its chat"
        )
        await _run_later(task, events, datetime.now(UTC) + EXECUTOR_BUSY_RECHECK)
        return None, f"skipped:{task.id} (its chat is busy)"
    except TodoRunCancelledError:
        await close_run(task, task_run, TaskRunStatus.CANCELLED, "stopped by the user")
        return TaskRunStatus.CANCELLED, f"cancelled:{task.id}"
    except Exception as exc:  # every failure is retried on the ladder, then marked failed
        log.exception("task.event_run_failed", task_id=task.id, error=str(exc))
        await close_run(
            task, task_run, TaskRunStatus.FAILED, f"{type(exc).__name__}: {str(exc)[:160]}"
        )
        return TaskRunStatus.FAILED, await _after_failure(task, events)
    if task.retry_count:
        await task_repository.update(
            task.id, user_id=task.user_id, update=TaskUpdate(retry_count=0)
        )
    return TaskRunStatus.SUCCESS, f"success:{task.id}"


async def _run_later(task: TaskDocument, events: Sequence[TriggerOrigin], at: datetime) -> None:
    """Queue a run of the task on these events at at, carrying them so none is lost."""
    await enqueue_worker_job(
        await RedisPoolManager.get_pool(),
        RUN_TASK_JOB,
        task.id,
        None,
        events=list(events),
        _defer_until=at,
    )


async def _after_failure(task: TaskDocument, events: Sequence[TriggerOrigin]) -> str:
    """Retry a failed run with its events on the ladder; past its last rung, give up on it."""
    attempt = task.retry_count + 1
    if attempt < MAX_RETRY_ATTEMPTS:
        next_attempt = datetime.now(UTC) + RETRY_BACKOFF[attempt - 1]
        await task_repository.update(
            task.id, user_id=task.user_id, update=TaskUpdate(retry_count=attempt)
        )
        await _run_later(task, events, next_attempt)
        await record_event(
            task,
            TaskLogEvent.RETRY_SCHEDULED,
            f"attempt {attempt + 1} of {MAX_RETRY_ATTEMPTS} at {next_attempt.isoformat()}",
        )
        return f"retry:{task.id} (attempt {attempt})"
    if isinstance(task.when, RepeatWhen):
        # The run is not the schedule's occurrence: only its retry count is this run's to clear.
        await notify_occurrence_given_up(task)
        await task_repository.update(
            task.id, user_id=task.user_id, update=TaskUpdate(retry_count=0)
        )
        return f"gave_up:{task.id} (max retries reached)"
    return await mark_failed(task, attempt)
