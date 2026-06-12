"""
Workflow worker functions for ARQ task processing.
Contains all workflow-related background tasks and execution logic.
"""

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from bson import ObjectId

from app.agents.prompts.workflow_prompts import (
    TODO_WORKFLOW_DESCRIPTION_TEMPLATE,
    TODO_WORKFLOW_PROMPT_TEMPLATE,
)
from app.api.v1.middleware.tiered_rate_limiter import (
    RateLimitExceededException,
    tiered_rate_limit,
)
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
    NotificationAction,
    NotificationContent,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
    RedirectConfig,
)
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
    Workflow,
)
from app.services.notification_service import notification_service
from app.services.todos.todo_service import TodoService
from app.services.user_service import get_user_by_id
from app.services.workflow.conversation_service import (
    add_workflow_execution_messages,
    get_or_create_workflow_conversation,
)
from app.services.workflow.scheduler import WorkflowScheduler
from app.services.workflow.service import WorkflowService
from app.utils.timezone import format_local_time
from shared.py.wide_events import WorkflowContext, log, wide_task


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
    async with wide_task("process_workflow_generation_task", todo_id=todo_id, user_id=user_id):
        log.info(f"Processing workflow generation for todo {todo_id}: {title}")

        try:
            # Build short card description plus detailed execution prompt
            workflow_description = TODO_WORKFLOW_DESCRIPTION_TEMPLATE.format(title=title)
            workflow_prompt = TODO_WORKFLOW_PROMPT_TEMPLATE.format(
                title=title,
                details_section=f"**Details:** {description}" if description else "",
            )
            # Create standalone workflow with todo workflow flag
            workflow_request = CreateWorkflowRequest(
                title=f"Todo: {title}",
                description=workflow_description,
                prompt=workflow_prompt,
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
                # Verify workflow actually has steps before linking
                if not workflow.steps or len(workflow.steps) == 0:
                    reason = workflow.error_message or "unknown error"
                    raise ValueError(f"Workflow {workflow.id} created but has no steps — {reason}")

                update_data = {
                    "workflow_id": workflow.id,
                    "updated_at": datetime.now(UTC),
                }

                result = await todos_collection.update_one(
                    {"_id": ObjectId(todo_id), "user_id": user_id},
                    {"$set": update_data},
                )

                if result.modified_count > 0:
                    log.info(
                        f"Successfully generated and linked standalone workflow {workflow.id} for todo {todo_id} with {len(workflow.steps)} steps"
                    )
                    log.set(
                        workflow=WorkflowContext(
                            id=workflow.id,
                            steps_count=len(workflow.steps),
                            trigger_type=TriggerType.MANUAL.value,
                        )
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
                        log.set(websocket_broadcast_success=True)
                        log.info(f"WebSocket event sent for workflow {workflow.id}")
                    except Exception as ws_error:
                        log.set(websocket_broadcast_success=False)
                        log.warning(f"Failed to send WebSocket event: {ws_error}")

                    # Clear the generating flag
                    from app.services.workflow.queue_service import WorkflowQueueService

                    await WorkflowQueueService.clear_workflow_generating_flag(todo_id)

                    return f"Successfully generated standalone workflow {workflow.id} for todo {todo_id}"
                raise ValueError(f"Todo {todo_id} not found or not updated")

            # Mark workflow generation as failed
            log.error(f"Failed to generate workflow for todo {todo_id}: No workflow created")
            raise ValueError("Workflow generation failed: No workflow created")

        except Exception as e:
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
                log.set(websocket_broadcast_success=True)
                log.info(f"WebSocket failure event sent for todo {todo_id}")
            except Exception as ws_error:
                log.set(websocket_broadcast_success=False)
                log.warning(f"Failed to send failure WebSocket event: {ws_error}")

            raise


async def _rearm_if_scheduled(
    scheduler: WorkflowScheduler, workflow: Workflow | None, context: dict | None
) -> None:
    """Arm the next occurrence for cron-scheduled recurring workflows.

    Only scheduler-originated fires (trigger_type=schedule) advance the schedule;
    manual and integration-triggered runs must not shift it. A workflow deactivated
    while a fire was in flight must not be re-armed back into the scheduled loop —
    liveness is governed by `activated`.
    """
    if workflow is None or not workflow.repeat or not workflow.activated:
        return
    trigger_type = context.get("trigger_type") if context else None
    if trigger_type != TriggerType.SCHEDULE.value:
        return
    await scheduler.handle_recurring_task(workflow, (workflow.occurrence_count or 0) + 1)


async def execute_workflow_by_id(ctx: dict, workflow_id: str, context: dict | None = None) -> str:
    """
    Execute a workflow by ID with proper execution count tracking.
    """
    async with wide_task("execute_workflow_by_id", workflow_id=workflow_id):
        actual_fire_utc = datetime.now(UTC)
        log.set(actual_fire_utc=actual_fire_utc.isoformat())
        log.info(f"Processing workflow execution: {workflow_id}")

        scheduler = WorkflowScheduler()
        workflow = None
        execution_id = None

        # Import execution service
        from app.services.workflow.execution_service import (
            complete_execution,
            create_execution,
        )

        try:
            await scheduler.initialize()
            workflow = await scheduler.get_task(workflow_id)

            if not workflow:
                return f"Workflow {workflow_id} not found"

            # Determine trigger type from context
            trigger_type = context.get("trigger_type", "manual") if context else "manual"
            log.set(
                workflow=WorkflowContext(
                    id=workflow_id,
                    trigger_type=trigger_type,
                    steps_count=len(workflow.steps),
                )
            )

            # Scheduler-originated fires: atomically claim the occurrence (scheduled ->
            # executing) so a concurrent recovery scan can't double-execute a workflow
            # whose previous fire is still running. Manual/integration "run now" fires
            # don't go through the scan and must not be status-gated.
            if trigger_type == TriggerType.SCHEDULE.value and not (
                await scheduler.claim_scheduled_for_execution(workflow_id)
            ):
                log.warning(
                    f"Workflow {workflow_id} not in scheduled state "
                    f"(already claimed or running); skipping duplicate scheduled fire"
                )
                return f"Workflow {workflow_id} already claimed; skipped duplicate scheduled fire"

            scheduled_at = getattr(workflow, "scheduled_at", None)
            if isinstance(scheduled_at, datetime):
                if scheduled_at.tzinfo is None:
                    scheduled_at = scheduled_at.replace(tzinfo=UTC)
                drift = int((actual_fire_utc - scheduled_at).total_seconds())
                log.set(
                    scheduled_at_utc=scheduled_at.isoformat(),
                    drift_from_scheduled_seconds=drift,
                )
                if abs(drift) > 300:
                    log.warning(
                        f"Workflow {workflow_id} fired {drift}s off schedule "
                        f"(positive = late, negative = early)",
                    )

            # Create execution record at start
            execution = await create_execution(
                workflow_id=workflow_id,
                user_id=workflow.user_id,
                trigger_type=trigger_type,
            )
            execution_id = execution.execution_id

            # Run the workflow as a silent chat turn. The executor does all the
            # steps and its result is delivered as the completion notification
            # from the background delivery path (gated by workflow_id), so there
            # is no separate notification call here.
            conversation_id = await execute_workflow_as_chat(
                workflow, {"user_id": workflow.user_id}, context or {}
            )

            # Track successful execution
            await WorkflowService.increment_execution_count(
                workflow_id, workflow.user_id, is_successful=True
            )

            # Complete execution record with success
            await complete_execution(
                execution_id=execution_id,
                status="success",
                summary="Workflow executed",
                conversation_id=conversation_id,
            )

            # Arm the next occurrence (scheduled recurring workflows only). A re-arm
            # failure must not turn a successful execution into a reported failure.
            try:
                await _rearm_if_scheduled(scheduler, workflow, context)
            except Exception as rearm_err:
                log.error("Failed to re-arm workflow %s: %s" % (workflow_id, rearm_err))

            return f"Workflow {workflow_id} executed successfully"

        except Exception as e:
            log.exception(
                f"Error executing workflow {workflow_id}: {e}",
            )

            # Complete execution record with failure
            if execution_id:
                try:
                    await complete_execution(
                        execution_id=execution_id,
                        status="failed",
                        error_message=str(e),
                    )
                except Exception as e2:
                    log.debug("Failed to complete execution record: %s" % e2)

            # Track failed execution
            if workflow:
                try:
                    await WorkflowService.increment_execution_count(
                        workflow_id, workflow.user_id, is_successful=False
                    )
                except Exception as e2:
                    log.debug("Failed to update workflow stats: %s" % e2)

            # Send failure notification so the user knows the workflow failed
            if workflow:
                try:
                    if isinstance(e, RateLimitExceededException):
                        title = f"Workflow Failed: {workflow.title}"
                        detail: dict[str, str] = e.detail if isinstance(e.detail, dict) else {}
                        plan_required = detail.get("plan_required", "pro").upper()
                        reset_time_str = detail.get("reset_time", "")

                        if reset_time_str:
                            # Quota exhausted — show when the limit resets
                            try:
                                reset_dt = datetime.fromisoformat(reset_time_str)
                                if reset_dt.tzinfo is None:
                                    reset_dt = reset_dt.replace(tzinfo=UTC)
                                try:
                                    reset_user = await get_user_by_id(workflow.user_id)
                                    reset_tz = reset_user.get("timezone") if reset_user else None
                                except Exception:
                                    reset_tz = None
                                formatted_reset = format_local_time(
                                    reset_dt, reset_tz, fmt="%b %d at %I:%M %p %Z"
                                )
                                body = (
                                    f"'{workflow.title}' couldn't run — "
                                    f"you've used all your workflow executions for today. "
                                    f"Resets {formatted_reset}. "
                                    f"Upgrade to {plan_required} for higher daily limits."
                                )
                            except Exception:
                                body = (
                                    f"'{workflow.title}' couldn't run — "
                                    f"you've used all your workflow executions for today. "
                                    f"Upgrade to {plan_required} for higher daily limits."
                                )
                        else:
                            # Plan-gated — feature isn't available on their plan at all
                            body = (
                                f"'{workflow.title}' couldn't run — "
                                f"automated workflow execution is not available on your current plan. "
                                f"Upgrade to {plan_required} to unlock this feature."
                            )

                        upgrade_action = NotificationAction(
                            type=ActionType.REDIRECT,
                            label=f"Upgrade to {plan_required}",
                            style=ActionStyle.PRIMARY,
                            config=ActionConfig(
                                redirect=RedirectConfig(
                                    url="/settings?section=subscription",
                                    open_in_new_tab=False,
                                    close_notification=True,
                                )
                            ),
                        )
                    else:
                        title = f"Workflow Failed: {workflow.title}"
                        body = f"Your workflow '{workflow.title}' encountered an error and could not complete."
                        upgrade_action = None

                    await notification_service.create_notification(
                        NotificationRequest(
                            user_id=workflow.user_id,
                            source=NotificationSourceEnum.WORKFLOW_FAILED,
                            type=NotificationType.ERROR,
                            content=NotificationContent(
                                title=title,
                                body=body,
                                actions=[upgrade_action] if upgrade_action else None,
                            ),
                            metadata={
                                "workflow_id": workflow.id,
                                "error_type": type(e).__name__,
                            },
                        )
                    )
                except Exception as notify_err:
                    log.debug("Failed to send failure notification: %s" % notify_err)

            # Still arm the next occurrence — a transient failure (rate limit, LLM
            # error) must not permanently kill a recurring workflow.
            try:
                await _rearm_if_scheduled(scheduler, workflow, context)
            except Exception as rearm_err:
                log.error("Failed to re-arm workflow %s: %s" % (workflow_id, rearm_err))

            return "Error executing workflow %s: %s" % (workflow_id, str(e))

        finally:
            if scheduler:
                await scheduler.close()


@tiered_rate_limit("trigger_workflow_executions")
async def execute_workflow_as_chat(workflow, user: dict, context: dict) -> str:
    """Run a workflow as a silent chat turn and return its conversation id.

    The workflow is fed to the agent exactly like an interactive chat turn (same
    ``call_agent_silent`` entry, same ``selectedWorkflow`` awareness). Comms
    delegates the whole workflow to the executor, which runs every step and
    synthesizes one result. That result is delivered as the workflow-completion
    notification from the background executor path (gated by ``workflow_id`` in
    the trigger context), so this function only kicks off the run and persists
    the trigger message; it does not build or send the result here.
    """

    # Avoid circular import
    from app.agents.core.agent import call_agent_silent

    user_id = user["user_id"]

    try:
        log.info(f"Executing workflow {workflow.id} as chat session for user {user_id}")

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
            log.warning(f"Could not get user data for {user_id}: {e}")
            user_data = {"user_id": user_id}
            user_time = datetime.now(UTC)

        # Get or create the workflow conversation for thread context
        conversation = await get_or_create_workflow_conversation(
            workflow_id=workflow.id,
            user_id=user_id,
            workflow_title=workflow.title,
        )
        conversation_id = conversation["conversation_id"]
        log.set(conversation_context_found=bool(conversation_id))

        selected_workflow_data = SelectedWorkflowData(
            id=workflow.id,
            title=workflow.title,
            description=workflow.description,
            prompt=workflow.prompt,
            steps=[
                {
                    "id": step.id,
                    "title": step.title,
                    "description": step.description,
                    "category": step.category,
                }
                for step in workflow.steps
            ],
        )

        # Persist the trigger as the user message. The text is left empty so the
        # UI renders just the workflow card (via selectedWorkflow), not a literal
        # "Run workflow: ..." bubble. The result is saved by the delivery path.
        trigger_message = MessageModel(
            type="user",
            response="",
            date=datetime.now(UTC).isoformat(),
            message_id=str(uuid4()),
            selectedWorkflow=selected_workflow_data,
        )
        await add_workflow_execution_messages(
            conversation_id=conversation_id,
            workflow_execution_messages=[trigger_message],
            user_id=user_id,
        )

        request = MessageRequestWithHistory(
            message=f"Execute workflow: {workflow.title}",
            messages=[],
            fileIds=[],
            fileData=[],
            selectedTool=None,
            selectedWorkflow=selected_workflow_data,
        )

        # Same entry as chat, silent. workflow_id/title in the trigger context
        # routes the executor's final result to the completion notification.
        await call_agent_silent(
            request=request,
            conversation_id=conversation_id,
            user=user_data,
            user_time=user_time,
            trigger_context={
                **(context or {}),
                "workflow_id": workflow.id,
                "workflow_title": workflow.title,
                "workflow_notify_on_completion": workflow.notify_on_completion,
                "execution_mode": "background",
            },
        )

        return conversation_id

    except Exception as e:
        # Re-raise so caller marks execution as failed instead of fake-success.
        log.error(
            "workflow_chat_execution_failed",
            workflow_id=workflow.id,
            workflow_title=getattr(workflow, "title", None),
            user_id=user.get("user_id") if isinstance(user, dict) else None,
            error_type=type(e).__name__,
            error=str(e)[:500],
            outcome="agent_error",
            exc_info=True,
        )
        raise


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
    async with wide_task("regenerate_workflow_steps", workflow_id=workflow_id, user_id=user_id):
        log.info(
            f"Regenerating workflow steps: {workflow_id} for user {user_id}, reason: {regeneration_reason}"
        )

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
        log.info(result)
        return result


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
    async with wide_task("generate_workflow_steps", workflow_id=workflow_id, user_id=user_id):
        log.info(f"Generating workflow steps: {workflow_id} for user {user_id}")

        # Import here to avoid circular imports
        from app.services.workflow import WorkflowService

        # Generate steps using the service method
        await WorkflowService._generate_workflow_steps(workflow_id, user_id)

        # Fetch the updated workflow to get the generated steps
        updated_workflow = await WorkflowService.get_workflow(workflow_id, user_id)

        if updated_workflow:
            log.set(
                workflow=WorkflowContext(
                    id=workflow_id,
                    steps_count=len(updated_workflow.steps),
                )
            )

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
                log.set(websocket_broadcast_success=True)
                log.info(f"WebSocket event sent for todo workflow {workflow_id}")
            except Exception as ws_error:
                log.set(websocket_broadcast_success=False)
                log.warning(f"Failed to send WebSocket event: {ws_error}")

        result = f"Successfully generated steps for workflow {workflow_id}"
        log.info(result)
        return result
