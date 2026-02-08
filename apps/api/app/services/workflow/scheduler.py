"""
Workflow scheduler extending BaseSchedulerService for robust scheduling.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.models.workflow_models import Workflow
from app.services.scheduler_service import BaseSchedulerService
from arq.connections import RedisSettings


class WorkflowScheduler(BaseSchedulerService):
    """
    Workflow scheduler using BaseSchedulerService foundation.

    Inherits all robust scheduling capabilities:
    - Recurring task logic with occurrence counting
    - Status management (SCHEDULED → EXECUTING → COMPLETED)
    - ARQ integration for reliable job queuing
    - Cron expression handling
    - stop_after and max_occurrences support
    """

    def __init__(self, redis_settings: Optional[RedisSettings] = None):
        """Initialize the workflow scheduler."""
        super().__init__(redis_settings)

    def get_job_name(self) -> str:
        """Get the ARQ job name for workflow processing."""
        return "execute_workflow_by_id"

    async def get_task(
        self, task_id: str, user_id: Optional[str] = None
    ) -> Optional[Workflow]:
        """
        Get a workflow by ID.

        Args:
            task_id: Workflow ID
            user_id: Optional user ID for additional validation

        Returns:
            Workflow object or None if not found
        """
        try:
            query = {"_id": task_id}
            if user_id:
                query["user_id"] = user_id

            workflow_doc = await workflows_collection.find_one(query)
            if not workflow_doc:
                logger.warning(f"Workflow {task_id} not found")
                return None

            # Transform MongoDB document to Workflow object
            workflow_doc["id"] = workflow_doc.get("_id")
            if "_id" in workflow_doc:
                del workflow_doc["_id"]

            return Workflow(**workflow_doc)
        except Exception as e:
            logger.error(f"Error fetching workflow {task_id}: {e}")
            return None

    async def execute_task(self, task: BaseScheduledTask) -> TaskExecutionResult:
        """
        Execute a workflow task.

        This delegates to the existing workflow worker logic
        while providing the BaseSchedulerService interface.

        Note: Workflows are executed via ARQ calling execute_workflow_by_id
        directly, which handles execution tracking. This method is currently
        not used for workflows but kept for BaseSchedulerService compatibility.

        Args:
            task: Workflow to execute (extending BaseScheduledTask)

        Returns:
            Task execution result
        """
        try:
            workflow: Optional[Workflow] = task if isinstance(task, Workflow) else None
            if not workflow:
                raise ValueError("Task must be a Workflow instance")

            from app.workers.tasks import execute_workflow_as_chat

            logger.info(f"Executing workflow {workflow.id}")

            if not workflow.id:
                raise ValueError("Workflow ID is required for execution")

            execution_messages = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, {}
            )

            from app.workers.tasks.workflow_tasks import (
                create_workflow_completion_notification,
            )

            await create_workflow_completion_notification(
                workflow, execution_messages, workflow.user_id
            )

            return TaskExecutionResult(
                success=True,
                message=f"Workflow executed via scheduler with {len(execution_messages)} messages",
            )
        except Exception as e:
            logger.error(f"Error executing workflow {task.id}: {e}")
            return TaskExecutionResult(
                success=False, message=f"Workflow execution failed: {str(e)}"
            )

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Update workflow status and other fields.

        Args:
            task_id: Workflow ID
            status: New status
            update_data: Additional fields to update
            user_id: User ID for authorization (optional)

        Returns:
            True if update was successful
        """
        try:
            update_fields = {
                "status": status.value,
                "updated_at": datetime.now(timezone.utc),
            }

            if update_data:
                update_fields.update(update_data)

            # Build query with optional user_id filter
            query = {"_id": task_id}
            if user_id:
                query["user_id"] = user_id

            result = await workflows_collection.update_one(
                query, {"$set": update_fields}
            )

            if result.modified_count > 0:
                logger.info(f"Updated workflow {task_id} status to {status.value}")
                return True
            else:
                logger.warning(f"No workflow updated for {task_id}")
                return False

        except Exception as e:
            logger.error(f"Error updating workflow {task_id}: {e}")
            return False

    async def get_pending_task(self, current_time: datetime) -> List[BaseScheduledTask]:
        """
        Get workflows that should be scheduled for execution.

        Args:
            current_time: Current time to check against

        Returns:
            List of workflows ready for execution (as BaseScheduledTask)
        """
        try:
            # Find workflows that are:
            # 1. In SCHEDULED status
            # 2. Have scheduled_at <= current_time
            # 3. Are activated
            query = {
                "status": ScheduledTaskStatus.SCHEDULED.value,
                "scheduled_at": {"$lte": current_time},
                "activated": True,
            }

            cursor = workflows_collection.find(query)
            workflows: List[BaseScheduledTask] = []

            async for workflow_doc in cursor:
                try:
                    # Transform MongoDB document to Workflow object
                    workflow_doc["id"] = workflow_doc.get("_id")
                    if "_id" in workflow_doc:
                        del workflow_doc["_id"]

                    workflow = Workflow(**workflow_doc)
                    workflows.append(workflow)  # Workflow extends BaseScheduledTask
                except Exception as e:
                    logger.error(f"Error creating workflow object: {e}")
                    continue

            logger.info(f"Found {len(workflows)} pending workflows")
            return workflows

        except Exception as e:
            logger.error(f"Error fetching pending workflows: {e}")
            return []

    async def create_workflow_with_scheduling(
        self, workflow_data: Dict[str, Any], user_id: str
    ) -> Optional[str]:
        """
        Create a workflow and handle its initial scheduling.

        Args:
            workflow_data: Workflow data dictionary
            user_id: User ID

        Returns:
            Workflow ID if successful, None otherwise
        """
        try:
            # Create the workflow
            workflow = Workflow(user_id=user_id, **workflow_data)

            # Insert into database
            workflow_dict = workflow.model_dump(mode="json")
            workflow_dict["_id"] = workflow_dict["id"]

            result = await workflows_collection.insert_one(workflow_dict)
            if not result.inserted_id:
                raise ValueError("Failed to create workflow in database")

            # Schedule if it's a scheduled workflow
            if workflow.trigger_config.type == "schedule" and workflow.repeat:
                from app.models.scheduler_models import ScheduleConfig

                # Ensure workflow.id is not None
                if not workflow.id:
                    raise ValueError("Workflow ID is required for scheduling")

                schedule_config = ScheduleConfig(
                    repeat=workflow.repeat,
                    scheduled_at=workflow.scheduled_at,
                    max_occurrences=workflow.max_occurrences,
                    stop_after=workflow.stop_after,
                    base_time=datetime.now(timezone.utc),  # Add required base_time
                )

                await self.schedule_task(workflow.id, schedule_config)
                logger.info(f"Scheduled workflow {workflow.id} for recurring execution")

            return workflow.id

        except Exception as e:
            logger.error(f"Error creating and scheduling workflow: {e}")
            return None

    async def schedule_workflow_execution(
        self,
        workflow_id: str,
        user_id: str,
        scheduled_at: datetime,
        repeat: Optional[str] = None,
        max_occurrences: Optional[int] = None,
        stop_after: Optional[datetime] = None,
    ) -> bool:
        """
        Schedule workflow execution using BaseSchedulerService.

        Args:
            workflow_id: Workflow ID to schedule
            user_id: User ID (for validation)
            scheduled_at: When to execute
            repeat: Cron expression for recurring workflows
            max_occurrences: Limit number of executions
            stop_after: Stop executing after this date

        Returns:
            True if scheduled successfully
        """
        try:
            # Create schedule configuration
            schedule_config = ScheduleConfig(
                scheduled_at=scheduled_at,
                repeat=repeat,
                max_occurrences=max_occurrences,
                stop_after=stop_after,
                base_time=scheduled_at,  # Use scheduled_at as base for timezone calculations
            )

            # Use the robust BaseSchedulerService scheduling
            success = await self.schedule_task(workflow_id, schedule_config)

            if success:
                logger.info(
                    f"Scheduled workflow {workflow_id} for execution at {scheduled_at}"
                    + (f" with repeat '{repeat}'" if repeat else "")
                )
            else:
                logger.error(f"Failed to schedule workflow {workflow_id}")

            return success

        except Exception as e:
            logger.error(f"Error scheduling workflow {workflow_id}: {str(e)}")
            return False

    async def cancel_scheduled_workflow_execution(self, workflow_id: str) -> bool:
        """
        Cancel scheduled workflow execution.

        Args:
            workflow_id: Workflow ID to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            # Update workflow status to cancelled in database
            db_success = await self.update_task_status(
                workflow_id, ScheduledTaskStatus.CANCELLED
            )

            # Cancel ARQ job
            arq_success = await self.cancel_task(workflow_id, "")

            if db_success and arq_success:
                logger.info(f"Cancelled scheduled execution for workflow {workflow_id}")
            elif db_success:
                logger.warning(
                    f"Cancelled workflow {workflow_id} in DB but ARQ cancellation failed"
                )
            else:
                logger.warning(
                    f"Could not cancel workflow {workflow_id} - may not exist or already executed"
                )

            return db_success

        except Exception as e:
            logger.error(f"Error cancelling workflow {workflow_id}: {str(e)}")
            return False

    async def reschedule_workflow(
        self, workflow_id: str, new_scheduled_at: datetime, repeat: Optional[str] = None
    ) -> bool:
        """
        Reschedule an existing workflow.

        Args:
            workflow_id: Workflow ID to reschedule
            new_scheduled_at: New execution time
            repeat: New cron expression (optional)

        Returns:
            True if rescheduled successfully
        """
        try:
            # Update the workflow's scheduling fields in database
            update_data = {
                "scheduled_at": new_scheduled_at,
                "status": ScheduledTaskStatus.SCHEDULED.value,
            }

            if repeat is not None:
                update_data["repeat"] = repeat

            # Update database status
            db_success = await self.update_task_status(
                workflow_id, ScheduledTaskStatus.SCHEDULED, update_data
            )

            if not db_success:
                logger.error(f"Failed to update workflow {workflow_id} in database")
                return False

            # Actually reschedule in ARQ queue
            arq_success = await self.reschedule_task(workflow_id, new_scheduled_at)

            if arq_success:
                logger.info(
                    f"Rescheduled workflow {workflow_id} for {new_scheduled_at}"
                )
            else:
                logger.error(
                    f"Failed to reschedule workflow {workflow_id} in ARQ queue"
                )

            return arq_success

        except Exception as e:
            logger.error(f"Error rescheduling workflow {workflow_id}: {str(e)}")
            return False

    async def get_workflow_status(self, workflow_id: str) -> Optional[str]:
        """
        Get the current status of a workflow.

        Args:
            workflow_id: Workflow ID

        Returns:
            Status string or None if not found
        """
        try:
            workflow = await self.get_task(workflow_id)
            return workflow.status.value if workflow else None
        except Exception as e:
            logger.error(f"Error getting workflow status for {workflow_id}: {str(e)}")
            return None


# Global instance for backward compatibility
workflow_scheduler = WorkflowScheduler()
