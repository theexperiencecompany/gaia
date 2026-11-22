"""A GAIA task's scheduled run: claimed, run on the executor in its chat, then settled.

The claim (idle to running, pinned to the occurrence the job was armed for) is the run's
lock: a second fire for the same task while it runs is skipped, and a run a dead worker
left running is reaped by recovery. A run that fails is retried on the backoff ladder,
then the task is marked failed and the user told once. A run that ends leaves a one-off
task done, with a next step it set, or with one code sets (parked as unplanned), and a
repeating task armed for its next occurrence. Every run writes one task_runs record.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.agents.core.background.session import TaskRun
from app.agents.core.background.todo_run import (
    ExecutorBusyError,
    TodoRunCancelledError,
    TodoRunRequest,
    run_todo_on_executor,
)
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.tasks import (
    EXECUTOR_BUSY_RECHECK,
    PAYWALL_FEATURE_GAIA_TASK,
    TaskFlag,
    TaskLogEvent,
    TaskRunStatus,
    TaskRunTrigger,
)
from app.constants.todos import (
    MAX_HOLD_CHECKS,
    MAX_RETRY_ATTEMPTS,
    OPEN_STATE_REPAIR_CHECK,
    PAUSED_RUN_RECHECK,
    RETRY_BACKOFF,
    TodoWakeKind,
    WaitingOn,
)
from app.db.repositories.tasks import task_repository
from app.decorators.entitlements import capture_paywall_block, is_paid
from app.models.message_models import TodoRunWake
from app.models.notification.notification_models import (
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.models.scheduler_models import DeactivationReason
from app.models.task_models import RepeatWhen, TaskDocument, TaskUpdate, Waiting
from app.models.todo_models import ExternalRefSource
from app.models.user_models import AuthenticatedUser
from app.services.analytics_service import capture
from app.services.conversation_service import get_or_create_task_conversation
from app.services.integrations.user_integrations import get_connected_integration_ids
from app.services.notification_service import notification_service
from app.services.tasks.arming import arm_at
from app.services.tasks.completion import complete_task
from app.services.tasks.open_state import hold_ran_out, wake_budget_update
from app.services.tasks.run_brief import build_scheduled_brief, collect_run_context
from app.services.tasks.run_records import (
    close_run,
    open_run,
    record_event,
    record_skipped_run,
)
from app.services.tasks.schedule import next_occurrence
from app.services.tasks.todo_rounds import task_redirect_action
from app.utils.auth_utils import OwnerNotFoundError, require_owner
from app.utils.timezone import Timezone
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskOpenStateRepaired, TaskRunFailed
from shared.py.wide_events import log

#: Tasks whose every run reads Gmail: the desk triages it, a thread task fetches its thread.
_GMAIL_REF_SOURCES = frozenset({ExternalRefSource.INBOX_DESK, ExternalRefSource.GMAIL_THREAD})


async def run_gaia_task(task: TaskDocument, armed_for: datetime) -> str:
    """Run the GAIA task for the occurrence armed_for names; return what became of the fire."""
    if skipped := await _skip_reason(task):
        return skipped
    try:
        user = await require_owner(task.user_id)
    except OwnerNotFoundError as missing:
        log.error("task.owner_not_a_user", task_id=task.id, error=str(missing))
        await complete_task(task, "closed: its owner is not a GAIA user")
        return f"no_owner:{task.id}"
    if not await is_paid(task.user_id):
        return await _pause_unpaid(task)
    if paused := await _paused_reason(task):
        return await _skip_while_paused(task, paused)

    claimed = await task_repository.claim_run(task.id, armed_for=armed_for)
    if claimed is None:
        log.info("task.run_not_claimed", task_id=task.id)
        return f"skipped:{task.id} (a run is going, or it moved off this time)"
    ran: TaskRunStatus | None = None
    try:
        ran, outcome = await _run_claimed(claimed, user)
        return outcome
    finally:
        await task_repository.finish_run(claimed.id, user_id=claimed.user_id, ran=ran)


async def _skip_reason(task: TaskDocument) -> str | None:
    """Return the result of a fire this task must not run, or None when it runs."""
    if task.completed:
        return f"completed:{task.id}"
    if not task.active:
        return f"paused:{task.id}"
    if TaskFlag.FAILED in task.status_flags:
        return f"skipped:{task.id} (marked failed)"
    if task.expires_at is not None and task.expires_at <= datetime.now(UTC):
        # The maintenance sweep closes an expired task; clearing its check stops recovery re-arming it.
        if task.next_check_at is not None:
            await task_repository.update(
                task.id, user_id=task.user_id, update=TaskUpdate(next_check_at=None)
            )
            await record_skipped_run(
                task,
                TaskRunTrigger.SCHEDULE,
                f"not run: it expired at {task.expires_at.isoformat()}",
            )
        return f"expired:{task.id}"
    return None


async def _pause_unpaid(task: TaskDocument) -> str:
    """Pause a task whose owner is not paid, so the paywall blocks it once rather than every fire."""
    log.warning("task.paused_subscription_required", task_id=task.id)
    capture_paywall_block(task.user_id, PAYWALL_FEATURE_GAIA_TASK)
    paused = await task_repository.deactivate(
        task.id, user_id=task.user_id, reason=DeactivationReason.SUBSCRIPTION_LAPSED
    )
    if paused is not None:
        await record_skipped_run(
            paused,
            TaskRunTrigger.SCHEDULE,
            "paused: runs need an active subscription, and resume when it starts",
        )
    return f"paused:{task.id} (subscription required)"


async def _paused_reason(task: TaskDocument) -> str | None:
    """Say why the task cannot run right now: Gmail work without Gmail connected."""
    ref = task.external_ref
    if ref is None or ref.source not in _GMAIL_REF_SOURCES:
        return None
    if GMAIL_INTEGRATION_ID in await get_connected_integration_ids(task.user_id):
        return None
    return "skipped: Gmail is not connected"


async def _skip_while_paused(task: TaskDocument, reason: str) -> str:
    """Skip this occurrence and look again later, as a lapsed workflow does."""
    await record_skipped_run(task, TaskRunTrigger.SCHEDULE, reason)
    if isinstance(task.when, RepeatWhen):
        await _advance_repeat(task, task.when)
    else:
        await _come_round_at(task, datetime.now(UTC) + PAUSED_RUN_RECHECK)
    return f"paused:{task.id}"


async def _run_claimed(
    task: TaskDocument, user: AuthenticatedUser
) -> tuple[TaskRunStatus | None, str]:
    """Run the claimed task and settle it; return how the run ended and the fire's result."""
    if task.retry_count == 0 and (spend := wake_budget_update(task)):
        # Spent before the run, so a retry of this same run does not spend it again.
        spent = await task_repository.update(task.id, user_id=task.user_id, update=spend)
        if spent is None:
            raise LookupError(f"task {task.id} vanished before its run")
        task = spent
    brief = build_scheduled_brief(
        task, await collect_run_context(task, Timezone.parse(user.timezone))
    )
    conversation_id = await get_or_create_task_conversation(task.user_id, task.id, task.title)
    task_run = TaskRun(
        task_id=task.id,
        run_id=str(uuid4()),
        trigger_type=TaskRunTrigger.SCHEDULE.value,
        runs_once=not isinstance(task.when, RepeatWhen) and not task.subscriptions,
    )

    async def opened() -> None:
        await open_run(task, task_run, conversation_id)

    try:
        await run_todo_on_executor(
            TodoRunRequest(
                user=user,
                todo_run=task_run,
                todo_title=task.title,
                task=brief,
                conversation_id=conversation_id,
                fresh_thread=True,
                wake=TodoRunWake(
                    kind=TodoWakeKind.SCHEDULE, trigger_names=[], approval_summary=None
                ),
                on_started=opened,
            )
        )
    except ExecutorBusyError:
        # Another run holds the task's chat: this one waits, it did not fail.
        await record_skipped_run(
            task, TaskRunTrigger.SCHEDULE, "waits: another run is going in its chat"
        )
        await _come_round_at(task, datetime.now(UTC) + EXECUTOR_BUSY_RECHECK)
        return None, f"skipped:{task.id} (its chat is busy)"
    except TodoRunCancelledError:
        await close_run(task, task_run, TaskRunStatus.CANCELLED, "stopped by the user")
        await _settle(task)
        return TaskRunStatus.CANCELLED, f"cancelled:{task.id}"
    except Exception as exc:  # every failure is retried on the ladder, then marked failed
        log.exception("task.run_failed", task_id=task.id, error=str(exc))
        await close_run(
            task, task_run, TaskRunStatus.FAILED, f"{type(exc).__name__}: {str(exc)[:160]}"
        )
        return TaskRunStatus.FAILED, await _after_failure(task)
    await _settle(task)
    return TaskRunStatus.SUCCESS, f"success:{task.id}"


