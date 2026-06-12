"""
Base scheduler service for managing scheduled tasks.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from app.config.settings import settings
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.utils.cron_utils import get_next_run_time
from shared.py.wide_events import log


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
        self.arq_pool = None

    async def initialize(self):
        """Initialize ARQ pool connection."""
        self.arq_pool = await create_pool(self.redis_settings)
        log.info(f"{self.__class__.__name__} initialized")

    async def close(self):
        """Close ARQ pool connection."""
        if self.arq_pool:
            await self.arq_pool.aclose()
        log.info(f"{self.__class__.__name__} closed")

    async def schedule_task(self, task_id: str, schedule_config: ScheduleConfig) -> bool:
        """Schedule a task using the provided configuration."""
        scheduled_at = schedule_config.scheduled_at

        # If no scheduled_at but has repeat, calculate next run time
        if not scheduled_at and schedule_config.repeat:
            scheduled_at = get_next_run_time(
                cron_expr=schedule_config.repeat, base_time=schedule_config.base_time
            )

        if not scheduled_at:
            raise ValueError("scheduled_at must be provided or repeat must be specified")

        return await self._enqueue_task(task_id, scheduled_at)

    async def reschedule_task(self, task_id: str, new_scheduled_at: datetime) -> bool:
        """Reschedule an existing task to a new time."""
        return await self._enqueue_task(task_id, new_scheduled_at)

    async def process_task_execution(self, task_id: str) -> TaskExecutionResult:
        """Process a scheduled task execution: validate, execute, then handle
        recurring logic or update final status."""
        log.set(scheduler_task_id=task_id, scheduler_class=self.__class__.__name__)
        # Get the task
        task = await self.get_task(task_id)
        if not task:
            log.error(f"Task {task_id} not found")
            return TaskExecutionResult(success=False, message=f"Task {task_id} not found")

        if task.status != ScheduledTaskStatus.SCHEDULED:
            log.warning(f"Task {task_id} is not scheduled (status: {task.status})")
            return TaskExecutionResult(
                success=False, message=f"Task {task_id} is not in scheduled status"
            )

        log.info(f"Processing task {task_id}")

        occurrence_count = task.occurrence_count + 1

        try:
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.EXECUTING,
                {"updated_at": datetime.now(UTC)},
            )
            execution_result = await self.execute_task(task)
        except Exception as e:
            log.error(f"Failed to execute task {task_id}: {e!s}")
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
            log.info(f"Completed one-time task {task_id}")
        else:
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.FAILED,
                {"occurrence_count": occurrence_count, "updated_at": datetime.now(UTC)},
            )
            log.warning(f"One-time task {task_id} failed: {execution_result.message}")

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
            log.info(f"Cancelled task {task_id}")

        return success

    async def scan_and_schedule_pending_tasks(self):
        """Scan for due scheduled tasks and enqueue them in ARQ (called at startup)."""
        now = datetime.now(UTC)
        tasks = await self.get_pending_task(now)

        scheduled_count = 0
        for task in tasks:
            if task.id and task.scheduled_at:
                await self._enqueue_task(task.id, task.scheduled_at)
                scheduled_count += 1

        log.info(f"Scheduled {scheduled_count} pending tasks")

    async def handle_recurring_task(self, task: BaseScheduledTask, occurrence_count: int):
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
            log.warning(f"Task {task.id} has no repeat schedule")
            return

        if not task.id:
            log.error("Task ID is None, cannot handle recurring task")
            return

        # Calculate next run time with user timezone context
        user_timezone = None

        # For workflows, extract timezone from trigger_config
        trigger_config = getattr(task, "trigger_config", None)
        if trigger_config and hasattr(trigger_config, "timezone"):
            user_timezone = trigger_config.timezone
            log.debug(f"Using workflow timezone: {user_timezone}")

        # Advance from now, not from a (possibly stale) scheduled_at, so a dormant
        # task resumes at its next future occurrence instead of replaying missed runs.
        next_run = get_next_run_time(task.repeat, datetime.now(UTC), user_timezone)

        if self._should_continue_recurring(task, occurrence_count, next_run):
            await self._reschedule_recurring_task(task, occurrence_count, next_run, trigger_config)
        else:
            await self.update_task_status(
                task.id,
                ScheduledTaskStatus.COMPLETED,
                {"occurrence_count": occurrence_count},
            )
            log.info(f"Completed recurring task {task.id}")

    @staticmethod
    def _should_continue_recurring(
        task: BaseScheduledTask, occurrence_count: int, next_run: datetime
    ) -> bool:
        """Decide whether a recurring task has more occurrences to schedule."""
        if task.max_occurrences and occurrence_count >= task.max_occurrences:
            log.info(f"Task {task.id} reached max occurrences ({task.max_occurrences})")
            return False

        if task.stop_after:
            stop_after = task.stop_after
            if stop_after.tzinfo is None:
                stop_after = stop_after.replace(tzinfo=UTC)
                log.warning(f"Task {task.id} stop_after was offset-naive, assuming UTC")

            if next_run >= stop_after:
                log.info(f"Task {task.id} reached stop_after date ({stop_after})")
                return False

        return True

    async def _reschedule_recurring_task(
        self,
        task: BaseScheduledTask,
        occurrence_count: int,
        next_run: datetime,
        trigger_config: Any,
    ) -> None:
        """Persist the next occurrence and re-enqueue the recurring task."""
        # Store scheduled_at as a native datetime so the `$lte` scan can match it.
        update_fields: dict[str, Any] = {
            "scheduled_at": next_run,
            "occurrence_count": occurrence_count,
        }
        if trigger_config is not None and hasattr(trigger_config, "next_run"):
            update_fields["trigger_config.next_run"] = next_run
        await self.update_task_status(task.id, ScheduledTaskStatus.SCHEDULED, update_fields)
        await self.reschedule_task(task.id, next_run)
        log.info(f"Rescheduled recurring task {task.id} for {next_run}")

    def _build_job_args(self, task_id: str) -> tuple:
        """Positional args passed to the ARQ job. Subclasses may add context."""
        return (task_id,)

    async def _enqueue_task(self, task_id: str, scheduled_at: datetime) -> bool:
        """Enqueue a task in ARQ."""
        log.set(scheduler_task_id=task_id, scheduler_scheduled_at=str(scheduled_at))
        if not self.arq_pool:
            log.error("ARQ pool not initialized")
            return False

        tz_was_naive = scheduled_at.tzinfo is None
        if tz_was_naive:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
            log.warning(
                f"Task {task_id} scheduled_at was naive; assumed UTC — this is a "
                f"common source of timezone drift, check the caller",
            )

        now = datetime.now(UTC)
        past_due = scheduled_at <= now
        if past_due:
            log.warning(
                f"Task {task_id} scheduled_at ({scheduled_at}) is in the past, "
                f"rescheduling to execute in 120 seconds"
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
        # Deterministic job id: ARQ dedupes a task+fire-time so concurrent scans or
        # repeated enqueues can't stack duplicate jobs for the same occurrence.
        job_id = f"{job_name}:{task_id}:{int(scheduled_at.timestamp())}"
        job = await self.arq_pool.enqueue_job(
            job_name, *self._build_job_args(task_id), _job_id=job_id, _defer_until=scheduled_at
        )

        if not job:
            log.warning(f"Task {task_id} already enqueued for {scheduled_at.isoformat()}; skipping")
            return False

        log.set(arq_job_id=job.job_id, arq_job_name=job_name)
        log.debug(f"Enqueued task {task_id} with job ID {job.job_id}")
        return True

    async def _query_pending_tasks(
        self,
        collection: Any,
        current_time: datetime,
        doc_to_task: Callable[[dict[str, Any]], BaseScheduledTask],
        extra_filter: dict[str, Any] | None = None,
    ) -> list[BaseScheduledTask]:
        """Shared recovery-scan query for every scheduler subclass.

        Selects tasks that are SCHEDULED and DUE (``scheduled_at <= now``). The
        ``$lte`` due-semantics live here, in one place, so the reminder and
        workflow scans can never diverge on the operator again (they once did:
        reminders used ``$gte`` and silently dropped every overdue task).

        Subclasses supply only their collection, a document->model mapper, and
        any extra filter (e.g. workflows additionally require ``activated: True``).
        """
        query: dict[str, Any] = {
            "status": ScheduledTaskStatus.SCHEDULED.value,
            "scheduled_at": {"$lte": current_time},
        }
        if extra_filter:
            query.update(extra_filter)

        tasks: list[BaseScheduledTask] = []
        try:
            cursor = collection.find(query)
            async for doc in cursor:
                try:
                    tasks.append(doc_to_task(doc))
                except Exception as e:
                    log.error(f"Error building pending task from document: {e}")
                    continue
        except Exception as e:
            log.error(f"Error fetching pending tasks: {e}")
            return []

        log.info(f"Found {len(tasks)} pending tasks")
        return tasks

    # Abstract methods that subclasses must implement

    @abstractmethod
    async def get_task(self, task_id: str, user_id: str | None = None) -> BaseScheduledTask | None:
        """Get a task by ID, or None if not found."""
        pass

    @abstractmethod
    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """Execute the actual task logic."""
        pass

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Update task status and any additional fields."""
        pass

    @abstractmethod
    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        """Get all tasks that are due to be scheduled at current_time."""
        pass

    @abstractmethod
    def get_job_name(self) -> str:
        """Get the ARQ job name for this scheduler."""
        pass
