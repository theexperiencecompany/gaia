"""
Clean workflow service for GAIA workflow system.
Handles CRUD operations and execution coordination.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflows_collection
from app.models.workflow_models import (
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
)
from .generation_service import WorkflowGenerationService
from .queue_service import WorkflowQueueService
from .scheduler import workflow_scheduler
from app.utils.workflow_utils import (
    ensure_trigger_config_object,
    handle_workflow_error,
    transform_workflow_document,
)
from .validators import WorkflowValidator


class WorkflowService:
    """Service class for workflow operations."""

    @staticmethod
    async def create_workflow(
        request: CreateWorkflowRequest,
        user_id: str,
        user_timezone: Optional[str] = None,
    ) -> Workflow:
        """Create a new workflow with automatic timezone population."""
        try:
            # Use provided timezone (from dependency) - should already be resolved by dependency
            timezone_to_use = user_timezone or "UTC"

            logger.info(f"Creating workflow with timezone: {timezone_to_use}")

            # Calculate next_run for scheduled workflows with timezone awareness
            trigger_config = request.trigger_config

            # Automatically populate timezone field
            if trigger_config.type == "schedule":
                trigger_config.timezone = timezone_to_use
                if trigger_config.cron_expression:
                    trigger_config.update_next_run(user_timezone=timezone_to_use)

            # Create workflow object
            workflow = Workflow(
                title=request.title,
                description=request.description,
                steps=[],  # Steps will be generated
                trigger_config=trigger_config,
                activated=True,  # Default to activated
                user_id=user_id,
            )

            # Insert into database
            workflow_dict = workflow.model_dump(mode="json")
            workflow_dict["_id"] = workflow_dict["id"]

            result = await workflows_collection.insert_one(workflow_dict)
            if not result.inserted_id:
                raise ValueError("Failed to create workflow in database")

            logger.info(f"Created workflow {workflow.id} for user {user_id}")

            if not workflow.id:
                raise ValueError("Workflow ID is required")

            # Schedule the workflow if it's a scheduled type and enabled
            if (
                trigger_config.type == "schedule"
                and trigger_config.enabled
                and trigger_config.next_run
            ):
                await workflow_scheduler.schedule_workflow_execution(
                    workflow.id,
                    user_id,
                    trigger_config.next_run,
                    repeat=trigger_config.cron_expression,  # Enable recurring if cron exists
                )

            # Generate steps
            if request.generate_immediately:
                await WorkflowService._generate_workflow_steps(workflow.id, user_id)
                # Fetch the updated workflow with generated steps
                updated_workflow = await WorkflowService.get_workflow(
                    workflow.id, user_id
                )
                return updated_workflow or workflow
            else:
                success = await WorkflowQueueService.queue_workflow_generation(
                    workflow.id, user_id
                )
                if not success:
                    logger.error(
                        f"Failed to queue workflow generation for {workflow.id}"
                    )

            return workflow

        except Exception as e:
            logger.error(f"Error creating workflow: {str(e)}")
            raise

    @staticmethod
    async def get_workflow(workflow_id: str, user_id: str) -> Optional[Workflow]:
        """Get a workflow by ID."""
        try:
            workflow_doc = await workflows_collection.find_one(
                {"_id": workflow_id, "user_id": user_id}
            )

            if not workflow_doc:
                return None

            # Transform document with trigger_config handling
            transformed_doc = transform_workflow_document(workflow_doc)
            return Workflow(**transformed_doc)

        except Exception as e:
            logger.error(f"Error getting workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def list_workflows(user_id: str) -> List[Workflow]:
        """List all workflows for a user."""
        try:
            # Use to_list() for better performance
            docs = (
                await workflows_collection.find({"user_id": user_id})
                .sort("created_at", -1)
                .to_list(length=None)
            )

            workflows = []
            for doc in docs:
                try:
                    transformed_doc = transform_workflow_document(doc)
                    workflows.append(Workflow(**transformed_doc))
                except Exception as e:
                    logger.warning(
                        f"Skipping malformed workflow document {doc.get('_id')}: {e}"
                    )
                    continue

            logger.debug(f"Retrieved {len(workflows)} workflows for user {user_id}")
            return workflows

        except Exception as e:
            logger.error(f"Error listing workflows for user {user_id}: {str(e)}")
            raise

    @staticmethod
    async def update_workflow(
        workflow_id: str,
        request: UpdateWorkflowRequest,
        user_id: str,
        user_timezone: Optional[str] = None,
    ) -> Optional[Workflow]:
        """Update an existing workflow with timezone awareness."""
        try:
            # Get current workflow to check for trigger changes
            current_workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not current_workflow:
                return None

            update_data = {"updated_at": datetime.now(timezone.utc)}
            update_fields = request.model_dump(exclude_unset=True)

            # Handle trigger config changes
            if "trigger_config" in update_fields:
                new_trigger_config = ensure_trigger_config_object(
                    update_fields["trigger_config"]
                )

                # Use provided timezone or fallback to UTC
                timezone_to_use = user_timezone or "UTC"

                logger.info(
                    f"Updating workflow {workflow_id} with timezone: {timezone_to_use}"
                )

                # Automatically populate timezone field if it's a scheduled workflow
                if new_trigger_config.type == "schedule":
                    new_trigger_config.timezone = timezone_to_use

                # Calculate next_run for scheduled workflows with timezone awareness
                if (
                    new_trigger_config.type == "schedule"
                    and new_trigger_config.cron_expression
                ):
                    new_trigger_config.update_next_run(user_timezone=timezone_to_use)

                # Check if we need to reschedule
                old_config = current_workflow.trigger_config
                schedule_changed = (
                    old_config.type != new_trigger_config.type
                    or old_config.cron_expression != new_trigger_config.cron_expression
                    or old_config.enabled != new_trigger_config.enabled
                )

                if schedule_changed:
                    # Use reschedule logic instead of cancel + schedule for efficiency
                    if (
                        new_trigger_config.type == "schedule"
                        and new_trigger_config.enabled
                        and new_trigger_config.next_run
                        and current_workflow.activated
                    ):
                        # Reschedule to new time with new cron expression
                        await workflow_scheduler.reschedule_workflow(
                            workflow_id,
                            new_trigger_config.next_run,
                            repeat=new_trigger_config.cron_expression,
                        )
                    else:
                        # Cancel if workflow is being disabled or conditions not met
                        await workflow_scheduler.cancel_scheduled_workflow_execution(
                            workflow_id
                        )

                # Convert TriggerConfig back to dict for MongoDB storage
                update_fields["trigger_config"] = new_trigger_config.model_dump(
                    mode="json"
                )

            update_data.update(update_fields)

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, {"$set": update_data}
            )

            if result.matched_count == 0:
                return None

            logger.info(f"Updated workflow {workflow_id} for user {user_id}")
            return await WorkflowService.get_workflow(workflow_id, user_id)

        except Exception as e:
            logger.error(f"Error updating workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def delete_workflow(workflow_id: str, user_id: str) -> bool:
        """Delete a workflow."""
        try:
            # Cancel any scheduled executions before deleting
            await workflow_scheduler.cancel_scheduled_workflow_execution(workflow_id)

            # Additional cleanup
            try:
                await workflow_scheduler.cancel_task(workflow_id, user_id)
            except Exception as e:
                logger.warning(
                    f"Additional cleanup failed for workflow {workflow_id}: {e}"
                )

            result = await workflows_collection.delete_one(
                {"_id": workflow_id, "user_id": user_id}
            )

            if result.deleted_count == 0:
                return False

            logger.info(f"Deleted workflow {workflow_id} for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error deleting workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def execute_workflow(
        workflow_id: str, request: WorkflowExecutionRequest, user_id: str
    ) -> WorkflowExecutionResponse:
        """Execute a workflow."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            # Use simple validator for execution check
            WorkflowValidator.validate_for_execution(workflow)

            # Update last execution timestamp
            result = await workflows_collection.find_one_and_update(
                {"_id": workflow_id, "user_id": user_id},
                {"$set": {"updated_at": datetime.now(timezone.utc)}},
            )

            if not result:
                raise ValueError(f"Failed to update workflow {workflow_id}")

            execution_id = f"exec_{workflow_id}_{uuid.uuid4().hex[:8]}"

            success = await WorkflowQueueService.queue_workflow_execution(
                workflow_id, user_id, request.context
            )
            if not success:
                raise ValueError(
                    f"Failed to queue workflow execution for {workflow_id}"
                )

            logger.info(f"Started execution {execution_id} for workflow {workflow_id}")

            return WorkflowExecutionResponse(
                execution_id=execution_id,
                message="Workflow execution started",
            )

        except Exception as e:
            logger.error(f"Error executing workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def get_workflow_status(
        workflow_id: str, user_id: str
    ) -> WorkflowStatusResponse:
        """Get the current status of a workflow."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")

            total_steps = len(workflow.steps)
            progress_percentage = 0.0

            if total_steps > 0:
                progress_percentage = 0

            return WorkflowStatusResponse(
                workflow_id=workflow_id,
                activated=workflow.activated,
                current_step_index=workflow.current_step_index,
                total_steps=total_steps,
                progress_percentage=progress_percentage,
                last_updated=workflow.updated_at,
                error_message=workflow.error_message,
                logs=workflow.execution_logs,
            )

        except Exception as e:
            logger.error(f"Error getting workflow status {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def activate_workflow(
        workflow_id: str, user_id: str, user_timezone: Optional[str] = None
    ) -> Optional[Workflow]:
        """Activate a workflow (enable its trigger)."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # Update trigger to enabled and status to active
            update_data = {
                "activated": True,
                "trigger_config.enabled": True,
                "updated_at": datetime.now(timezone.utc),
            }

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, {"$set": update_data}
            )

            if result.matched_count == 0:
                return None

            # Get updated workflow
            updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not updated_workflow:
                return None

            # Schedule if workflow is scheduled type
            if (
                updated_workflow.trigger_config.type == "schedule"
                and updated_workflow.trigger_config.enabled
                and updated_workflow.trigger_config.next_run
            ):
                await workflow_scheduler.schedule_workflow_execution(
                    workflow_id,
                    user_id,
                    updated_workflow.trigger_config.next_run,
                    repeat=updated_workflow.trigger_config.cron_expression,
                    max_occurrences=getattr(updated_workflow, "max_occurrences", None),
                    stop_after=getattr(updated_workflow, "stop_after", None),
                )

            logger.info(f"Activated workflow {workflow_id} for user {user_id}")
            return updated_workflow

        except Exception as e:
            logger.error(f"Error activating workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def deactivate_workflow(
        workflow_id: str, user_id: str, user_timezone: Optional[str] = None
    ) -> Optional[Workflow]:
        """Deactivate a workflow (disable its trigger)."""
        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # Cancel any scheduled executions
            await workflow_scheduler.cancel_scheduled_workflow_execution(workflow_id)

            # Update trigger to disabled and status to inactive
            update_data = {
                "activated": False,
                "trigger_config.enabled": False,
                "updated_at": datetime.now(timezone.utc),
            }

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, {"$set": update_data}
            )

            if result.matched_count == 0:
                return None

            logger.info(f"Deactivated workflow {workflow_id} for user {user_id}")
            return await WorkflowService.get_workflow(workflow_id, user_id)

        except Exception as e:
            logger.error(f"Error deactivating workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def regenerate_workflow_steps(
        workflow_id: str,
        user_id: str,
        regeneration_reason: Optional[str] = None,
        force_different_tools: bool = True,
    ) -> Optional[Workflow]:
        """Regenerate steps for an existing workflow."""
        try:
            # Get the existing workflow
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # Generate new steps using the existing title and description
            steps_data = await WorkflowGenerationService.generate_steps_with_llm(
                workflow.description, workflow.title, workflow.trigger_config
            )

            # Update workflow with new steps
            result = await workflows_collection.find_one_and_update(
                {"_id": workflow_id, "user_id": user_id},
                {
                    "$set": {
                        "steps": steps_data,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                return_document=True,
            )

            if result:
                transformed_doc = transform_workflow_document(result)
                return Workflow(**transformed_doc)
            return None

        except Exception as e:
            logger.error(f"Error regenerating workflow steps {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def increment_execution_count(
        workflow_id: str, user_id: str, is_successful: bool = False
    ) -> bool:
        """Increment workflow execution statistics.

        Args:
            workflow_id: ID of the workflow
            user_id: ID of the user who owns the workflow
            is_successful: Whether the execution was successful

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            inc_data = {"total_executions": 1}
            if is_successful:
                inc_data["successful_executions"] = 1

            update_data = {
                "$inc": inc_data,
                "$set": {"last_executed_at": datetime.now(timezone.utc)},
            }

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, update_data
            )

            success = result.matched_count > 0
            if success:
                logger.debug(
                    f"Updated execution count for workflow {workflow_id}: total +1, successful +{1 if is_successful else 0}"
                )
            else:
                logger.warning(
                    f"Failed to update execution count - workflow not found: {workflow_id}"
                )

            return success

        except Exception as e:
            logger.error(
                f"Error updating execution count for workflow {workflow_id}: {str(e)}"
            )
            return False

    @staticmethod
    async def _generate_workflow_steps(workflow_id: str, user_id: str) -> None:
        """Generate workflow steps using LLM with structured output."""
        try:
            await workflows_collection.find_one_and_update(
                {"_id": workflow_id, "user_id": user_id},
                {"$set": {"updated_at": datetime.now(timezone.utc)}},
            )

            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return

            # Generate steps using structured LLM output
            steps_data = await WorkflowGenerationService.generate_steps_with_llm(
                workflow.description, workflow.title, workflow.trigger_config
            )

            if steps_data:
                await workflows_collection.find_one_and_update(
                    {"_id": workflow_id, "user_id": user_id},
                    {
                        "$set": {
                            "steps": steps_data,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    },
                )
            else:
                await handle_workflow_error(
                    workflow_id, user_id, Exception("Failed to generate workflow steps")
                )

        except Exception as e:
            logger.error(f"Error generating workflow steps for {workflow_id}: {str(e)}")
            await handle_workflow_error(workflow_id, user_id, e)