async def _after_failure(task: TaskDocument) -> str:
    """Retry a failed run on the ladder; past its last rung, give up on it."""
    attempt = task.retry_count + 1
    if attempt < MAX_RETRY_ATTEMPTS:
        next_attempt = datetime.now(UTC) + RETRY_BACKOFF[attempt - 1]
        await _come_round_at(task, next_attempt, retry_count=attempt)
        await record_event(
            task,
            TaskLogEvent.RETRY_SCHEDULED,
            f"attempt {attempt + 1} of {MAX_RETRY_ATTEMPTS} at {next_attempt.isoformat()}",
        )
        return f"retry:{task.id} (attempt {attempt})"
    if isinstance(task.when, RepeatWhen):
        # Marking a repeat failed would stop every later run for an outage usually gone by then.
        await _notify_run_failed(
            task,
            f"This run of '{task.title}' failed after {MAX_RETRY_ATTEMPTS} attempts. "
            "It runs again at its next scheduled time.",
        )
        await _advance_repeat(task, task.when)
        return f"gave_up:{task.id} (max retries reached; the next occurrence is armed)"
    await task_repository.update(
        task.id, user_id=task.user_id, update=TaskUpdate(retry_count=attempt)
    )
    await task_repository.add_flags(task.id, user_id=task.user_id, flags=[TaskFlag.FAILED])
    await record_event(
        task,
        TaskLogEvent.MARKED_FAILED,
        f"stopped after {MAX_RETRY_ATTEMPTS} failed attempts; runs resume once the failed "
        "flag is cleared",
    )
    capture(UserId(task.user_id), TaskRunFailed(task_id=task.id, attempts=MAX_RETRY_ATTEMPTS))
    await _notify_run_failed(
        task,
        f"Your scheduled task '{task.title}' could not be completed after "
        f"{MAX_RETRY_ATTEMPTS} attempts. Please check the task and try again.",
    )
    return f"failed:{task.id} (max retries reached)"


