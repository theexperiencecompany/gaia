"""
Base scheduler service for managing scheduled tasks.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.config.settings import settings
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.utils.cron_utils import get_next_run_time
from app.utils.occurrence import occurrence_stamp
from app.utils.timezone import Timezone
from app.workers.queue import enqueue_worker_job
from shared.py.wide_events import log


class TriggerConfigLike(Protocol):
    """The only two fields the base scheduler reads off a task's trigger_config.

    Structural rather than an import of ``workflow_models.TriggerConfig``: this
    scheduler serves both the reminder and the workflow domain, so it must not
    depend on either one's concrete model. Naming the fields is what stops a
    dict-shaped trigger_config from reaching here — on a dict, the timezone read
    silently yields None and the recurrence re-arms at the wrong wall-clock hour.
    """

    timezone: str | None
    next_run: datetime | None


# How long a task may sit in EXECUTING before the reaper assumes its worker died.
# Comfortably above the ARQ job timeout so a genuinely long run is never reaped
# out from under itself.
STALE_EXECUTING_THRESHOLD = timedelta(hours=1)


class BaseSchedulerService(ABC):
    """
    Base scheduler service that handles all scheduling-related functionality.

    This service manages:
    - ARQ pool for task queuing
    - Task scheduling and rescheduling
    - Recurring task logic
    - Task status management

    Subclasses must implement task-specific operations like CRUD and execution.
    """

    def __init__(self, redis_settings: RedisSettings | None = None):
        """Initialize the scheduler service."""
        self.redis_settings = redis_settings or RedisSettings.from_dsn(settings.REDIS_URL)
        self.arq_pool: ArqRedis | None = None

    async def initialize(self) -> None:
        """Initialize ARQ pool connection."""
        self.arq_pool = await create_pool(self.redis_settings)
        log.info("initialized", self_class_name=self.__class__.__name__)

    async def close(self) -> None:
        """Close ARQ pool connection."""
        if self.arq_pool:
            await self.arq_pool.aclose()
        log.info("closed", self_class_name=self.__class__.__name__)

    async def schedule_task(self, task_id: str, schedule_config: ScheduleConfig) -> bool:
        """Schedule a task using the provided configuration."""
        scheduled_at = schedule_config.scheduled_at

        # If no scheduled_at but has repeat, calculate next run time (from now in
        # UTC; callers that need a specific zone pre-compute scheduled_at).
        if not scheduled_at and schedule_config.repeat:
            scheduled_at = get_next_run_time(schedule_config.repeat)

        if not scheduled_at:
            raise ValueError("scheduled_at must be provided or repeat must be specified")

        return await self._enqueue_task(task_id, scheduled_at)

    async def reschedule_task(self, task_id: str, new_scheduled_at: datetime) -> bool:
        """Reschedule an existing task to a new time."""
        return await self._enqueue_task(task_id, new_scheduled_at)

    async def process_task_execution(
        self, task_id: str, expected_occurrence: datetime | None = None
    ) -> TaskExecutionResult:
        """Process a scheduled task execution: validate, execute, then handle
        recurring logic or update final status."""
        log.set(scheduler_task_id=task_id, scheduler_class=self.__class__.__name__)
        # Get the task
        task = await self.get_task(task_id)
        if not task:
            log.error("Task not found", task_id=task_id)
            return TaskExecutionResult(success=False, message=f"Task {task_id} not found")

        # Claim before executing, never "read the status then write it". Two ARQ
        # jobs for one task is the ordinary case: the startup scan runs in every
        # replica and every worker, and past-due tasks are re-armed to that
        # process's own ``now + 120s``, so the job ids differ and ARQ does not
        # dedup them. Under a read-then-write both jobs saw SCHEDULED and both
        # ran — the user got the reminder twice and both agent turns were
        # billed. The claim IS the SCHEDULED -> EXECUTING transition, so exactly
        # one job can win it.
        if not await self.claim_task_for_execution(task_id, expected_occurrence):
            log.warning("Task already claimed by another run", task_id=task_id)
            return TaskExecutionResult(
                success=False, message=f"Task {task_id} is not in scheduled status"
            )

        log.info("Processing task", task_id=task_id)

        occurrence_count = task.occurrence_count + 1

        try:
            execution_result = await self.execute_task(task)
        except Exception as e:
            log.error(
                "Failed to execute task", task_id=task_id, error=str(e), error_type=type(e).__name__
            )
            execution_result = TaskExecutionResult(
                success=False, message=f"Task execution failed: {e!s}"
            )

        if task.repeat:
            # Recurring tasks advance to the next occurrence on success AND failure:
            # a transient error must not silently kill the series (mirrors the workflow
            # executor). max_occurrences / stop_after still terminate the series.
            await self.handle_recurring_task(task, occurrence_count)
        elif execution_result.success:
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.COMPLETED,
                {"occurrence_count": occurrence_count},
            )
            log.info("Completed one-time task", task_id=task_id)
        else:
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.FAILED,
                {"occurrence_count": occurrence_count, "updated_at": datetime.now(UTC)},
            )
            log.warning(
                "One-time task failed", task_id=task_id, failure_reason=execution_result.message
            )

        return execution_result

    async def cancel_task(self, task_id: str, user_id: str) -> bool:
        """Cancel a scheduled task.

        ARQ has no direct job cancellation, so this marks the task cancelled in
        the DB; execution checks the status and skips if cancelled.
        """
        success = await self.update_task_status(
            task_id,
            ScheduledTaskStatus.CANCELLED,
            {"updated_at": datetime.now(UTC)},
            user_id,
        )

        if success:
            log.info("Cancelled task", task_id=task_id)

        return success

    async def scan_and_schedule_pending_tasks(self) -> None:
        """Scan for due scheduled tasks and enqueue them in ARQ (called at startup)."""
        now = datetime.now(UTC)
        tasks = await self.get_pending_task(now)

        scheduled_count = 0
        for task in tasks:
            if task.id and task.scheduled_at:
                await self._enqueue_task(task.id, task.scheduled_at)
                scheduled_count += 1

        log.info("Scheduled pending tasks", scheduled_count=scheduled_count)

    async def handle_recurring_task(self, task: BaseScheduledTask, occurrence_count: int) -> None:
        """
        Reschedule the next occurrence of a recurring task, or mark it completed
        once max_occurrences / stop_after is reached.

        Shared by the reminder path (via process_task_execution) and the workflow
        executor, so recurrence behaves identically for both.
        """
        log.set(
            scheduler_task_id=task.id,
            scheduler_occurrence_count=occurrence_count,
            scheduler_repeat=task.repeat,
            scheduler_max_occurrences=task.max_occurrences,
        )
        if not task.repeat:
            log.warning("Task has no repeat schedule", id=task.id)
            return

        if not task.id:
            log.error("Task ID is None, cannot handle recurring task")
            return

        trigger_config: TriggerConfigLike | None = getattr(task, "trigger_config", None)
        user_timezone = self._recurrence_timezone(task)
        log.set(scheduler_recurrence_timezone=user_timezone)

        # Advance from now, not from a (possibly stale) scheduled_at, so a dormant
        # task resumes at its next future occurrence instead of replaying missed runs.
        next_run = get_next_run_time(task.repeat, datetime.now(UTC), Timezone.parse(user_timezone))

        if self._should_continue_recurring(task, occurrence_count, next_run):
            await self._reschedule_recurring_task(task, occurrence_count, next_run, trigger_config)
        else:
            await self.update_task_status(
                task.id,
                ScheduledTaskStatus.COMPLETED,
                {"occurrence_count": occurrence_count},
            )
            log.info("Completed recurring task", id=task.id)

    @staticmethod
    def _recurrence_timezone(task: BaseScheduledTask) -> str | None:
        """The zone a task's cron is evaluated in; None means UTC.

        Reminders store it on the task itself; workflows store it on
        trigger_config (the zone the cron was authored against), which therefore
        wins. Both are read by name because only some subclasses declare them.
        """
        trigger_config: TriggerConfigLike | None = getattr(task, "trigger_config", None)
        trigger_timezone: str | None = trigger_config.timezone if trigger_config else None
        return trigger_timezone or getattr(task, "timezone", None)

    async def reap_stale_executing(self) -> int:
        """Recover tasks wedged in EXECUTING past the staleness threshold.

        A fire claims a task (scheduled -> executing) with no lease on the claim.
        If the worker dies before re-arming — a rolling deploy SIGKILLs it, or
        arq cancels the job and the retry finds the row already claimed — the row
        stays EXECUTING forever. Nothing can see it again: the due-scan filters
        on ``status="scheduled"``, and the claim gate can never match it. The
        reminder or workflow simply never fires, with no error and no retry.

        Returns the number of tasks reaped.
        """
        now = datetime.now(UTC)
        cutoff = now - STALE_EXECUTING_THRESHOLD
        reaped = 0

        for task in await self.find_stale_executing(cutoff):
            if not task.id:
                continue
            schedule_tz = Timezone.parse(self._recurrence_timezone(task))
            # A one-shot has no repeat: return it to SCHEDULED at its original
            # time so the due-scan picks it up on the next pass, rather than
            # dropping it for want of a next occurrence.
            next_run = get_next_run_time(task.repeat, now, schedule_tz) if task.repeat else None

            update_fields: dict[str, Any] = {"scheduled_at": next_run or task.scheduled_at}
            trigger_config: TriggerConfigLike | None = getattr(task, "trigger_config", None)
            if next_run is not None and trigger_config is not None:
                update_fields["trigger_config.next_run"] = next_run

            await self.update_task_status(task.id, ScheduledTaskStatus.SCHEDULED, update_fields)
            rearm_at = next_run or task.scheduled_at
            if rearm_at is not None:
                await self.reschedule_task(task.id, rearm_at)

            updated_at = getattr(task, "updated_at", None)
            if isinstance(updated_at, datetime) and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            log.warning(
                "Reaped task stuck in EXECUTING; reset to SCHEDULED",
                task_id=task.id,
                scheduler_class=self.__class__.__name__,
                stuck_seconds=int((now - updated_at).total_seconds()) if updated_at else -1,
                next_run=rearm_at,
            )
            reaped += 1

        return reaped

    @staticmethod
    def _should_continue_recurring(
        task: BaseScheduledTask, occurrence_count: int, next_run: datetime
    ) -> bool:
        """Decide whether a recurring task has more occurrences to schedule."""
        if task.max_occurrences and occurrence_count >= task.max_occurrences:
            log.info(
                "Task reached max occurrences", id=task.id, max_occurrences=task.max_occurrences
            )
            return False

        if task.stop_after:
            stop_after = task.stop_after
            if stop_after.tzinfo is None:
                stop_after = stop_after.replace(tzinfo=UTC)
                log.warning("Task stop_after was offset-naive, assuming UTC", id=task.id)

            if next_run >= stop_after:
                log.info("Task reached stop_after date", id=task.id, stop_after=stop_after)
                return False

        return True

    async def _reschedule_recurring_task(
        self,
        task: BaseScheduledTask,
        occurrence_count: int,
        next_run: datetime,
        trigger_config: TriggerConfigLike | None,
    ) -> None:
        """Persist the next occurrence and re-enqueue the recurring task."""
        # Store scheduled_at as a native datetime so the `$lte` scan can match it.
        update_fields: dict[str, Any] = {
            "scheduled_at": next_run,
            "occurrence_count": occurrence_count,
        }
        # The hasattr stays despite the Protocol: this write decides what the next
        # scheduled run fires with, and trigger_config arrives via getattr (i.e.
        # unchecked at runtime). A task whose config genuinely has no next_run must
        # not get a phantom `trigger_config.next_run` key written into Mongo.
        if trigger_config is not None and hasattr(trigger_config, "next_run"):
            update_fields["trigger_config.next_run"] = next_run
        await self.update_task_status(task.id, ScheduledTaskStatus.SCHEDULED, update_fields)
        await self.reschedule_task(task.id, next_run)
        log.info("Rescheduled recurring task for", id=task.id, next_run=next_run)

    def _build_job_args(self, task_id: str, _scheduled_at: datetime) -> tuple[object, ...]:
        """Positional args passed to the ARQ job. Subclasses may add context.

        Heterogeneous by design — ARQ takes opaque ``*args`` and the workflow
        scheduler appends a trigger-context dict (including the armed fire time)
        after the id. The base itself needs only the id; ``_scheduled_at`` is part
        of the seam so subclasses can stamp their jobs with it.
        """
        return (task_id,)

    async def _enqueue_task(self, task_id: str, scheduled_at: datetime) -> bool:
        """Enqueue a task in ARQ."""
        log.set(scheduler_task_id=task_id, scheduler_scheduled_at=str(scheduled_at))
        if not self.arq_pool:
            log.error("ARQ pool not initialized")
            return False

        # The armed time is what the DB holds for this occurrence; the job stamp
        # must carry it even when a past-due shift below moves the actual defer.
        armed_for = scheduled_at

        tz_was_naive = scheduled_at.tzinfo is None
        if tz_was_naive:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
            armed_for = armed_for.replace(tzinfo=UTC)
            log.warning(
                "Task scheduled_at was naive; assumed UTC — this is a common source of timezone drift, check the caller",
                task_id=task_id,
            )

        now = datetime.now(UTC)
        past_due = scheduled_at <= now
        if past_due:
            log.warning(
                "Task scheduled_at is in the past, rescheduling to execute in 120 seconds",
                task_id=task_id,
                scheduled_at=scheduled_at,
            )
            scheduled_at = now + timedelta(seconds=120)

        defer_seconds = int((scheduled_at - now).total_seconds())
        log.set(
            scheduled_at_utc=scheduled_at.isoformat(),
            defer_seconds=defer_seconds,
            scheduled_at_was_naive=tz_was_naive,
            scheduled_at_past_due=past_due,
        )

        job_name = self.get_job_name()
        # Deterministic job id: ARQ dedupes a task+occurrence so concurrent scans or
        # repeated enqueues can't stack duplicate jobs for the same occurrence. Keyed
        # on the ARMED time, not the deferred one: a past-due fire shifted 120 s out
        # must not collide with the genuine next occurrence that lands on that same
        # minute, or the real one is deduped away and the shifted job, carrying the
        # stale stamp, is the only thing that fires and is rejected as stale.
        job_id = f"{job_name}:{task_id}:{occurrence_stamp(armed_for)}"
        job = await enqueue_worker_job(
            self.arq_pool,
            job_name,
            *self._build_job_args(task_id, armed_for),
            _job_id=job_id,
            _defer_until=scheduled_at,
        )

        if not job:
            log.warning(
                "Task already enqueued; skipping",
                task_id=task_id,
                scheduled_at=scheduled_at.isoformat(),
            )
            return False

        log.set(arq_job_id=job.job_id, arq_job_name=job_name)
        log.debug("Enqueued task with job ID", task_id=task_id, job_id=job.job_id)
        return True

    # The pending-scan's ``$lte`` due-semantics now live on each domain's
    # repository as ``find_pending_before`` (identical filter, so the reminder and
    # workflow scans can't diverge on the operator again — they once did, reminders
    # used ``$gte`` and dropped every overdue task). This base no longer touches a
    # collection handle; ``get_pending_task`` is the seam each subclass fills.

    # Abstract methods that subclasses must implement

    @abstractmethod
    async def get_task(self, task_id: str, user_id: str | None = None) -> BaseScheduledTask | None:
        """Get a task by ID, or None if not found."""

    @abstractmethod
    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """Execute the actual task logic."""

    @abstractmethod
    async def claim_task_for_execution(
        self, task_id: str, expected_occurrence: datetime | None = None
    ) -> bool:
        """Atomically move a scheduled task to EXECUTING; False if already claimed.

        Must be a single conditional write predicated on the current status —
        anything that reads the status and then writes it lets two workers both
        pass the check and run the task twice.

        ``expected_occurrence`` is the fire time the job was armed for. Status
        alone is not sufficient for a recurring task: re-arming returns it to
        SCHEDULED for the NEXT occurrence, at which point a sibling pod's stale
        job would find it claimable again and run it early. Jobs enqueued before
        the stamp existed pass ``None`` and claim on status alone.
        """

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Update task status and any additional fields."""

    @abstractmethod
    async def find_stale_executing(self, cutoff: datetime) -> list[BaseScheduledTask]:
        """Tasks left in EXECUTING since before ``cutoff`` — the reaper's candidates."""

    @abstractmethod
    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        """Get all tasks that are due to be scheduled at current_time."""

    @abstractmethod
    def get_job_name(self) -> str:
        """Get the ARQ job name for this scheduler."""
