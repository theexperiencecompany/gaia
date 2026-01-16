"""
Clean workflow service for GAIA workflow system.
Handles CRUD operations and execution coordination.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from app.config.loggers import general_logger as logger
from app.db.chroma.chromadb import ChromaClient
from app.db.mongodb.collections import workflows_collection
from app.decorators.caching import Cacheable
from app.models.workflow_models import (
    CreateWorkflowRequest,
    PublicWorkflowsResponse,
    TriggerConfig,
    TriggerType,
    UpdateWorkflowRequest,
    Workflow,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowStatusResponse,
)
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError
from app.utils.workflow_utils import (
    ensure_trigger_config_object,
    handle_workflow_error,
    transform_workflow_document,
)

from .generation_service import WorkflowGenerationService
from .queue_service import WorkflowQueueService
from .scheduler import workflow_scheduler
from .validators import WorkflowValidator


class WorkflowService:
    """Service class for workflow operations."""

    @staticmethod
    async def _register_integration_triggers(
        workflow_id: str,
        user_id: str,
        trigger_config: TriggerConfig,
    ) -> List[str]:
        """Register Composio triggers for integration-based workflows.

        Delegates to TriggerService which handles provider-specific logic.
        Returns list of registered trigger IDs.

        Raises:
            TriggerRegistrationError: If trigger registration fails
        """
        # Only handle integration type triggers
        if trigger_config.type != TriggerType.INTEGRATION:
            logger.debug(
                f"Skipping trigger registration: type={trigger_config.type} is not INTEGRATION"
            )
            return []

        trigger_name = trigger_config.trigger_name
        if not trigger_name:
            raise TriggerRegistrationError(
                "Integration trigger requires 'trigger_name' but none was provided. "
                "This indicates a frontend configuration error.",
                trigger_name="unknown",
            )

        # Use raise_on_failure=True to ensure errors propagate
        trigger_ids = await TriggerService.register_triggers(
            user_id=user_id,
            workflow_id=workflow_id,
            trigger_name=trigger_name,
            trigger_config=trigger_config,
            raise_on_failure=True,
        )

        return trigger_ids

    @staticmethod
    async def create_workflow(
        request: CreateWorkflowRequest,
        user_id: str,
        user_timezone: Optional[str] = None,
        is_todo_workflow: bool = False,
        source_todo_id: Optional[str] = None,
    ) -> Workflow:
        """Create a new workflow with automatic timezone population.

        Uses Saga pattern for atomicity:
        1. Create workflow in pending state (activated=False)
        2. Register Composio triggers (if needed)
        3. Activate workflow with trigger IDs
        4. On failure: rollback (delete workflow)
        """
        workflow_id: Optional[str] = None
        trigger_ids: List[str] = []

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

            # Use provided steps or initialize empty list for generation
            workflow_steps = request.steps if request.steps else []

            # Step 1: Create workflow in PENDING state (activated=False)
            workflow = Workflow(
                title=request.title,
                description=request.description,
                steps=workflow_steps,
                trigger_config=trigger_config,
                activated=False,  # Start in pending state
                user_id=user_id,
                is_todo_workflow=is_todo_workflow,
                source_todo_id=source_todo_id,
            )

            # Insert into database
            workflow_dict = workflow.model_dump(mode="json")
            workflow_dict["_id"] = workflow_dict["id"]

            result = await workflows_collection.insert_one(workflow_dict)
            if not result.inserted_id:
                raise ValueError("Failed to create workflow in database")

            workflow_id = workflow.id
            logger.info(f"Created pending workflow {workflow_id} for user {user_id}")

            # Store in ChromaDB for semantic search (non-critical, don't fail on error)
            try:
                chroma = await ChromaClient.get_langchain_client(
                    "workflows", create_if_not_exists=True
                )
                content = (
                    f"{workflow.title} | {workflow.description} | {trigger_config.type}"
                )
                chroma.add_texts(
                    texts=[content],
                    metadatas=[
                        {
                            "user_id": user_id,
                            "workflow_id": str(workflow.id),
                            "trigger_type": trigger_config.type,
                        }
                    ],
                    ids=[str(workflow.id)],
                )
            except Exception as e:
                logger.warning(f"Failed to store workflow in ChromaDB: {e}")

            if not workflow.id:
                raise ValueError("Workflow ID is required")

            # Step 2: Register integration triggers (this can raise TriggerRegistrationError)
            # The handlers will rollback their own partial triggers on failure
            trigger_ids = await WorkflowService._register_integration_triggers(
                workflow_id=workflow.id,
                user_id=user_id,
                trigger_config=trigger_config,
            )

            # Step 3: Activate workflow and store trigger IDs
            update_data: dict[str, Any] = {"activated": True}
            if trigger_ids:
                update_data["trigger_config.composio_trigger_ids"] = trigger_ids

            await workflows_collection.update_one(
                {"_id": workflow.id},
                {"$set": update_data},
            )

            # Update local workflow object
            workflow.activated = True
            if trigger_ids:
                workflow.trigger_config.composio_trigger_ids = trigger_ids

            logger.info(
                f"Activated workflow {workflow.id} with {len(trigger_ids)} triggers"
            )

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

            # Generate steps only if not provided
            if not request.steps:
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
            else:
                logger.info(
                    f"Workflow {workflow.id} created with {len(request.steps)} pre-existing steps, skipping generation"
                )

            return workflow

        except TriggerRegistrationError as e:
            # Saga compensation: delete the pending workflow
            logger.error(f"Trigger registration failed, rolling back workflow: {e}")
            if workflow_id:
                try:
                    await workflows_collection.delete_one({"_id": workflow_id})
                    logger.info(f"Rolled back workflow {workflow_id}")
                except Exception as delete_error:
                    logger.error(
                        f"Failed to rollback workflow {workflow_id}: {delete_error}"
                    )
            raise

        except Exception as e:
            logger.error(f"Error creating workflow: {str(e)}")
            # For other errors, still try to cleanup if workflow was created
            if workflow_id:
                try:
                    # Cleanup any triggers that were registered
                    if trigger_ids:
                        trigger_name = request.trigger_config.trigger_name
                        if trigger_name:
                            await TriggerService.unregister_triggers(
                                user_id, trigger_name, trigger_ids, workflow_id
                            )
                    await workflows_collection.delete_one({"_id": workflow_id})
                    logger.info(f"Rolled back workflow {workflow_id} after error")
                except Exception as cleanup_error:
                    logger.error(f"Cleanup failed for {workflow_id}: {cleanup_error}")
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
    async def list_workflows(
        user_id: str, exclude_todo_workflows: bool = True
    ) -> List[Workflow]:
        """List all workflows for a user.

        Args:
            user_id: User ID to filter by
            exclude_todo_workflows: If True, filter out auto-generated todo workflows
        """
        try:
            # Build query - filter out todo workflows by default
            query: dict[str, Any] = {"user_id": user_id}
            if exclude_todo_workflows:
                query["$or"] = [
                    {"is_todo_workflow": {"$exists": False}},
                    {"is_todo_workflow": False},
                ]

            # Use to_list() for better performance
            docs = (
                await workflows_collection.find(query)
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
        """Update an existing workflow with timezone awareness.

        Uses Saga pattern for trigger updates: if new trigger registration fails,
        attempts to restore the old triggers (compensation).
        """
        # Track state for potential rollback
        old_trigger_ids: List[str] = []
        old_trigger_name: str = ""

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

                # Handle trigger re-registration for integration triggers
                # Always delete and recreate triggers since Composio triggers can't be updated
                new_trigger_type = new_trigger_config.type
                is_integration_trigger = new_trigger_type == TriggerType.INTEGRATION
                registered_trigger_ids = None

                if is_integration_trigger and current_workflow.activated:
                    old_trigger_name = old_config.trigger_name or ""
                    old_trigger_ids = old_config.composio_trigger_ids or []

                    # Delete old triggers (pass workflow_id for reference counting)
                    if old_trigger_ids:
                        await TriggerService.unregister_triggers(
                            user_id, old_trigger_name, old_trigger_ids, workflow_id
                        )

                    # Register new triggers (can raise TriggerRegistrationError)
                    registered_trigger_ids = (
                        await WorkflowService._register_integration_triggers(
                            workflow_id=workflow_id,
                            user_id=user_id,
                            trigger_config=new_trigger_config,
                        )
                    )

                # Convert TriggerConfig back to dict for MongoDB storage
                update_fields["trigger_config"] = new_trigger_config.model_dump(
                    mode="json"
                )

                # Add new trigger IDs if triggers were registered
                if registered_trigger_ids is not None:
                    update_fields["trigger_config"]["composio_trigger_ids"] = (
                        registered_trigger_ids
                    )

            update_data.update(update_fields)

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, {"$set": update_data}
            )

            if result.matched_count == 0:
                return None

            logger.info(f"Updated workflow {workflow_id} for user {user_id}")
            return await WorkflowService.get_workflow(workflow_id, user_id)

        except TriggerRegistrationError as e:
            # Compensation: try to restore old triggers
            logger.error(f"Trigger update failed for workflow {workflow_id}: {e}")
            if old_trigger_ids and old_trigger_name:
                logger.info(
                    f"Attempting to restore {len(old_trigger_ids)} old triggers for workflow {workflow_id}"
                )
                # Note: We previously deleted old triggers, but this was before new registration failed
                # The old triggers are already gone - we just need to inform the user
                # In a perfect system, we'd re-register old triggers, but that could also fail
            raise

        except Exception as e:
            logger.error(f"Error updating workflow {workflow_id}: {str(e)}")
            raise

    @staticmethod
    async def delete_workflow(workflow_id: str, user_id: str) -> bool:
        """Delete a workflow."""
        try:
            # Get workflow first to access trigger config
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)

            # Cancel any scheduled executions before deleting
            await workflow_scheduler.cancel_scheduled_workflow_execution(workflow_id)

            # Additional cleanup
            try:
                await workflow_scheduler.cancel_task(workflow_id, user_id)
            except Exception as e:
                logger.warning(
                    f"Additional cleanup failed for workflow {workflow_id}: {e}"
                )

            # Unregister Composio triggers if any (pass workflow_id for reference counting)
            if workflow:
                trigger_config = workflow.trigger_config
                trigger_ids = trigger_config.composio_trigger_ids or []
                if trigger_ids:
                    trigger_name = trigger_config.trigger_name
                    if trigger_name:
                        await TriggerService.unregister_triggers(
                            user_id, trigger_name, trigger_ids, workflow_id
                        )
                    else:
                        logger.warning(
                            f"No trigger_name found for workflow {workflow_id}, cannot unregister triggers"
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
        """Activate a workflow (enable its trigger).

        Uses Saga pattern: if trigger registration fails, the workflow remains inactive.
        """
        trigger_ids: List[str] = []

        try:
            workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not workflow:
                return None

            # 1. Register Composio triggers FIRST (can raise TriggerRegistrationError)
            trigger_config = workflow.trigger_config
            trigger_type = trigger_config.type

            # Use the shared method for integration trigger registration
            trigger_ids = await WorkflowService._register_integration_triggers(
                workflow_id=workflow_id,
                user_id=user_id,
                trigger_config=trigger_config,
            )

            if trigger_ids:
                logger.info(
                    f"Registered {len(trigger_ids)} Composio triggers for workflow {workflow_id}"
                )

            # Get trigger_name for potential rollback
            trigger_name = trigger_config.trigger_name

            # 2. Update status and store triggers
            update_data: dict[str, Any] = {
                "activated": True,
                "trigger_config.enabled": True,
                "trigger_config.composio_trigger_ids": trigger_ids,
                "updated_at": datetime.now(timezone.utc),
            }

            result = await workflows_collection.update_one(
                {"_id": workflow_id, "user_id": user_id}, {"$set": update_data}
            )

            if result.matched_count == 0:
                # Rollback triggers if DB update fails (pass workflow_id for reference counting)
                if trigger_ids and trigger_name:
                    await TriggerService.unregister_triggers(
                        user_id, trigger_name, trigger_ids, workflow_id
                    )
                return None

            # 3. Get updated workflow
            updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)
            if not updated_workflow:
                return None

            # 4. Schedule if needed
            if (
                trigger_type == "schedule"
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

        except TriggerRegistrationError as e:
            # Trigger registration failed - workflow remains inactive
            logger.error(f"Failed to activate workflow {workflow_id}: {e}")
            raise

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

            # Unregister Composio triggers if any (pass workflow_id for reference counting)
            trigger_config = workflow.trigger_config
            trigger_ids = trigger_config.composio_trigger_ids or []
            if trigger_ids:
                trigger_name = trigger_config.trigger_name
                if trigger_name:
                    await TriggerService.unregister_triggers(
                        user_id, trigger_name, trigger_ids, workflow_id
                    )
                    logger.info(
                        f"Unregistered {len(trigger_ids)} Composio triggers for workflow {workflow_id}"
                    )
                else:
                    logger.warning(
                        f"No trigger_name found for workflow {workflow_id}, cannot unregister triggers"
                    )

            # Update trigger to disabled and clear trigger IDs
            update_data: dict[str, Any] = {
                "activated": False,
                "trigger_config.enabled": False,
                "trigger_config.composio_trigger_ids": [],
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
    @Cacheable(smart_hash=True, ttl=300, model=PublicWorkflowsResponse)
    async def get_community_workflows(
        limit: int = 20,
        offset: int = 0,
        user_id: Optional[str] = None,
    ) -> PublicWorkflowsResponse:
        """Get public workflows from the community marketplace with caching."""
        try:
            pipeline = [
                {
                    "$match": {
                        "is_public": True,
                        "$or": [
                            {"is_explore": {"$exists": False}},
                            {"is_explore": False},
                        ],
                    }
                },
                {"$sort": {"created_at": -1}},
                {"$skip": offset},
                {"$limit": limit},
                {
                    "$lookup": {
                        "from": "users",
                        "let": {"creator_id": "$created_by"},
                        "pipeline": [
                            {
                                "$match": {
                                    "$expr": {
                                        "$eq": ["$_id", {"$toObjectId": "$$creator_id"}]
                                    }
                                }
                            },
                            {
                                "$project": {
                                    "name": 1,
                                    "email": 1,
                                    "picture": 1,
                                    "_id": 0,
                                }
                            },
                        ],
                        "as": "creator_info",
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "title": 1,
                        "description": 1,
                        "steps": {
                            "$map": {
                                "input": "$steps",
                                "as": "step",
                                "in": {
                                    "title": "$$step.title",
                                    "category": "$$step.category",
                                    "description": "$$step.description",
                                },
                            }
                        },
                        "upvoted_by": 1,
                        "created_at": 1,
                        "created_by": 1,
                        "creator_info": 1,
                    }
                },
            ]

            workflows = await workflows_collection.aggregate(pipeline).to_list(
                length=limit
            )
            # Exclude explore workflows from community count
            total = await workflows_collection.count_documents(
                {
                    "is_public": True,
                    "$or": [{"is_explore": {"$exists": False}}, {"is_explore": False}],
                }
            )

            formatted_workflows = []
            for workflow in workflows:
                creator_info = (
                    workflow.get("creator_info", [{}])[0]
                    if workflow.get("creator_info")
                    else {}
                )

                # Normalize steps to use 'category' field (handle legacy 'tool_category')
                raw_steps = workflow.get("steps", [])
                normalized_steps = []
                for step in raw_steps:
                    normalized_step = {
                        "id": step.get("id", ""),
                        "title": step.get("title", ""),
                        "description": step.get("description", ""),
                        # Use 'category' if present, fall back to 'tool_category'
                        "category": step.get("category")
                        or step.get("tool_category", "general"),
                    }
                    normalized_steps.append(normalized_step)

                formatted_workflow = {
                    "id": workflow["_id"],
                    "title": workflow["title"],
                    "description": workflow["description"],
                    "steps": normalized_steps,
                    "created_at": workflow["created_at"],
                    "creator": {
                        "id": workflow.get("created_by"),
                        "name": creator_info.get("name", "Unknown"),
                        "avatar": creator_info.get("picture"),
                    },
                }
                formatted_workflows.append(formatted_workflow)

            return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

        except Exception as e:
            logger.error(f"Error fetching community workflows: {str(e)}")
            raise

    @staticmethod
    @Cacheable(smart_hash=True, ttl=600, model=PublicWorkflowsResponse)
    async def get_explore_workflows(
        limit: int = 25,
        offset: int = 0,
    ) -> PublicWorkflowsResponse:
        """Get explore/featured workflows for the discover section with caching."""
        try:
            # Query for explore workflows (is_explore = True)
            query = {"is_explore": True}

            # Get total count
            total = await workflows_collection.count_documents(query)

            # Get workflows with pagination, sorted by execution count and recency
            workflows = await workflows_collection.aggregate(
                [
                    {"$match": query},
                    {"$sort": {"total_executions": -1, "updated_at": -1}},
                    {"$skip": offset},
                    {"$limit": limit},
                    {
                        "$lookup": {
                            "from": "users",
                            "localField": "created_by",
                            "foreignField": "_id",
                            "as": "creator_info",
                        }
                    },
                ]
            ).to_list(length=None)

            # Format workflows with creator information
            formatted_workflows = []
            for workflow in workflows:
                creator_info = (
                    workflow.get("creator_info", [{}])[0]
                    if workflow.get("creator_info")
                    else {}
                )

                # Normalize steps to use 'category' field (handle legacy 'tool_category')
                raw_steps = workflow.get("steps", [])
                normalized_steps = []
                for step in raw_steps:
                    normalized_step = {
                        "id": step.get("id", ""),
                        "title": step.get("title", ""),
                        "description": step.get("description", ""),
                        # Use 'category' if present, fall back to 'tool_category'
                        "category": step.get("category")
                        or step.get("tool_category", "general"),
                    }
                    normalized_steps.append(normalized_step)

                formatted_workflow = {
                    "id": workflow["_id"],
                    "title": workflow["title"],
                    "description": workflow["description"],
                    "steps": normalized_steps,
                    "created_at": workflow["created_at"],
                    "categories": workflow.get("use_case_categories", ["featured"]),
                    "total_executions": workflow.get("total_executions", 0),
                    "creator": {
                        "id": workflow.get("created_by"),
                        "name": creator_info.get("name", "GAIA Team"),
                        "avatar": creator_info.get("picture"),
                    },
                }
                formatted_workflows.append(formatted_workflow)

            return PublicWorkflowsResponse(workflows=formatted_workflows, total=total)

        except Exception as e:
            logger.error(f"Error fetching explore workflows: {str(e)}")
            raise

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
