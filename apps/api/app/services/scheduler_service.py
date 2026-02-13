"""
Base scheduler service for managing scheduled tasks.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.config.settings import settings
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.utils.cron_utils import get_next_run_time
from arq import create_pool
from arq.connections import RedisSettings


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

    def __init__(self, redis_settings: Optional[RedisSettings] = None):
        """
        Initialize the scheduler service.

        Args:
            redis_settings: Redis connection settings for ARQ
        """
        self.redis_settings = redis_settings or RedisSettings.from_dsn(
            settings.REDIS_URL
        )
        self.arq_pool = None

    async def initialize(self):
        """Initialize ARQ pool connection."""
        self.arq_pool = await create_pool(self.redis_settings)
        logger.info(f"{self.__class__.__name__} initialized")

    async def close(self):
        """Close ARQ pool connection."""
        if self.arq_pool:
            await self.arq_pool.aclose()
        logger.info(f"{self.__class__.__name__} closed")

    async def schedule_task(
        self, task_id: str, schedule_config: ScheduleConfig
    ) -> bool:
        """
        Schedule a task using the provided configuration.

        Args:
            task_id: Unique identifier for the task
            schedule_config: Scheduling configuration

        Returns:
            True if scheduled successfully
        """
        scheduled_at = schedule_config.scheduled_at

        # If no scheduled_at but has repeat, calculate next run time
        if not scheduled_at and schedule_config.repeat:
            scheduled_at = get_next_run_time(
                cron_expr=schedule_config.repeat, base_time=schedule_config.base_time
            )

        if not scheduled_at:
            raise ValueError(
                "scheduled_at must be provided or repeat must be specified"
            )

        return await self._enqueue_task(task_id, scheduled_at)

    async def reschedule_task(self, task_id: str, new_scheduled_at: datetime) -> bool:
        """
        Reschedule an existing task to a new time.

        Args:
            task_id: Task ID to reschedule
            new_scheduled_at: New scheduled time

        Returns:
            True if rescheduled successfully
        """
        return await self._enqueue_task(task_id, new_scheduled_at)

    async def process_task_execution(self, task_id: str) -> TaskExecutionResult:
        """
        Process a scheduled task execution.

        This method handles the complete task execution lifecycle:
        1. Get and validate the task
        2. Execute the task
        3. Handle recurring logic
        4. Update task status

        Args:
            task_id: Task ID to process

        Returns:
            Task execution result
        """
        # Get the task
        task = await self.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return TaskExecutionResult(
                success=False, message=f"Task {task_id} not found"
            )

        if task.status != ScheduledTaskStatus.SCHEDULED:
            logger.warning(f"Task {task_id} is not scheduled (status: {task.status})")
            return TaskExecutionResult(
                success=False, message=f"Task {task_id} is not in scheduled status"
            )

        logger.info(f"Processing task {task_id}")

        try:
            # Mark task as executing
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.EXECUTING,
                {"updated_at": datetime.now(timezone.utc)},
            )

            # Execute the task
            execution_result = await self.execute_task(task)

            # Increment occurrence count
            occurrence_count = task.occurrence_count + 1

            # Handle recurring tasks
            if task.repeat:
                await self._handle_recurring_task(task, occurrence_count)
            else:
                # One-time task - mark as completed
                await self.update_task_status(
                    task_id,
                    ScheduledTaskStatus.COMPLETED,
                    {"occurrence_count": occurrence_count},
                )
                logger.info(f"Completed one-time task {task_id}")

            return execution_result

        except Exception as e:
            logger.error(f"Failed to process task {task_id}: {str(e)}")
            await self.update_task_status(
                task_id,
                ScheduledTaskStatus.FAILED,
                {"updated_at": datetime.now(timezone.utc)},
            )
            return TaskExecutionResult(
                success=False, message=f"Task execution failed: {str(e)}"
            )

    async def cancel_task(self, task_id: str, user_id: str) -> bool:
        """
        Cancel a scheduled task.

        Note: ARQ doesn't support direct job cancellation, so this marks the task
        as cancelled in the database. The task execution will check this status
        and skip execution if cancelled.

        Args:
            task_id: Task ID to cancel
            user_id: User ID for authorization

        Returns:
            True if cancelled successfully
        """
        success = await self.update_task_status(
            task_id,
            ScheduledTaskStatus.CANCELLED,
            {"updated_at": datetime.now(timezone.utc)},
            user_id,
        )

        if success:
            logger.info(f"Cancelled task {task_id}")

        return success

    async def scan_and_schedule_pending_tasks(self):
        """
        Scan for scheduled tasks and enqueue them in ARQ.
        Called during service startup.
        """
        now = datetime.now(timezone.utc)
        tasks = await self.get_pending_task(now)

        scheduled_count = 0
        for task in tasks:
            if task.id:
                await self._enqueue_task(task.id, task.scheduled_at)
                scheduled_count += 1

        logger.info(f"Scheduled {scheduled_count} pending tasks")

    async def _handle_recurring_task(
        self, task: BaseScheduledTask, occurrence_count: int
    ):
        """
        Handle rescheduling logic for recurring tasks.

        Args:
            task: The task to handle
            occurrence_count: Current occurrence count
        """
        if not task.repeat:
            logger.warning(f"Task {task.id} has no repeat schedule")
            return

        if not task.id:
            logger.error("Task ID is None, cannot handle recurring task")
            return

        # Calculate next run time with user timezone context
        user_timezone = None

        # For workflows, extract timezone from trigger_config
        trigger_config = getattr(task, "trigger_config", None)
        if trigger_config and hasattr(trigger_config, "timezone"):
            user_timezone = trigger_config.timezone
            logger.debug(f"Using workflow timezone: {user_timezone}")

        next_run = get_next_run_time(task.repeat, task.scheduled_at, user_timezone)

        # Check if we should continue scheduling
        should_continue = True

        # Check max occurrences
        if task.max_occurrences and occurrence_count >= task.max_occurrences:
            should_continue = False
            logger.info(
                f"Task {task.id} reached max occurrences ({task.max_occurrences})"
            )

        # Check stop_after date
        if task.stop_after:
            stop_after = task.stop_after
            if stop_after.tzinfo is None:
                stop_after = stop_after.replace(tzinfo=timezone.utc)
                logger.warning(
                    f"Task {task.id} stop_after was offset-naive, assuming UTC"
                )

            if next_run >= stop_after:
                should_continue = False
                logger.info(f"Task {task.id} reached stop_after date ({stop_after})")

        if should_continue:
            # Update and reschedule
            await self.update_task_status(
                task.id,
                ScheduledTaskStatus.SCHEDULED,
                {
                    "scheduled_at": next_run.isoformat(),
                    "occurrence_count": occurrence_count,
                },
            )
            await self.reschedule_task(task.id, next_run)
            logger.info(f"Rescheduled recurring task {task.id} for {next_run}")
        else:
            # Mark as completed
            await self.update_task_status(
                task.id,
                ScheduledTaskStatus.COMPLETED,
                {"occurrence_count": occurrence_count},
            )
            logger.info(f"Completed recurring task {task.id}")

    async def _enqueue_task(self, task_id: str, scheduled_at: datetime) -> bool:
        """
        Enqueue a task in ARQ.

        Args:
            task_id: Task ID
            scheduled_at: When to execute the task

        Returns:
            True if enqueued successfully
        """
        if not self.arq_pool:
            logger.error("ARQ pool not initialized")
            return False

        # Ensure scheduled_at is timezone-aware
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

        # Check if scheduled time is in the past - if so, schedule for now + small buffer
        # This prevents Redis PSETEX errors from negative expire times
        now = datetime.now(timezone.utc)
        if scheduled_at <= now:
            logger.warning(
                f"Task {task_id} scheduled_at ({scheduled_at}) is in the past, "
                f"rescheduling to execute in 120 seconds"
            )
            scheduled_at = now + timedelta(seconds=120)

        job_name = self.get_job_name()
        job = await self.arq_pool.enqueue_job(
            job_name, task_id, _defer_until=scheduled_at
        )

        if not job:
            logger.error(f"Failed to enqueue task {task_id}")
            return False

        logger.debug(f"Enqueued task {task_id} with job ID {job.job_id}")
        return True

    # Abstract methods that subclasses must implement

    @abstractmethod
    async def get_task(
        self, task_id: str, user_id: Optional[str] = None
    ) -> Optional[BaseScheduledTask]:
        """
        Get a task by ID.

        Args:
            task_id: Task ID
            user_id: User ID for authorization (optional)

        Returns:
            Task model or None if not found
        """
        pass

    @abstractmethod
    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """
        Execute the actual task logic.

        Args:
            task: Task to execute

        Returns:
            Task execution result
        """
        pass

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Update task status and additional data.

        Args:
            task_id: Task ID to update
            status: New status
            update_data: Additional fields to update
            user_id: User ID for authorization (optional)

        Returns:
            True if updated successfully
        """
        pass

    @abstractmethod
    async def get_pending_task(self, current_time: datetime) -> List[BaseScheduledTask]:
        """
        Get all tasks that should be scheduled.

        Args:
            current_time: Current time for filtering

        Returns:
            List of tasks to schedule
        """
        pass

    @abstractmethod
    def get_job_name(self) -> str:
        """
        Get the ARQ job name for this scheduler.

        Returns:
            Job name string
        """
        pass
