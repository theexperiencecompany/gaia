"""Reminder scheduler for managing reminder tasks."""

from datetime import UTC, datetime

from arq.connections import RedisSettings

from app.db.repositories.reminders import reminder_repository
from app.models.reminder_models import (
    CreateReminderRequest,
    ReminderDocument,
    ReminderModel,
    ReminderStatus,
    ReminderUpdate,
)
from app.models.scheduler_models import (
    BaseScheduledTask,
    DeactivationReason,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
    TaskOutcome,
    TaskRearm,
)
from app.services.scheduler_service import BaseSchedulerService
from app.utils.cron_utils import get_next_run_time
from app.utils.occurrence import occurrence_stamp
from app.utils.schedule import InvalidScheduleError, validate_recurring_schedule
from app.utils.timezone import Timezone
from shared.py.wide_events import log


class ReminderScheduler(BaseSchedulerService):
    """Manage reminder scheduling and execution."""

    def __init__(self, redis_settings: RedisSettings | None = None):
        """Initialize the reminder scheduler."""
        super().__init__(redis_settings)

    def get_job_name(self) -> str:
        """Get the ARQ job name for reminder processing."""
        return "process_reminder"

    async def create_reminder(self, reminder_data: CreateReminderRequest, user_id: str) -> str:
        """Create a new reminder and schedule it. Returns the reminder ID."""
        is_recurring = reminder_data.repeat is not None
        now = datetime.now(UTC)
        scheduled_at = reminder_data.scheduled_at
        seconds_until_scheduled = (
            int((scheduled_at - now).total_seconds())
            if scheduled_at and scheduled_at > now
            else None
        )
        log.set(
            reminder={
                "user_id": user_id,
                "scheduled_at": str(reminder_data.scheduled_at),
                "is_recurring": is_recurring,
                "repeat": reminder_data.repeat,
                "seconds_until_scheduled": seconds_until_scheduled,
            }
        )
        # Create schedule config
        schedule_config = ScheduleConfig(
            repeat=reminder_data.repeat,
            scheduled_at=reminder_data.scheduled_at,
            max_occurrences=reminder_data.max_occurrences,
            stop_after=reminder_data.stop_after,
        )

        # Set scheduled_at if not provided — compute the first fire in the
        # reminder's own zone so it (and the recurrence, which reads
        # reminder.timezone) fire at the right local hour, not in UTC.
        if not schedule_config.scheduled_at:
            if schedule_config.repeat:
                schedule_config.scheduled_at = get_next_run_time(
                    schedule_config.repeat, tz=Timezone.parse(reminder_data.timezone)
                )
            else:
                raise ValueError("scheduled_at must be provided or repeat must be specified")

        # reminder_data.timezone flows through model_dump() onto the persisted
        # ReminderModel.timezone; handle_recurring_task reads it on re-arm.
        reminder_dict = reminder_data.model_dump()
        reminder_dict["scheduled_at"] = schedule_config.scheduled_at
        reminder = ReminderDocument(**reminder_dict, user_id=user_id)

        created = await reminder_repository.create(reminder)
        reminder_id = created.id

        # Schedule the task using base scheduler
        await self.schedule_task(reminder_id, schedule_config)

        log.info(
            "Created and scheduled reminder for",
            reminder_id=reminder_id,
            scheduled_at=created.scheduled_at,
        )
        return reminder_id

    async def update_reminder(self, reminder_id: str, update: ReminderUpdate, user_id: str) -> bool:
        """Update an existing reminder, rescheduling if scheduled_at changed.

        Returns True when a matching reminder was found. (The prior direct-Mongo path
        keyed on modified_count and returned False for a no-op update; the
        repository reports found/not-found, so an idempotent no-op now succeeds —
        the correct outcome.)
        """
        log.set(reminder_id=reminder_id, reminder_user_id=user_id)

        updated = await reminder_repository.update_for_user(reminder_id, user_id, update)
        if updated is None:
            return False

        log.info("Updated reminder", reminder_id=reminder_id)

        # If scheduled_at was updated, reschedule the task. ``model_fields_set``
        # is what the old dict's `"key" in update_data` checked — a field the
        # caller never touched must not trigger a reschedule.
        touched = update.model_fields_set
        if "scheduled_at" in touched and "status" in touched:
            if update.status == ReminderStatus.SCHEDULED and update.scheduled_at is not None:
                await self.reschedule_task(reminder_id, new_scheduled_at=update.scheduled_at)

        return True

    async def resume(self, reminder: ReminderModel) -> bool:
        """Return a paused reminder to SCHEDULED at its next fire in its own timezone.

        A series whose stop_after or max_occurrences ran out while paused completes
        instead. Raises InvalidScheduleError when its stored schedule breaks the
        rule; only the user can fix that, so it stays paused.
        """
        if not reminder.id:
            raise ValueError("Reminder must have an ID to resume")
        update = ReminderUpdate(status=ReminderStatus.SCHEDULED, pause_reason=None)
        if reminder.repeat:
            validate_recurring_schedule(reminder.repeat)
            next_run = get_next_run_time(reminder.repeat, tz=Timezone.parse(reminder.timezone))
            if self._should_continue_recurring(reminder, reminder.occurrence_count, next_run):
                update.scheduled_at = next_run
            else:
                update.status = ReminderStatus.COMPLETED
        return await self.update_reminder(reminder.id, update, reminder.user_id)

    async def resume_paused_for(self, user_id: str, reason: DeactivationReason) -> int:
        """Resume every reminder the system paused for reason; return the count resumed.

        One that cannot resume does not stop the rest; their failures are raised
        together at the end. A broken schedule is re-marked INVALID_SCHEDULE so no
        later resume retries it.
        """
        resumed = 0
        failures: list[Exception] = []
        for reminder in await reminder_repository.find_paused_for_reason(user_id, reason):
            try:
                await self.resume(reminder)
            except InvalidScheduleError as e:
                await self.pause_for_reason(reminder, DeactivationReason.INVALID_SCHEDULE)
                log.warning(
                    "Paused reminder kept paused: its schedule breaks the rule",
                    reminder_id=reminder.id,
                    user_id=user_id,
                    schedule_rejection=e.reason.value,
                )
                continue
            except Exception as e:  # the rest of the user's reminders must still resume
                log.warning(
                    "Paused reminder could not resume",
                    reminder_id=reminder.id,
                    user_id=user_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                failures.append(e)
                continue
            resumed += 1
        log.set(reminders_resumed=resumed, reminders_resume_reason=reason.value)
        if failures:
            raise ExceptionGroup(f"{len(failures)} paused reminder(s) could not resume", failures)
        return resumed

    async def list_user_reminders(
        self,
        user_id: str,
        status: ReminderStatus | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[ReminderDocument]:
        """List reminders for a user, optionally filtered by status."""
        return await reminder_repository.list_for_user(
            user_id, status=status, limit=limit, skip=skip
        )

    async def get_reminder(self, task_id: str, user_id: str | None = None) -> ReminderModel | None:
        task = await self.get_task(task_id, user_id)
        return task if isinstance(task, ReminderModel) else None

    # Implementation of abstract methods from BaseSchedulerService

    async def get_task(self, task_id: str, user_id: str | None = None) -> BaseScheduledTask | None:
        """Get a reminder by ID (owner-scoped when user_id is given)."""
        if user_id:
            return await reminder_repository.get_for_user(task_id, user_id)
        return await reminder_repository.get(task_id)

    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """Execute a reminder task."""
        try:
            # Import here to avoid circular imports
            # Deferred import: breaks circular import: app.tasks.reminder_tasks reaches back into this service
            from app.tasks.reminder_tasks import (  # noqa: PLC0415 -- deferred
                execute_reminder_by_agent,
            )

            # Ensure task is a ReminderModel
            if not isinstance(task, ReminderModel):
                return TaskExecutionResult(
                    outcome=TaskOutcome.FAILED, message="Task is not a ReminderModel"
                )

            outcome = await execute_reminder_by_agent(task)

            return TaskExecutionResult(
                outcome=outcome, message=f"Reminder {task.id}: {outcome.value}"
            )
        except Exception as e:
            return TaskExecutionResult(
                outcome=TaskOutcome.FAILED, message=f"Failed to execute reminder: {e!s}"
            )

    async def pause_for_reason(self, task: BaseScheduledTask, reason: DeactivationReason) -> None:
        """Pause the reminder with a system reason, so the resume that owns reason can find it."""
        if not task.id:
            raise ValueError("Reminder must have an ID to pause")
        await reminder_repository.set_status(task.id, ReminderStatus.PAUSED, pause_reason=reason)

    async def find_stale_executing(self, cutoff: datetime) -> list[BaseScheduledTask]:
        """Reminders wedged in EXECUTING since before cutoff."""
        return list(await reminder_repository.find_stale_executing(cutoff))

    async def claim_task_for_execution(
        self, task_id: str, expected_occurrence: datetime | None = None
    ) -> bool:
        """Claim this reminder for one fire; False if another worker already has it."""
        return await reminder_repository.claim_for_execution(
            task_id, expected_scheduled_at=expected_occurrence
        )

    def _build_job_args(self, task_id: str, scheduled_at: datetime) -> tuple[object, ...]:
        """Stamp the occurrence this job is armed for, so a stale job can be rejected.

        Carried as a unix int because ARQ args are serialized; the worker turns
        it back into the datetime the claim pins on.
        """
        return (task_id, occurrence_stamp(scheduled_at))

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        rearm: TaskRearm | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Update reminder status plus its re-arm fields; a reminder has no next_run or repeat to write."""
        rearm = rearm or TaskRearm()
        scheduled_at = rearm.scheduled_at if isinstance(rearm.scheduled_at, datetime) else None
        return await reminder_repository.set_status(
            task_id,
            status,
            user_id=user_id,
            occurrence_count=rearm.occurrence_count,
            scheduled_at=scheduled_at,
        )

    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        """Reminders that are scheduled and due (scheduled_at <= now).

        The due-scan lives on the repository (find_pending_before) with the same
        $lte semantics the workflow scan uses, so the two can't diverge (reminders
        once used $gte and silently dropped overdue tasks).
        """
        pending: list[BaseScheduledTask] = []
        pending.extend(await reminder_repository.find_pending_before(current_time))
        return pending


reminder_scheduler = ReminderScheduler()
