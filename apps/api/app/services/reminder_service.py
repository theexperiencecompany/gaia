"""
Reminder scheduler for managing reminder tasks.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import reminders_collection
from app.models.reminder_models import (
    CreateReminderRequest,
    ReminderModel,
    ReminderStatus,
)
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.services.scheduler_service import BaseSchedulerService
from app.utils.cron_utils import get_next_run_time
from arq.connections import RedisSettings
from bson import ObjectId


class ReminderScheduler(BaseSchedulerService):
    """
    Manages reminder scheduling and execution.
    Inherits from BaseSchedulerService for common scheduling functionality.
    """

    def __init__(self, redis_settings: Optional[RedisSettings] = None):
        """
        Initialize the reminder scheduler.

        Args:
            redis_settings: Redis connection settings for ARQ
        """
        super().__init__(redis_settings)

    def get_job_name(self) -> str:
        """Get the ARQ job name for reminder processing."""
        return "process_reminder"

    async def create_reminder(
        self, reminder_data: CreateReminderRequest, user_id: str
    ) -> str:
        """
        Create a new reminder and schedule it.

        Args:
            reminder_data: Reminder data dictionary
            user_id: User Id

        Returns:
            Created reminder ID
        """
        # Create schedule config
        schedule_config = ScheduleConfig(
            repeat=reminder_data.repeat,
            scheduled_at=reminder_data.scheduled_at,
            max_occurrences=reminder_data.max_occurrences,
            stop_after=reminder_data.stop_after,
            base_time=reminder_data.base_time,
        )

        # Set scheduled_at if not provided
        if not schedule_config.scheduled_at:
            if schedule_config.repeat:
                schedule_config.scheduled_at = get_next_run_time(
                    cron_expr=schedule_config.repeat,
                    base_time=schedule_config.base_time,
                )
            else:
                raise ValueError(
                    "scheduled_at must be provided or repeat must be specified"
                )

        reminder = ReminderModel(**reminder_data.model_dump(), user_id=user_id)

        # Insert into MongoDB
        result = await reminders_collection.insert_one(
            document=self._serialize_reminder(reminder)
        )
        reminder_id = str(result.inserted_id)

        # Schedule the task using base scheduler
        await self.schedule_task(reminder_id, schedule_config)

        logger.info(
            f"Created and scheduled reminder {reminder_id} for {reminder.scheduled_at}"
        )
        return reminder_id

    async def update_reminder(
        self, reminder_id: str, update_data: dict, user_id: str
    ) -> bool:
        """
        Update an existing reminder.

        Args:
            reminder_id: Reminder ID to update
            update_data: Fields to update
            user_id: User ID for authorization

        Returns:
            True if updated successfully
        """
        # Add updated_at timestamp
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        filters: dict = {"_id": ObjectId(reminder_id)}
        if user_id:
            filters["user_id"] = user_id

        result = await reminders_collection.update_one(filters, {"$set": update_data})

        if result.modified_count > 0:
            logger.info(f"Updated reminder {reminder_id}")

            # If scheduled_at was updated, reschedule the task
            if "scheduled_at" in update_data and "status" in update_data:
                if update_data["status"] == ReminderStatus.SCHEDULED:
                    await self.reschedule_task(
                        reminder_id,
                        new_scheduled_at=datetime.fromisoformat(
                            update_data["scheduled_at"]
                        ),
                    )

            return True

        return False

    async def list_user_reminders(
        self,
        user_id: str,
        status: Optional[ReminderStatus] = None,
        limit: int = 100,
        skip: int = 0,
    ) -> List[ReminderModel]:
        """
        List reminders for a user.

        Args:
            user_id: User ID
            status: Filter by status (optional)
            limit: Maximum number of results
            skip: Number of results to skip

        Returns:
            List of reminder models
        """
        query = {"user_id": user_id}
        if status:
            query["status"] = status

        cursor = reminders_collection.find(query).skip(skip).limit(limit)
        docs = await cursor.to_list(length=limit)

        results = []

        # Convert ObjectId to string and create ReminderModel instances
        for doc in docs:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            results.append(ReminderModel(**doc))

        return results

    async def get_reminder(
        self, task_id: str, user_id: Optional[str] = None
    ) -> Optional[ReminderModel]:
        """Get a reminder by ID."""
        task = await self.get_task(task_id, user_id)
        return task if isinstance(task, ReminderModel) else None

    # Implementation of abstract methods from BaseSchedulerService

    async def get_task(
        self, task_id: str, user_id: Optional[str] = None
    ) -> Optional[BaseScheduledTask]:
        """Get a reminder by ID."""
        filters: dict = {"_id": ObjectId(task_id)}
        if user_id:
            filters["user_id"] = user_id

        doc = await reminders_collection.find_one(filters)
        if doc:
            doc["_id"] = str(doc["_id"])  # Convert ObjectId to string
            return ReminderModel(**doc)
        return None

    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """Execute a reminder task."""
        try:
            # Import here to avoid circular imports
            from app.tasks.reminder_tasks import execute_reminder_by_agent

            # Ensure task is a ReminderModel
            if not isinstance(task, ReminderModel):
                return TaskExecutionResult(
                    success=False, message="Task is not a ReminderModel"
                )

            await execute_reminder_by_agent(task)

            return TaskExecutionResult(
                success=True, message=f"Successfully executed reminder {task.id}"
            )
        except Exception as e:
            return TaskExecutionResult(
                success=False, message=f"Failed to execute reminder: {str(e)}"
            )

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Update reminder status."""
        update_fields: Dict[str, Any] = {"status": status}
        if update_data:
            update_fields.update(update_data)

        if "updated_at" not in update_fields:
            update_fields["updated_at"] = datetime.now(timezone.utc)

        filters: dict = {"_id": ObjectId(task_id)}
        if user_id:
            filters["user_id"] = user_id

        result = await reminders_collection.update_one(filters, {"$set": update_fields})

        return result.modified_count > 0

    async def get_pending_task(self, current_time: datetime) -> List[BaseScheduledTask]:
        """Get all scheduled reminders that should be enqueued."""
        cursor = reminders_collection.find(
            {"status": ReminderStatus.SCHEDULED, "scheduled_at": {"$gte": current_time}}
        )

        tasks = []
        async for doc in cursor:
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            tasks.append(ReminderModel(**doc))

        return tasks

    def _serialize_reminder(self, reminder: ReminderModel) -> dict:
        """
        Serialize a ReminderModel to a dictionary for MongoDB storage.

        Args:
            reminder: ReminderModel instance

        Returns:
            Dictionary representation of the reminder
        """
        reminder_dict = reminder.model_dump(by_alias=True)
        if reminder_dict.get("_id") is None:
            # Ensure to remove _id if it was not set
            reminder_dict.pop("_id", None)

        return reminder_dict


reminder_scheduler = ReminderScheduler()
