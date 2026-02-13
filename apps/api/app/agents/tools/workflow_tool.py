"""
Workflow tools for the executor and workflow subagent.

Provides tools for:
- Searching for integration triggers (with config_fields embedded)
- Creating workflows (new or from_conversation mode)
- Managing workflows (list, get, execute)

The create_workflow tool invokes WorkflowSubagentRunner which handles
the subagent execution and returns structured JSON for streaming.

Direct creation: For simple, unambiguous workflows (manual/scheduled triggers),
we can create them directly without user confirmation. Integration triggers
always require confirmation due to config_fields (calendar_ids, channel_ids, etc).
"""

from typing import Annotated, Literal

from app.agents.tools.workflow_utils import (
    build_from_conversation_task,
    build_new_workflow_task,
    can_create_directly,
    create_workflow_directly,
    error_response,
    get_thread_id,
    get_user_id,
    get_user_time,
    get_user_timezone,
    success_response,
)
from app.config.loggers import general_logger as logger
from app.decorators import with_rate_limiting
from app.models.workflow_models import WorkflowExecutionRequest
from app.services.workflow import WorkflowService
from app.services.workflow.context_extractor import WorkflowContextExtractor
from app.services.workflow.subagent_output import parse_subagent_response
from app.services.workflow.trigger_search import TriggerSearchService
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