async def _notify_run_failed(task: TaskDocument, body: str) -> None:
    await notification_service.create_notification(
        NotificationRequest(
            user_id=task.user_id,
            source=NotificationSourceEnum.BACKGROUND_JOB,
            type=NotificationType.ERROR,
            content=NotificationContent(
                title=f"Scheduled Task Failed: {task.title}",
                body=body,
                actions=[task_redirect_action(task.id)],
            ),
            metadata={"task_id": task.id, "retry_count": MAX_RETRY_ATTEMPTS},
        )
    )


async def _come_round_at(
    task: TaskDocument, moment: datetime, *, retry_count: int | None = None
) -> None:
    """Bring the task round again at moment and arm it, unless it was rescheduled meanwhile.

    A one-off moves its next check; a repeat moves this occurrence, as a retry of it.
    """
    fields: dict[str, object] = {} if retry_count is None else {"retry_count": retry_count}
    if isinstance(task.when, RepeatWhen) and task.when.next_run is not None:
        fields["when"] = task.when.model_copy(update={"next_run": moment})
        moved = await task_repository.update_if_next_run(
            task.id,
            task.user_id,
            expected=task.when.next_run,
            update=TaskUpdate.model_validate(fields),
        )
    else:
        moved = await task_repository.update_if_next_check_at(
            task.id,
            task.user_id,
            expected=task.next_check_at,
            update=TaskUpdate.model_validate({**fields, "next_check_at": moment}),
        )
    if moved is None:
        log.info("task.rescheduled_during_run", task_id=task.id)
        return
    await arm_at(task.id, moment)


