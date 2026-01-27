"""
Workflow worker functions for ARQ task processing.
Contains all workflow-related background tasks and execution logic.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.agents.prompts.workflow_prompts import TODO_WORKFLOW_DESCRIPTION_TEMPLATE
from app.api.v1.middleware.tiered_rate_limiter import tiered_rate_limit
from app.config.loggers import worker_logger as logger
from app.config.token_repository import token_repository
from app.core.websocket_manager import get_websocket_manager
from app.db.mongodb.collections import todos_collection
from app.models.chat_models import MessageModel
from app.models.message_models import (
    MessageRequestWithHistory,
    SelectedWorkflowData,
)
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ChannelConfig,
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    RedirectConfig,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
)
from app.services.model_service import get_user_selected_model
from app.services.notification_service import notification_service
from app.services.todos.todo_service import TodoService
from app.services.user_service import get_user_by_id
from app.services.workflow.conversation_service import (
    add_workflow_execution_messages,
    get_or_create_workflow_conversation,
)
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.service import WorkflowService
from bson import ObjectId
from langchain_core.callbacks import UsageMetadataCallbackHandler


async def get_user_authentication_tokens(
    user_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieve user authentication tokens for workflow execution.

    This wrapper function handles token retrieval and refresh for background workflow execution,
    following the same pattern as chat streams to ensure consistent authentication.

    Args:
        user_id: The user ID to get tokens for

    Returns:
        Tuple of (access_token, refresh_token) or (None, None) if not available
    """
    try:
        token = await token_repository.get_token(
            str(user_id), "google", renew_if_expired=True
        )
        if token:
            access_token = (
                str(token.get("access_token", ""))
                if token.get("access_token")
                else None
            )
            refresh_token = (
                str(token.get("refresh_token", ""))
                if token.get("refresh_token")
                else None
            )
            if access_token and refresh_token:
                logger.info(
                    f"Successfully retrieved authentication tokens for user {user_id}"
                )
                return access_token, refresh_token
            else:
                logger.warning(
                    f"Tokens found but empty for user {user_id} - access_token: {bool(access_token)}, refresh_token: {bool(refresh_token)}"
                )
                return None, None
        else:
            logger.warning(f"No authentication tokens found for user {user_id}")
            return None, None

    except Exception as e:
        logger.error(f"Error retrieving authentication tokens for user {user_id}: {e}")
        return None, None