@tool
async def search_triggers(
    config: RunnableConfig,
    query: Annotated[str, "Describe when the workflow should trigger"],
    limit: Annotated[int, "Max number of results to return"] = 15,
) -> dict:
    """
    Search for integration triggers matching your description.

    Returns triggers with their configuration schema embedded (config_fields).
    Use this to find appropriate triggers before creating a workflow.

    Examples:
    - "when I receive an email" -> Gmail triggers
    - "when calendar event starts" -> Google Calendar triggers
    - "when someone sends a slack message" -> Slack triggers
    - "when a github issue is created" -> GitHub triggers

    Returns matching triggers with:
    - trigger_slug: Use this in create_workflow for integration triggers
    - trigger_name: Human-readable name
    - description: What the trigger does
    - is_connected: Whether user has this integration connected
    - config_fields: Configuration options for this trigger
    """
    try:
        user_id = get_user_id(config)

        results = await TriggerSearchService.search(
            query=query,
            user_id=user_id,
            limit=limit,
        )

        connected = [t for t in results if t.get("is_connected")]
        not_connected = [t for t in results if not t.get("is_connected")]

        return success_response(
            {
                "triggers": results,
                "connected_count": len(connected),
                "not_connected_count": len(not_connected),
            }
        )

    except Exception as e:
        logger.error(f"Error searching triggers: {e}")
        return error_response("search_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def create_workflow(
    config: RunnableConfig,
    user_request: Annotated[
        str,
        "The user's exact words describing what workflow they want. Pass verbatim.",
    ],
    mode: Annotated[
        Literal["new", "from_conversation"],
        "Mode: 'new' for creating from description, 'from_conversation' to save current session as workflow",
    ] = "new",
) -> dict:
    """
    Start workflow creation. Delegates to the workflow assistant.

    IMPORTANT: Pass the user's request EXACTLY as stated. Do not interpret,
    parse schedules, extract steps, or determine trigger types yourself.

    MODES:
    - mode="new": User wants to create a workflow from a description
    - mode="from_conversation": User wants to save current session as a reusable workflow

    The workflow assistant will handle everything:
    - Understanding user intent
    - Searching for triggers (scheduled, integration-based)
    - Asking clarifying questions when needed
    - Creating the workflow draft for user confirmation

    EXAMPLES:

    User: "Create a workflow that checks my email every morning"
    -> create_workflow(user_request="checks my email every morning", mode="new")

    User: "I want a workflow that notifies me on Slack when I get a GitHub PR"
    -> create_workflow(user_request="notifies me on Slack when I get a GitHub PR", mode="new")

    User: "Save this as a workflow"
    -> create_workflow(user_request="save this as a workflow", mode="from_conversation")

    User: "Turn what we just did into an automation that runs every Monday"
    -> create_workflow(user_request="runs every Monday", mode="from_conversation")

    DO NOT:
    - Parse cron expressions
    - Extract or guess step descriptions
    - Determine trigger types (manual/scheduled/integration)
    - Generate titles or descriptions
    - Fill in any other parameters

    Just pass user_request and mode. The workflow assistant handles everything else.
    """
    from app.services.workflow.workflow_subagent import WorkflowSubagentRunner

    writer = get_stream_writer()

    try:
        user_id = get_user_id(config)
        thread_id = get_thread_id(config) or ""
        user_name = config.get("configurable", {}).get("user_name")
        user_time = get_user_time(config)
        # Get user's timezone offset from configurable (e.g., +05:30)
        user_timezone = get_user_timezone(config)

        # Build task description based on mode
        if mode == "new":
            if not user_request or not user_request.strip():
                return error_response(
                    "missing_request",
                    "user_request is required. Pass the user's words describing what workflow they want.",
                )
            task_description = build_new_workflow_task(user_request.strip())

        elif mode == "from_conversation":
            if not thread_id:
                return error_response("no_context", "No conversation context available")

            context = await WorkflowContextExtractor.extract_from_thread(thread_id)

            if not context or not context.workflow_steps:
                return error_response(
                    "extraction_failed",
                    "Could not extract workflow steps from conversation. Try describing what you want instead.",
                )

            task_description = build_from_conversation_task(context, user_request)
        else:
            return error_response(
                "invalid_mode",
                f"Unknown mode: {mode}. Use 'new' or 'from_conversation'.",
            )

        logger.info(f"[create_workflow] Executing with mode={mode}")

        # Execute workflow subagent
        subagent_response = await WorkflowSubagentRunner.execute(
            task=task_description,
            user_id=user_id,
            thread_id=thread_id,
            user_name=user_name,
            user_time=user_time,
            stream_writer=writer,
        )

        # Parse the response
        result = parse_subagent_response(subagent_response)
        logger.info(f"[create_workflow] Parsed mode={result.mode}")

        if result.mode == "finalized" and result.draft:
            draft = result.draft

            # Check if we can create directly (simple, unambiguous workflows)
            if can_create_directly(draft):
                logger.info(
                    f"[create_workflow] Attempting direct creation for: {draft.title}"
                )

                # Try to create the workflow directly
                direct_result = await create_workflow_directly(
                    draft=draft,
                    user_id=user_id,
                    writer=writer,
                    user_timezone=user_timezone,
                )

                if direct_result is not None:
                    # Success - workflow was created directly
                    return direct_result

                # Fall through to draft card if direct creation failed
                logger.info(
                    "[create_workflow] Direct creation failed, falling back to draft"
                )

            # Stream workflow draft to frontend for user confirmation
            writer(result.draft.to_stream_payload())
            logger.info(f"[create_workflow] Streamed draft: {result.draft.title}")

            return success_response(
                {"status": "draft_sent", "mode": mode},
                "Workflow draft sent to user for confirmation.",
            )

        elif result.mode == "clarifying":
            # Subagent needs to ask the user a question.
            # Return the question text so the executor can relay it
            # through comms to the user.
            question = (
                result.message or "The workflow assistant needs more information."
            )
            return success_response(
                {
                    "status": "clarifying",
                    "mode": mode,
                    "question": question,
                },
                f"The workflow assistant needs clarification from the user: {question}",
            )

        elif result.mode == "parse_error":
            # Subagent returned something we couldn't parse.
            # Let the executor know so it can inform the user or retry.
            logger.warning(f"[create_workflow] Parse error: {result.parse_error}")
            return error_response(
                "parse_error",
                f"Failed to process the workflow assistant's response: {result.parse_error}. "
                "Please try again or rephrase your request.",
            )

        else:
            return success_response(
                {"status": "completed", "mode": mode},
                "Workflow creation completed.",
            )

    except Exception as e:
        logger.error(f"[create_workflow] Exception: {e}", exc_info=True)
        return error_response("subagent_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def list_workflows(config: RunnableConfig) -> dict:
    """List all workflows for the current user."""
    try:
        user_id = get_user_id(config)
        workflows = await WorkflowService.list_workflows(user_id)

        workflow_summaries = [
            {
                "id": w.id,
                "title": w.title,
                "description": w.description[:100] + "..."
                if len(w.description) > 100
                else w.description,
                "trigger_type": w.trigger_config.type,
                "activated": w.activated,
                "step_count": len(w.steps),
                "total_executions": w.total_executions,
            }
            for w in workflows
        ]

        writer = get_stream_writer()
        writer(
            {
                "workflow_list": {
                    "action": "list",
                    "workflows": workflow_summaries,
                    "total": len(workflows),
                }
            }
        )

        return success_response(
            {"workflows": workflow_summaries, "total": len(workflows)}
        )

    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return error_response("fetch_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def get_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to retrieve"],
) -> dict:
    """Get detailed information about a specific workflow."""
    try:
        user_id = get_user_id(config)
        workflow = await WorkflowService.get_workflow(workflow_id, user_id)
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        writer = get_stream_writer()
        writer({"workflow_data": {"action": "get", "workflow": workflow.model_dump()}})

        return success_response(workflow.model_dump())

    except Exception as e:
        logger.error(f"Error getting workflow {workflow_id}: {e}")
        return error_response("fetch_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def execute_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to execute"],
) -> dict:
    """Execute a workflow immediately (run now)."""
    try:
        user_id = get_user_id(config)
        result = await WorkflowService.execute_workflow(
            workflow_id, WorkflowExecutionRequest(), user_id
        )

        data = {
            "workflow_id": workflow_id,
            "execution_id": result.execution_id,
            "message": result.message,
        }

        writer = get_stream_writer()
        writer({"workflow_execution": {"action": "started", "execution": data}})

        return success_response(data)

    except Exception as e:
        logger.error(f"Error executing workflow {workflow_id}: {e}")
        return error_response("execution_failed", str(e))


# Tools for the executor - directly accessible
EXECUTOR_WORKFLOW_TOOLS = [
    search_triggers,
    create_workflow,
    list_workflows,
    get_workflow,
    execute_workflow,
]

# Tools for the workflow subagent - used by WorkflowSubagentRunner
SUBAGENT_WORKFLOW_TOOLS = [
    search_triggers,
    list_workflows,
]

# Default export for registry
tools = EXECUTOR_WORKFLOW_TOOLS
