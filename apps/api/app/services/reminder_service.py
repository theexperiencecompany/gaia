"""
Reminder scheduler for managing reminder tasks.
"""

from datetime import UTC, datetime
from typing import Any

from arq.connections import RedisSettings
from bson import ObjectId

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
from shared.py.wide_events import log


class ReminderScheduler(BaseSchedulerService):
    """
    Manages reminder scheduling and execution.
    Inherits from BaseSchedulerService for common scheduling functionality.
    """

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
                raise ValueError("scheduled_at must be provided or repeat must be specified")

        reminder_dict = reminder_data.model_dump()
        reminder_dict["scheduled_at"] = schedule_config.scheduled_at
        reminder = ReminderModel(**reminder_dict, user_id=user_id)

        # Insert into MongoDB
        result = await reminders_collection.insert_one(document=self._serialize_reminder(reminder))
        reminder_id = str(result.inserted_id)

        # Schedule the task using base scheduler
        await self.schedule_task(reminder_id, schedule_config)

        log.info(f"Created and scheduled reminder {reminder_id} for {reminder.scheduled_at}")
        return reminder_id

    async def update_reminder(self, reminder_id: str, update_data: dict, user_id: str) -> bool:
        """Update an existing reminder, rescheduling if scheduled_at changed."""
        log.set(reminder_id=reminder_id, reminder_user_id=user_id)
        # Native datetime (BSON date), consistent with create/status-update writes.
        update_data["updated_at"] = datetime.now(UTC)

        filters: dict = {"_id": ObjectId(reminder_id)}
        if user_id:
            filters["user_id"] = user_id

        result = await reminders_collection.update_one(filters, {"$set": update_data})

        if result.modified_count > 0:
            log.info(f"Updated reminder {reminder_id}")

            # If scheduled_at was updated, reschedule the task
            if "scheduled_at" in update_data and "status" in update_data:
                if update_data["status"] == ReminderStatus.SCHEDULED:
                    scheduled_at = update_data["scheduled_at"]
                    if isinstance(scheduled_at, str):
                        scheduled_at = datetime.fromisoformat(scheduled_at)
                    await self.reschedule_task(reminder_id, new_scheduled_at=scheduled_at)

            return True

        return False

    async def list_user_reminders(
        self,
        user_id: str,
        status: ReminderStatus | None = None,
        limit: int = 100,
        skip: int = 0,
    ) -> list[ReminderModel]:
        """List reminders for a user, optionally filtered by status."""
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

    async def get_reminder(self, task_id: str, user_id: str | None = None) -> ReminderModel | None:
        """Get a reminder by ID."""
        task = await self.get_task(task_id, user_id)
        return task if isinstance(task, ReminderModel) else None

    # Implementation of abstract methods from BaseSchedulerService

    async def get_task(self, task_id: str, user_id: str | None = None) -> BaseScheduledTask | None:
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
                return TaskExecutionResult(success=False, message="Task is not a ReminderModel")

            await execute_reminder_by_agent(task)

            return TaskExecutionResult(
                success=True, message=f"Successfully executed reminder {task.id}"
            )
        except Exception as e:
            return TaskExecutionResult(success=False, message=f"Failed to execute reminder: {e!s}")

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> bool:
        """Update reminder status."""
        update_fields: dict[str, Any] = {"status": status}
        if update_data:
            update_fields.update(update_data)

        if "updated_at" not in update_fields:
            update_fields["updated_at"] = datetime.now(UTC)

        filters: dict = {"_id": ObjectId(task_id)}
        if user_id:
            filters["user_id"] = user_id

        result = await reminders_collection.update_one(filters, {"$set": update_fields})

        return result.modified_count > 0

    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        """Reminders that are scheduled and due (scheduled_at <= now).

        Delegates the due-query to the shared base implementation so the
        recovery scan can't diverge from the workflow scan (it previously used
        ``$gte`` and silently dropped overdue reminders).
        """
        return await self._query_pending_tasks(
            reminders_collection, current_time, self._doc_to_reminder
        )

    @staticmethod
    def _doc_to_reminder(doc: dict) -> ReminderModel:
        """Transform a MongoDB document into a ReminderModel (ObjectId ``_id`` -> str)."""
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        return ReminderModel(**doc)

    def _serialize_reminder(self, reminder: ReminderModel) -> dict:
        """Serialize a ReminderModel to a dict for MongoDB storage."""
        reminder_dict = reminder.model_dump(by_alias=True)
        if reminder_dict.get("_id") is None:
            # Ensure to remove _id if it was not set
            reminder_dict.pop("_id", None)

        return reminder_dict


reminder_scheduler = ReminderScheduler()
