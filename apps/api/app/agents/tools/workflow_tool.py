"""
Workflow tools for the executor and workflow subagent.

Provides tools for:
- Searching for integration triggers (with config_fields embedded)
- Creating workflows (new or from_conversation mode)
- Managing workflows (list, get, execute)

The workflow subagent uses structured JSON output which is parsed and streamed to frontend.
"""

from typing import Annotated, Any, Literal

from app.agents.prompts.workflow_prompts import (
    WORKFLOW_CREATION_FROM_CONVERSATION_TASK_TEMPLATE,
    WORKFLOW_CREATION_HINTS_TEMPLATE,
    WORKFLOW_CREATION_NEW_TASK_TEMPLATE,
    WORKFLOW_CREATION_RETRY_TEMPLATE,
    WORKFLOW_CREATION_USER_REQUEST_TEMPLATE,
)
from app.config.loggers import general_logger as logger
from app.decorators import with_rate_limiting
from app.models.workflow_models import (
    WorkflowExecutionRequest,
)
from app.services.workflow import WorkflowService
from app.services.workflow.context_extractor import WorkflowContextExtractor
from app.services.workflow.subagent_output import parse_subagent_response
from app.services.workflow.trigger_search import TriggerSearchService
from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer


def error_response(error_code: str, message: str) -> dict:
    """Return a standardized error response."""
    return {"success": False, "error": error_code, "message": message}


def success_response(data: Any, message: str | None = None) -> dict:
    """Return a standardized success response."""
    response = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response


def get_user_id(config: RunnableConfig) -> str:
    """Extract user_id from config. Raises error if missing."""
    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        raise ValueError("User authentication required")
    return user_id