async def _advance_repeat(task: TaskDocument, when: RepeatWhen) -> None:
    """Arm a repeat's next occurrence, unless its schedule moved meanwhile."""
    expected = when.next_run
    if expected is None:
        return
    zone = when.timezone or (await require_owner(task.user_id)).timezone
    upcoming = next_occurrence(when.rule, zone, anchor=expected)
    advanced = await task_repository.update_if_next_run(
        task.id,
        task.user_id,
        expected=expected,
        update=TaskUpdate(retry_count=0, when=when.model_copy(update={"next_run": upcoming})),
    )
    if advanced is None:
        log.info("task.rescheduled_during_run", task_id=task.id)
        return
    if upcoming is not None:
        await arm_at(task.id, upcoming)
        await record_event(task, TaskLogEvent.SCHEDULED, f"next run {upcoming.isoformat()}")


async def _settle(woke: TaskDocument) -> None:
    """Leave the task with a next step after its run; the run's own close or reschedule stands.

    The run is delivered, so a failure here must not run it again: parking is the one
    write that has to land, and it is recorded loudly because it means the model failed.
    """
    if isinstance(woke.when, RepeatWhen):
        await _advance_repeat(woke, woke.when)
        return
    current = await task_repository.get(woke.id, user_id=woke.user_id)
    if current is None:
        return
    if current.completed or current.next_check_at != woke.next_check_at:
        log.info("task.settled_by_its_run", task_id=woke.id)
        if current.retry_count:
            await task_repository.update(
                woke.id, user_id=woke.user_id, update=TaskUpdate(retry_count=0)
            )
        return
    if current.pause_reason is not None:
        await _clear_check(current, TaskUpdate(retry_count=0, next_check_at=None))
        return
    if hold_ran_out(current):
        await complete_task(
            current, f"closed: the question went unanswered through {MAX_HOLD_CHECKS} checks"
        )
        log.warning("task.unanswered_hold_closed", task_id=woke.id)
        return
    next_check = datetime.now(UTC) + OPEN_STATE_REPAIR_CHECK
    parked = await task_repository.update_if_next_check_at(
        current.id,
        current.user_id,
        expected=woke.next_check_at,
        update=TaskUpdate(
            retry_count=0, next_check_at=next_check, waiting=Waiting(on=WaitingOn.UNPLANNED)
        ),
    )
    if parked is None:
        log.info("task.rescheduled_during_run", task_id=woke.id)
        return
    await arm_at(parked.id, next_check)
    await record_event(
        parked,
        TaskLogEvent.OPEN_STATE_REPAIRED,
        "the run ended with no next step even after being sent back, so GAIA parked it "
        f"as unplanned with a check at {next_check.isoformat()}",
    )
    waiting_on = woke.waiting.on.value if woke.waiting else None
    log.warning("task.open_state_repaired", task_id=woke.id, waiting_on=waiting_on)
    capture(UserId(woke.user_id), TaskOpenStateRepaired(task_id=woke.id, waiting_on=waiting_on))


async def _clear_check(task: TaskDocument, update: TaskUpdate) -> None:
    if (
        await task_repository.update_if_next_check_at(
            task.id, task.user_id, expected=task.next_check_at, update=update
        )
        is None
    ):
        log.info("task.rescheduled_during_run", task_id=task.id)