async def process_workflow_generation_task(
    ctx: dict, todo_id: str, user_id: str, title: str, description: str = ""
) -> str:
    """
    Process workflow generation task for todos.
    Migrated from RabbitMQ to ARQ for unified task processing.
    Broadcasts WebSocket event when workflow generation completes.

    Args:
        ctx: ARQ context
        todo_id: Todo ID to generate workflow for
        user_id: User ID who owns the todo
        title: Todo title
        description: Todo description

    Returns:
        Processing result message
    """
    logger.info(f"Processing workflow generation for todo {todo_id}: {title}")

    try:
        # Create rich description using the template
        workflow_description = TODO_WORKFLOW_DESCRIPTION_TEMPLATE.format(
            title=title,
            details_section=f"**Details:** {description}" if description else "",
        )
        # Create standalone workflow with todo workflow flag
        workflow_request = CreateWorkflowRequest(
            title=f"Todo: {title}",
            description=workflow_description,
            trigger_config=TriggerConfig(type=TriggerType.MANUAL, enabled=True),
            generate_immediately=True,
        )

        workflow = await WorkflowService.create_workflow(
            workflow_request,
            user_id,
            is_todo_workflow=True,
            source_todo_id=todo_id,
        )

        if workflow and workflow.id:
            update_data = {
                "workflow_id": workflow.id,
                "updated_at": datetime.now(timezone.utc),
            }

            result = await todos_collection.update_one(
                {"_id": ObjectId(todo_id), "user_id": user_id}, {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(
                    f"Successfully generated and linked standalone workflow {workflow.id} for todo {todo_id} with {len(workflow.steps)} steps"
                )

                await TodoService._invalidate_cache(user_id, None, todo_id, "update")

                try:
                    websocket_manager = get_websocket_manager()
                    await websocket_manager.broadcast_to_user(
                        user_id,
                        {
                            "type": "workflow.generated",
                            "todo_id": todo_id,
                            "workflow": workflow.model_dump(mode="json"),
                        },
                    )
                    logger.info(f"WebSocket event sent for workflow {workflow.id}")
                except Exception as ws_error:
                    logger.warning(f"Failed to send WebSocket event: {ws_error}")

                # Clear the generating flag
                from app.services.workflow.queue_service import WorkflowQueueService

                await WorkflowQueueService.clear_workflow_generating_flag(todo_id)

                return f"Successfully generated standalone workflow {workflow.id} for todo {todo_id}"
            else:
                raise ValueError(f"Todo {todo_id} not found or not updated")

        else:
            # Mark workflow generation as failed
            logger.error(
                f"Failed to generate workflow for todo {todo_id}: No workflow created"
            )
            raise ValueError("Workflow generation failed: No workflow created")

    except Exception as e:
        # Log the error
        error_msg = (
            f"Failed to process workflow generation for todo {todo_id}: {str(e)}"
        )
        logger.error(error_msg)

        # Clear the generating flag on failure too
        try:
            from app.services.workflow.queue_service import WorkflowQueueService

            await WorkflowQueueService.clear_workflow_generating_flag(todo_id)
        except Exception:  # nosec B110 - Intentional: cleanup should not raise
            pass

        # Broadcast failure WebSocket event so frontend can handle it
        try:
            websocket_manager = get_websocket_manager()
            await websocket_manager.broadcast_to_user(
                user_id,
                {
                    "type": "workflow.generation_failed",
                    "todo_id": todo_id,
                    "error": str(e),
                },
            )
            logger.info(f"WebSocket failure event sent for todo {todo_id}")
        except Exception as ws_error:
            logger.warning(f"Failed to send failure WebSocket event: {ws_error}")

        raise


async def execute_workflow_by_id(
    ctx: dict, workflow_id: str, context: Optional[dict] = None
) -> str:
    """
    Execute a workflow by ID with proper execution count tracking.
    """
    logger.info(f"Processing workflow execution: {workflow_id}")

    scheduler = WorkflowScheduler()
    workflow = None
    execution_messages = []

    try:
        await scheduler.initialize()
        workflow = await scheduler.get_task(workflow_id)

        if not workflow:
            return f"Workflow {workflow_id} not found"

        # Execute the workflow
        execution_messages = await execute_workflow_as_chat(
            workflow, {"user_id": workflow.user_id}, context or {}
        )

        # Track successful execution
        await WorkflowService.increment_execution_count(
            workflow_id, workflow.user_id, is_successful=True
        )

        # Store messages and send notification
        await create_workflow_completion_notification(
            workflow, execution_messages, workflow.user_id
        )

        return f"Workflow {workflow_id} executed successfully with {len(execution_messages)} messages"

    except Exception as e:
        logger.error(f"Error executing workflow {workflow_id}: {str(e)}", exc_info=True)

        # Track failed execution
        if workflow:
            try:
                await WorkflowService.increment_execution_count(
                    workflow_id, workflow.user_id, is_successful=False
                )
            except Exception as e2:
                logger.debug(f"Failed to update workflow stats: {e2}")

        # Try to store error messages if any were generated
        if execution_messages and workflow:
            try:
                await create_workflow_completion_notification(
                    workflow, execution_messages, workflow.user_id
                )
            except Exception as e2:
                logger.debug(f"Failed to create notification: {e2}")

        return f"Error executing workflow {workflow_id}: {str(e)}"

    finally:
        if scheduler:
            await scheduler.close()


@tiered_rate_limit("trigger_workflow_executions")
async def execute_workflow_as_chat(workflow, user: dict, context: dict) -> list:
    """
    Execute workflow as a single chat session, just like normal user chat.
    This creates proper tool calls and messages identical to normal chat flow.

    Args:
        workflow: The workflow object to execute
        user: User dict containing user_id (for rate limiting compatibility)
        context: Optional execution context

    Returns:
        List of MessageModel objects from the execution
    """

    # Avoid circular import
    from app.agents.core.agent import call_agent_silent

    # Extract user_id from user dict for backward compatibility
    user_id = user["user_id"]

    try:
        logger.info(
            f"Executing workflow {workflow.id} as chat session for user {user_id}"
        )

        # Get user tokens for authentication (same as chat stream)
        access_token, refresh_token = await get_user_authentication_tokens(user_id)

        if not access_token:
            logger.error(
                f"No access token available for user {user_id} - workflow tools requiring authentication will fail"
            )
        else:
            logger.info(
                f"Access token available for user {user_id} - tools can authenticate"
            )

        # Get user data and create timezone-aware datetime
        try:
            user_data = await get_user_by_id(user_id)
            if user_data:
                user_data["user_id"] = user_id  # Ensure user_id is present
                user_tz = ZoneInfo(user_data.get("timezone", "UTC"))
            else:
                user_data = {"user_id": user_id}
                user_tz = ZoneInfo("UTC")
            user_time = datetime.now(user_tz)
        except Exception as e:
            logger.warning(f"Could not get user data for {user_id}: {e}")
            user_data = {"user_id": user_id}
            user_time = datetime.now(timezone.utc)

        user_model_config = None
        try:
            user_model_config = await get_user_selected_model(user_id)
        except Exception as e:
            logger.warning(
                f"Could not get user's selected model for workflow, using default: {e}"
            )

        # Get or create the workflow conversation for thread context
        conversation = await get_or_create_workflow_conversation(
            workflow_id=workflow.id,
            user_id=user_id,
            workflow_title=workflow.title,
        )

        # Convert workflow steps to the format expected by SelectedWorkflowData
        workflow_steps = []
        for step in workflow.steps:
            workflow_steps.append(
                {
                    "id": step.id,
                    "title": step.title,
                    "description": step.description,
                    "category": step.category,
                }
            )

        selected_workflow_data = SelectedWorkflowData(
            id=workflow.id,
            title=workflow.title,
            description=workflow.description,
            steps=workflow_steps,
        )

        # Create a simple MessageRequestWithHistory for workflow execution
        request = MessageRequestWithHistory(
            message=f"Execute workflow: {workflow.title}",
            messages=[],
            fileIds=[],
            fileData=[],
            selectedTool=None,
            selectedWorkflow=selected_workflow_data,
        )

        usage_metadata_callback = UsageMetadataCallbackHandler()

        # Execute using the same logic as normal chat
        complete_message, tool_data = await call_agent_silent(
            request=request,
            conversation_id=conversation["conversation_id"],
            user=user_data,
            user_time=user_time,
            user_model_config=user_model_config,
            trigger_context=context,
            usage_metadata_callback=usage_metadata_callback,
        )

        # Create execution messages with proper tool data
        execution_messages = []

        # Create a simple user message showing workflow execution (like frontend)
        user_message = MessageModel(
            type="user",
            response="",
            date=datetime.now(timezone.utc).isoformat(),
            message_id=str(uuid4()),
            selectedWorkflow=selected_workflow_data,
        )
        execution_messages.append(user_message)

        # Create the bot message with complete response and tool data
        bot_message = MessageModel(
            type="bot",
            response=complete_message,
            date=datetime.now(timezone.utc).isoformat(),
            message_id=str(uuid4()),
            # metadata=token_metadata,  # Include token usage metadata
            **tool_data,  # Include all captured tool data
        )
        execution_messages.append(bot_message)

        return execution_messages

    except Exception as e:
        logger.error(f"Failed to execute workflow {workflow.id} as chat: {str(e)}")
        # Return error message
        error_message = MessageModel(
            type="bot",
            response=f"❌ **Workflow Execution Failed**\n\nWorkflow: {workflow.title}\nError: {str(e)}",
            date=datetime.now(timezone.utc).isoformat(),
            message_id=str(uuid4()),
        )
        return [error_message]


async def regenerate_workflow_steps(
    ctx: dict,
    workflow_id: str,
    user_id: str,
    regeneration_reason: str,
    force_different_tools: bool = True,
) -> str:
    """
    Regenerate workflow steps for an existing workflow.

    Args:
        ctx: ARQ context
        workflow_id: ID of the workflow to regenerate steps for
        user_id: ID of the user who owns the workflow
        regeneration_reason: Reason for regeneration
        force_different_tools: Whether to force different tools

    Returns:
        Processing result message
    """
    logger.info(
        f"Regenerating workflow steps: {workflow_id} for user {user_id}, reason: {regeneration_reason}"
    )

    try:
        # Import here to avoid circular imports
        from app.services.workflow import WorkflowService

        # Regenerate steps using the service method (without background queue)
        await WorkflowService.regenerate_workflow_steps(
            workflow_id,
            user_id,
            regeneration_reason,
            force_different_tools,
        )

        result = f"Successfully regenerated steps for workflow {workflow_id}"
        logger.info(result)
        return result

    except Exception as e:
        error_msg = f"Failed to regenerate workflow steps {workflow_id}: {str(e)}"
        logger.error(error_msg)
        raise


async def generate_workflow_steps(ctx: dict, workflow_id: str, user_id: str) -> str:
    """
    Generate workflow steps for a workflow.
    Broadcasts WebSocket event when complete if it's a todo workflow.

    Args:
        ctx: ARQ context
        workflow_id: ID of the workflow to generate steps for
        user_id: ID of the user who owns the workflow

    Returns:
        Processing result message
    """
    logger.info(f"Generating workflow steps: {workflow_id} for user {user_id}")

    try:
        # Import here to avoid circular imports
        from app.services.workflow import WorkflowService

        # Generate steps using the service method
        await WorkflowService._generate_workflow_steps(workflow_id, user_id)

        # Fetch the updated workflow to get the generated steps
        updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)

        # If this is a todo workflow, send WebSocket event
        if (
            updated_workflow
            and updated_workflow.is_todo_workflow
            and updated_workflow.source_todo_id
        ):
            try:
                websocket_manager = get_websocket_manager()
                await websocket_manager.broadcast_to_user(
                    user_id,
                    {
                        "type": "workflow.generated",
                        "todo_id": updated_workflow.source_todo_id,
                        "workflow": updated_workflow.model_dump(mode="json"),
                    },
                )
                logger.info(f"WebSocket event sent for todo workflow {workflow_id}")
            except Exception as ws_error:
                logger.warning(f"Failed to send WebSocket event: {ws_error}")

        result = f"Successfully generated steps for workflow {workflow_id}"
        logger.info(result)
        return result

    except Exception as e:
        error_msg = f"Failed to generate workflow steps {workflow_id}: {str(e)}"
        logger.error(error_msg)
        raise


async def create_workflow_completion_notification(
    workflow, execution_messages, user_id: str
):
    """Store workflow execution messages and send completion notification."""

    # Get or create conversation (required for storage)
    conversation = await get_or_create_workflow_conversation(
        workflow_id=workflow.id,
        user_id=user_id,
        workflow_title=workflow.title,
    )
    logger.info(
        f"Workflow conversation: {conversation['conversation_id']} for workflow {workflow.id}"
    )

    # Store execution messages
    if execution_messages:
        try:
            logger.info(
                f"Storing {len(execution_messages)} messages to conversation {conversation['conversation_id']}"
            )
            await add_workflow_execution_messages(
                conversation_id=conversation["conversation_id"],
                workflow_execution_messages=execution_messages,
                user_id=user_id,
            )
            logger.info(
                f"Successfully stored {len(execution_messages)} messages for workflow {workflow.id}"
            )
        except Exception as storage_error:
            logger.error(
                f"Failed to store messages for workflow {workflow.id}: {storage_error}",
                exc_info=True,
            )
            raise  # Re-raise to ensure storage failures are visible
    else:
        logger.warning(f"No execution messages to store for workflow {workflow.id}")

    # Send notification (best effort - don't fail if this breaks)
    try:
        await notification_service.create_notification(
            NotificationRequest(
                user_id=user_id,
                source=NotificationSourceEnum.BACKGROUND_JOB,
                content=NotificationContent(
                    title=f"Workflow Completed: {workflow.title}",
                    body=f"Your workflow '{workflow.title}' has completed successfully.",
                    actions=[
                        NotificationAction(
                            type=ActionType.REDIRECT,
                            label="View Results",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url=f"/c/{conversation['conversation_id']}",
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    ],
                ),
                channels=[
                    ChannelConfig(channel_type="inapp", enabled=True, priority=1)
                ],
                metadata={
                    "workflow_id": workflow.id,
                    "conversation_id": conversation["conversation_id"],
                },
            )
        )
        logger.info(f"Notification sent for workflow {workflow.id}")
    except Exception as e:
        logger.error(f"Failed to send notification for workflow {workflow.id}: {e}")