def get_thread_id(config: RunnableConfig) -> str | None:
    """Extract thread_id from config."""
    return config.get("configurable", {}).get("thread_id")


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
    - config_fields: Configuration options for this trigger (IDs, filters, etc.)
    """
    try:
        user_id = get_user_id(config)

        results = await TriggerSearchService.search(
            query=query,
            user_id=user_id,
            limit=limit,
        )

        # Format for display
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
    workflow_request: Annotated[
        str | None,
        "Natural language description of the workflow. Required for type='new'.",
    ] = None,
    type: Annotated[
        Literal["new", "from_conversation"],
        "Type of workflow creation",
    ] = "new",
    # Optional hints - passed to subagent as suggestions
    title: Annotated[str | None, "Suggested workflow title"] = None,
    description: Annotated[str | None, "Suggested workflow description"] = None,
    trigger_type: Annotated[
        Literal["manual", "scheduled", "integration"] | None,
        "Suggested trigger type",
    ] = None,
    trigger_slug: Annotated[str | None, "For integration triggers"] = None,
    cron_expression: Annotated[str | None, "For scheduled triggers"] = None,
    steps: Annotated[list[str] | None, "Suggested step descriptions"] = None,
) -> dict:
    """
    Create a workflow. Delegates to the specialized workflow subagent for refinement.

    WHEN TO USE:
    - User wants to create a new workflow: type="new" with workflow_request
    - User wants to save current conversation as workflow: type="from_conversation"

    PARAMETERS:

    type="new" (create from description):
      - workflow_request: REQUIRED - describe what workflow to create
        Example: "Check my emails every morning and summarize them"
      - Other parameters are optional hints

    type="from_conversation" (save session as workflow):
      - workflow_request: Optional - additional context from user
      - Extracts steps from current conversation automatically
      - Other parameters are optional hints

    Optional hint parameters (title, trigger_type, etc.) are passed to the workflow
    subagent as suggestions. The subagent may refine or override them based on user input.

    EXAMPLES:

    Create a scheduled workflow:
      create_workflow(
        type="new",
        workflow_request="Check my Gmail every morning at 9am and summarize unread emails"
      )

    Create with hints:
      create_workflow(
        type="new",
        workflow_request="Post to Slack when I get important emails",
        trigger_type="integration"
      )

    Save conversation as workflow:
      create_workflow(type="from_conversation")

    Save with user's trigger preference:
      create_workflow(
        type="from_conversation",
        workflow_request="make it run every Monday"
      )
    """
    from pydantic import ValidationError

    writer = get_stream_writer()
    user_id = get_user_id(config)

    # Validate parameters
    if type == "new":
        if not workflow_request or not workflow_request.strip():
            return error_response(
                "missing_request",
                "workflow_request is required for type='new'. Describe what workflow to create.",
            )
        task_description = _build_new_workflow_task(
            workflow_request=workflow_request.strip(),
            title=title,
            description=description,
            trigger_type=trigger_type,
            trigger_slug=trigger_slug,
            cron_expression=cron_expression,
            steps=steps,
        )
    elif type == "from_conversation":
        thread_id = get_thread_id(config)
        if not thread_id:
            return error_response("no_context", "No conversation context available")

        try:
            context = await WorkflowContextExtractor.extract_from_thread(
                thread_id, user_id
            )

            if not context or not context.workflow_steps:
                return error_response(
                    "extraction_failed",
                    "Could not extract workflow steps from conversation",
                )

            task_description = _build_from_conversation_task(
                context=context,
                workflow_request=workflow_request,
                title=title,
                description=description,
                trigger_type=trigger_type,
                trigger_slug=trigger_slug,
                cron_expression=cron_expression,
                steps=steps,
            )

        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            return error_response("validation_failed", str(e))
        except Exception as e:
            logger.error(f"Error extracting context: {e}")
            return error_response("extraction_failed", str(e))
    else:
        return error_response("invalid_type", f"Unknown type: {type}")

    # Hand off to workflow subagent with retry logic
    try:
        from app.agents.core.subagents.handoff_tools import handoff

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            if attempt == 0:
                current_task = task_description
            else:
                # Retry with error correction message from template
                current_task = WORKFLOW_CREATION_RETRY_TEMPLATE.format(
                    error=last_error,
                    original_task=task_description,
                )

            handoff_result = await handoff.ainvoke(
                {
                    "subagent_id": "workflows",
                    "task": current_task,
                },
                config,
            )

            # Parse the subagent response
            parsed_output = parse_subagent_response(handoff_result)

            if parsed_output.mode == "parse_error":
                last_error = parsed_output.parse_error
                logger.warning(
                    f"Workflow subagent JSON parse error (attempt {attempt + 1}): {last_error}"
                )
                if attempt < max_retries:
                    continue
                else:
                    # Max retries reached
                    return success_response(
                        {
                            "status": "clarifying",
                            "type": type,
                            "parse_error": last_error,
                        },
                        "Workflow assistant encountered a formatting issue. Please try again.",
                    )

            elif parsed_output.mode == "finalized" and parsed_output.draft:
                # Subagent finalized the workflow - stream the draft
                writer(parsed_output.draft.to_stream_payload())

                return success_response(
                    {
                        "status": "draft_sent",
                        "type": type,
                        "finalized": True,
                        "title": parsed_output.draft.title,
                        "direct_create": parsed_output.draft.direct_create,
                    },
                    "Workflow draft sent to user for confirmation in the editor.",
                )

            else:
                # Subagent is asking clarifying questions
                # The handoff already streamed the response to the user
                return success_response(
                    {
                        "status": "clarifying",
                        "type": type,
                    },
                    "Workflow assistant is helping the user refine the workflow.",
                )

        # Should not reach here
        return success_response(
            {"status": "clarifying", "type": type},
            "Workflow assistant is helping the user refine the workflow.",
        )

    except Exception as e:
        logger.error(f"Error in create_workflow: {e}")
        return error_response("handoff_failed", str(e))


def _build_new_workflow_task(
    workflow_request: str,
    title: str | None = None,
    description: str | None = None,
    trigger_type: str | None = None,
    trigger_slug: str | None = None,
    cron_expression: str | None = None,
    steps: list[str] | None = None,
) -> str:
    """Build task description for a new workflow from natural language request."""
    # Build hints section if any hints provided
    hints = _build_hints_list(
        title=title,
        description=description,
        trigger_type=trigger_type,
        trigger_slug=trigger_slug,
        cron_expression=cron_expression,
        steps=steps,
    )

    hints_section = ""
    if hints:
        hints_section = WORKFLOW_CREATION_HINTS_TEMPLATE.format(hints="\n".join(hints))

    return WORKFLOW_CREATION_NEW_TASK_TEMPLATE.format(
        workflow_request=workflow_request,
        hints_section=hints_section,
    )


def _build_from_conversation_task(
    context,
    workflow_request: str | None = None,
    title: str | None = None,
    description: str | None = None,
    trigger_type: str | None = None,
    trigger_slug: str | None = None,
    cron_expression: str | None = None,
    steps: list[str] | None = None,
) -> str:
    """Build task description for workflow extracted from conversation."""
    # Format steps from context
    steps_text = "\n".join(
        f"- {step.get('title', step)}" if isinstance(step, dict) else f"- {step}"
        for step in context.workflow_steps
    )

    # Build user request section
    user_request_section = ""
    if workflow_request:
        user_request_section = WORKFLOW_CREATION_USER_REQUEST_TEMPLATE.format(
            workflow_request=workflow_request
        )

    # Build hints section
    hints = _build_hints_list(
        title=title,
        description=description,
        trigger_type=trigger_type,
        trigger_slug=trigger_slug,
        cron_expression=cron_expression,
        steps=steps,
        is_override=True,
    )

    hints_section = ""
    if hints:
        hints_section = WORKFLOW_CREATION_HINTS_TEMPLATE.format(hints="\n".join(hints))

    return WORKFLOW_CREATION_FROM_CONVERSATION_TASK_TEMPLATE.format(
        suggested_title=context.suggested_title,
        summary=context.summary,
        steps_text=steps_text,
        integrations_used=", ".join(context.integrations_used)
        if context.integrations_used
        else "None",
        user_request_section=user_request_section,
        hints_section=hints_section,
    )


def _build_hints_list(
    title: str | None = None,
    description: str | None = None,
    trigger_type: str | None = None,
    trigger_slug: str | None = None,
    cron_expression: str | None = None,
    steps: list[str] | None = None,
    is_override: bool = False,
) -> list[str]:
    """Build list of hint strings from optional parameters."""
    hints = []
    prefix = " override" if is_override else ""

    if title:
        hints.append(f"- Suggested title{prefix}: {title}")
    if description:
        hints.append(f"- Suggested description: {description}")
    if trigger_type:
        hints.append(f"- Suggested trigger type: {trigger_type}")
    if trigger_slug:
        hints.append(f"- Suggested trigger slug: {trigger_slug}")
    if cron_expression:
        hints.append(f"- Suggested schedule: {cron_expression}")
    if steps:
        hints.append(f"- Suggested steps{prefix}: {', '.join(steps)}")

    return hints


@tool
async def finalize_workflow(
    config: RunnableConfig,
    title: Annotated[str, "Workflow title"],
    description: Annotated[str, "Workflow description"],
    trigger_type: Annotated[
        Literal["manual", "scheduled", "integration"],
        "Trigger type: manual, scheduled, or integration",
    ] = "manual",
    trigger_slug: Annotated[
        str | None,
        "For integration triggers: the trigger_slug",
    ] = None,
    cron_expression: Annotated[
        str | None,
        "For scheduled triggers: cron expression",
    ] = None,
    steps: Annotated[
        list[str] | None,
        "List of step descriptions in natural language",
    ] = None,
) -> dict:
    """
    Finalize workflow draft and send to user for confirmation.

    Use this after discussing the workflow details with the user.
    This writes the draft to the stream, which opens the workflow editor
    in the frontend for final confirmation.

    The user will be able to:
    - Review and edit the title/description
    - Fill in trigger configuration IDs (calendar IDs, channel IDs, etc.)
    - Confirm to create the workflow
    """
    writer = get_stream_writer()
    _ = get_user_id(config)

    # Validate
    if trigger_type == "scheduled" and not cron_expression:
        return error_response(
            "missing_cron", "cron_expression required for scheduled trigger"
        )
    if trigger_type == "integration" and not trigger_slug:
        return error_response(
            "missing_trigger", "trigger_slug required for integration trigger"
        )

    # Write draft to stream
    writer(
        {
            "workflow_draft": {
                "suggested_title": title,
                "suggested_description": description,
                "trigger_type": trigger_type,
                "trigger_slug": trigger_slug,
                "cron_expression": cron_expression,
                "steps": steps or [],
            }
        }
    )

    return success_response(
        {"status": "draft_sent"},
        "Workflow draft sent to user. They can now review and confirm in the editor.",
    )


@tool
@with_rate_limiting("workflow_operations")
async def list_workflows(
    config: RunnableConfig,
) -> dict:
    """List all workflows for the current user."""
    try:
        user_id = get_user_id(config)
        workflows = await WorkflowService.list_workflows(user_id)

        # Return summarized view
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
            {
                "workflows": workflow_summaries,
                "total": len(workflows),
            }
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


# Tools for the executor (main agent)
EXECUTOR_WORKFLOW_TOOLS = [
    search_triggers,
    create_workflow,
    list_workflows,
    get_workflow,
    execute_workflow,
]

# Tools for the workflow subagent
# Note: finalize_workflow removed - subagent now uses structured JSON output
# which is parsed by create_workflow and streamed to frontend
SUBAGENT_WORKFLOW_TOOLS = [
    search_triggers,
    list_workflows,
]

# Legacy export for backwards compatibility
tools = EXECUTOR_WORKFLOW_TOOLS
