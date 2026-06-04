"""
Workflow scheduler extending BaseSchedulerService for robust scheduling.
"""

from datetime import UTC, datetime
from typing import Any

from arq.connections import RedisSettings

from app.db.mongodb.collections import workflows_collection
from app.models.scheduler_models import (
    BaseScheduledTask,
    ScheduleConfig,
    ScheduledTaskStatus,
    TaskExecutionResult,
)
from app.models.workflow_models import TriggerType, Workflow
from app.services.scheduler_service import BaseSchedulerService
from shared.py.wide_events import log


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

    def __init__(self, redis_settings: RedisSettings | None = None):
        """Initialize the workflow scheduler."""
        super().__init__(redis_settings)

    def get_job_name(self) -> str:
        """Get the ARQ job name for workflow processing."""
        return "execute_workflow_by_id"

    def _build_job_args(self, task_id: str) -> tuple:
        """Mark scheduler-originated fires so the executor re-arms the next
        occurrence; manual "run now" executions pass their own context and so are
        never tagged as scheduled."""
        return (task_id, {"trigger_type": TriggerType.SCHEDULE.value})

    async def claim_scheduled_for_execution(self, workflow_id: str) -> bool:
        """Atomically claim a live, idle workflow for a fire (SCHEDULED -> EXECUTING).

        The claim verifies BOTH axes at once: liveness (`activated=True`) and
        run-state (`status="scheduled"`). Returns False — and the caller skips the
        fire — when either fails:
        - a concurrent recovery scan already claimed it (status != scheduled), or
        - the workflow has been deactivated (`activated=False`) but a deferred ARQ
          job for an earlier-armed occurrence is still in Redis and fires anyway.

        Keeping liveness (`activated`) and run-state (`status`) as independent fields
        is deliberate: deactivate/reactivate only flips `activated`, so a reactivated
        workflow is still status="scheduled" and immediately claimable — no stale
        status can wedge it. The re-arm at the end of execution returns the row to
        "scheduled" with its next run time.
        """
        result = await workflows_collection.find_one_and_update(
            {
                "_id": workflow_id,
                "activated": True,
                "status": ScheduledTaskStatus.SCHEDULED.value,
            },
            {
                "$set": {
                    "status": ScheduledTaskStatus.EXECUTING.value,
                    "updated_at": datetime.now(UTC),
                }
            },
        )
        return result is not None

    async def get_task(self, task_id: str, user_id: str | None = None) -> Workflow | None:
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
                log.warning(f"Workflow {task_id} not found")
                return None

            # Transform MongoDB document to Workflow object
            workflow_doc["id"] = workflow_doc.get("_id")
            if "_id" in workflow_doc:
                del workflow_doc["_id"]

            return Workflow(**workflow_doc)
        except Exception as e:
            log.error(f"Error fetching workflow {task_id}: {e}")
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
            workflow: Workflow | None = task if isinstance(task, Workflow) else None
            if not workflow:
                raise ValueError("Task must be a Workflow instance")

            from app.workers.tasks import execute_workflow_as_chat

            log.set(workflow={"id": workflow.id, "status": "executing"})
            log.info(f"Executing workflow {workflow.id}")

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
            log.error(f"Error executing workflow {task.id}: {e}")
            return TaskExecutionResult(success=False, message=f"Workflow execution failed: {e!s}")

    async def update_task_status(
        self,
        task_id: str,
        status: ScheduledTaskStatus,
        update_data: dict[str, Any] | None = None,
        user_id: str | None = None,
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
                "updated_at": datetime.now(UTC),
            }

            if update_data:
                update_fields.update(update_data)

            # Build query with optional user_id filter
            query = {"_id": task_id}
            if user_id:
                query["user_id"] = user_id

            result = await workflows_collection.update_one(query, {"$set": update_fields})

            if result.modified_count > 0:
                log.set(workflow={"id": task_id, "status": status.value})
                log.info(f"Updated workflow {task_id} status to {status.value}")
                return True
            log.warning(f"No workflow updated for {task_id}")
            return False

        except Exception as e:
            log.error(f"Error updating workflow {task_id}: {e}")
            return False

    async def get_pending_task(self, current_time: datetime) -> list[BaseScheduledTask]:
        """Recurring (cron) workflows that are due and activated.

        The ``repeat`` filter is load-bearing: ``Workflow`` extends
        ``BaseScheduledTask``, so EVERY workflow defaults to status="scheduled" and
        gets ``scheduled_at = now`` at creation when it has no ``next_run`` (manual,
        integration and todo workflows all do). Without ``repeat``, the recovery scan
        would match those non-scheduled workflows and re-run the agent on every pass.
        ``repeat`` (the cron the scheduler actually re-arms on) is the precise,
        serialization-robust discriminator for "scheduler-managed".
        """
        return await self._query_pending_tasks(
            workflows_collection,
            current_time,
            self._doc_to_workflow,
            extra_filter={"activated": True, "repeat": {"$nin": [None, ""]}},
        )

    @staticmethod
    def _doc_to_workflow(doc: dict[str, Any]) -> Workflow:
        """Transform a MongoDB document into a Workflow (string ``_id`` -> ``id``)."""
        doc["id"] = doc.get("_id")
        doc.pop("_id", None)
        return Workflow(**doc)

    async def schedule_workflow_execution(
        self,
        workflow_id: str,
        user_id: str,
        scheduled_at: datetime,
        repeat: str | None = None,
        max_occurrences: int | None = None,
        stop_after: datetime | None = None,
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
                log.info(
                    f"Scheduled workflow {workflow_id} for execution at {scheduled_at}"
                    + (f" with repeat '{repeat}'" if repeat else "")
                )
            else:
                log.error(f"Failed to schedule workflow {workflow_id}")

            return success

        except Exception as e:
            log.error(f"Error scheduling workflow {workflow_id}: {e!s}")
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
            db_success = await self.update_task_status(workflow_id, ScheduledTaskStatus.CANCELLED)

            # Cancel ARQ job
            arq_success = await self.cancel_task(workflow_id, "")

            if db_success and arq_success:
                log.info(f"Cancelled scheduled execution for workflow {workflow_id}")
            elif db_success:
                log.warning(f"Cancelled workflow {workflow_id} in DB but ARQ cancellation failed")
            else:
                log.warning(
                    f"Could not cancel workflow {workflow_id} - may not exist or already executed"
                )

            return db_success

        except Exception as e:
            log.error(f"Error cancelling workflow {workflow_id}: {e!s}")
            return False

    async def reschedule_workflow(
        self, workflow_id: str, new_scheduled_at: datetime, repeat: str | None = None
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
                log.error(f"Failed to update workflow {workflow_id} in database")
                return False

            # Actually reschedule in ARQ queue
            arq_success = await self.reschedule_task(workflow_id, new_scheduled_at)

            if arq_success:
                log.info(f"Rescheduled workflow {workflow_id} for {new_scheduled_at}")
            else:
                log.error(f"Failed to reschedule workflow {workflow_id} in ARQ queue")

            return arq_success

        except Exception as e:
            log.error(f"Error rescheduling workflow {workflow_id}: {e!s}")
            return False

    async def get_workflow_status(self, workflow_id: str) -> str | None:
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
            log.error(f"Error getting workflow status for {workflow_id}: {e!s}")
            return None


# Global instance for backward compatibility
workflow_scheduler = WorkflowScheduler()
