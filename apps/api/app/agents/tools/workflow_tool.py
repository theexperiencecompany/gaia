"""
Workflow tools for the executor and workflow subagent.

Provides tools for:
- Searching for integration triggers (with config_fields embedded)
- Creating workflows (custom mode or from session mode with structured output)
- Managing workflows (list, get, execute)

The workflow subagent uses structured JSON output instead of tool calls to finalize workflows.
The create_workflow tool parses the subagent response and streams the draft to the frontend.
"""

from functools import wraps
from typing import Annotated, Any, Literal

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


def get_user_id(config: RunnableConfig) -> str | None:
    """Extract user_id from config."""
    return config.get("configurable", {}).get("user_id")


def get_thread_id(config: RunnableConfig) -> str | None:
    """Extract thread_id from config."""
    return config.get("configurable", {}).get("thread_id")


def require_user_auth(func):
    """Decorator to require user authentication."""

    @wraps(func)
    async def wrapper(config: RunnableConfig, *args, **kwargs):
        user_id = get_user_id(config)
        if not user_id:
            return error_response("auth_required", "User authentication required")
        return await func(config, user_id, *args, **kwargs)

    return wrapper


# =============================================================================
# TOOL 1: search_triggers
# =============================================================================


@tool
@require_user_auth
async def search_triggers(
    config: RunnableConfig,
    user_id: str,
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


# =============================================================================
# TOOL 2: create_workflow (executor tool)
# =============================================================================


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def create_workflow(
    config: RunnableConfig,
    user_id: str,
    mode: Annotated[
        Literal["custom", "from_session"],
        "Mode: 'custom' to provide all details, 'from_session' to extract from conversation",
    ],
    # For custom mode - all details provided by executor
    title: Annotated[str | None, "Workflow title"] = None,
    description: Annotated[str | None, "Workflow description"] = None,
    trigger_type: Annotated[
        Literal["manual", "scheduled", "integration"],
        "When workflow runs: manual, scheduled (time-based), or integration (event-based)",
    ] = "manual",
    trigger_slug: Annotated[
        str | None,
        "For integration triggers: the trigger_slug from search_triggers",
    ] = None,
    cron_expression: Annotated[
        str | None,
        "For scheduled triggers: cron expression (e.g., '0 9 * * *' for daily at 9am)",
    ] = None,
    steps: Annotated[
        list[str] | None,
        "List of step descriptions in natural language",
    ] = None,
) -> dict:
    """
    Create a workflow draft for user confirmation.

    Two modes:
    - custom: You provide all workflow details. Draft is sent to frontend for user to confirm.
    - from_session: Extracts workflow from conversation context, then hands off to
                   workflow subagent for refinement with the user.

    For custom mode:
    - Provide title, description, trigger_type, and optionally steps
    - If trigger_type="scheduled", provide cron_expression
    - If trigger_type="integration", provide trigger_slug from search_triggers

    The draft is written to the stream and the frontend opens the workflow editor
    for the user to review, fill in trigger config IDs, and confirm.
    """
    writer = get_stream_writer()

    if mode == "custom":
        # Validate required fields for custom mode
        if not title:
            return error_response("missing_title", "Title required for custom mode")
        if not description:
            return error_response(
                "missing_description", "Description required for custom mode"
            )
        if trigger_type == "scheduled" and not cron_expression:
            return error_response(
                "missing_cron", "cron_expression required for scheduled trigger"
            )
        if trigger_type == "integration" and not trigger_slug:
            return error_response(
                "missing_trigger",
                "trigger_slug required for integration trigger. Use search_triggers first.",
            )

        # Write draft to stream - frontend will open WorkflowModal
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
            {"status": "draft_sent", "mode": "custom"},
            "Workflow draft sent to user for confirmation in the editor.",
        )

    elif mode == "from_session":
        # Extract context from current conversation
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

            # Import and call handoff tool directly
            from app.agents.core.subagents.handoff_tools import handoff

            # Format steps as readable list
            steps_text = "\n".join(
                f"- {step.get('title', step)}"
                if isinstance(step, dict)
                else f"- {step}"
                for step in context.workflow_steps
            )

            task_description = f"""Create a workflow from the following conversation context:

Title suggestion: {context.suggested_title}
Summary: {context.summary}

Steps identified:
{steps_text}

Integrations used: {", ".join(context.integrations_used) if context.integrations_used else "None"}

Help the user finalize this workflow by:
1. Confirming or refining the title and description
2. Determining the trigger type (manual, scheduled, or integration-based)
3. If integration trigger needed, use search_triggers to find appropriate triggers
4. Once confirmed, output a finalized JSON block with the workflow details

Remember to ALWAYS include a JSON block in your response (either clarifying or finalized type).
"""

            # Call handoff and get the subagent's response
            # Retry up to 2 times if JSON parsing fails
            max_retries = 2
            last_error = None

            for attempt in range(max_retries + 1):
                if attempt == 0:
                    current_task = task_description
                else:
                    # Retry with error correction message
                    current_task = f"""Your previous response had an invalid JSON output. Error: {last_error}

Please respond again with a VALID JSON block. Required format:

For clarifying questions:
```json
{{"type": "clarifying", "message": "Your question here"}}
```

For finalized workflow:
```json
{{
    "type": "finalized",
    "title": "Workflow Title",
    "description": "What this workflow does",
    "trigger_type": "manual|scheduled|integration",
    "cron_expression": "0 9 * * *",
    "trigger_slug": "TRIGGER_SLUG_HERE",
    "steps": ["Step 1", "Step 2"]
}}
```

Note: cron_expression is required for scheduled triggers. trigger_slug is required for integration triggers.

Original context:
{task_description}
"""

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
                    # JSON was found but invalid - retry
                    last_error = parsed_output.parse_error
                    logger.warning(
                        f"Workflow subagent JSON parse error (attempt {attempt + 1}): {last_error}"
                    )
                    if attempt < max_retries:
                        continue
                    else:
                        # Max retries reached - treat as clarifying
                        return success_response(
                            {
                                "status": "clarifying",
                                "mode": "from_session",
                                "context_summary": context.summary,
                                "parse_error": last_error,
                            },
                            "Workflow assistant encountered a formatting issue. Please try again.",
                        )

                elif parsed_output.mode == "finalized" and parsed_output.draft:
                    # Subagent finalized the workflow - stream the draft directly
                    writer(parsed_output.draft.to_stream_payload())

                    return success_response(
                        {
                            "status": "draft_sent",
                            "mode": "from_session",
                            "finalized": True,
                            "title": parsed_output.draft.title,
                        },
                        "Workflow draft sent to user for confirmation in the editor.",
                    )

                else:
                    # Subagent is still asking clarifying questions
                    # The handoff already streamed the response to the user
                    return success_response(
                        {
                            "status": "clarifying",
                            "mode": "from_session",
                            "context_summary": context.summary,
                        },
                        "Workflow assistant is helping the user refine the workflow.",
                    )

            # Should not reach here, but just in case
            return success_response(
                {
                    "status": "clarifying",
                    "mode": "from_session",
                    "context_summary": context.summary,
                },
                "Workflow assistant is helping the user refine the workflow.",
            )

        except Exception as e:
            logger.error(f"Error in from_session mode: {e}")
            return error_response("handoff_failed", str(e))

    return error_response("invalid_mode", f"Unknown mode: {mode}")


# =============================================================================
# TOOL 3: finalize_workflow (subagent only)
# =============================================================================


@tool
@require_user_auth
async def finalize_workflow(
    config: RunnableConfig,
    user_id: str,
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


# =============================================================================
# TOOL 4: list_workflows
# =============================================================================


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def list_workflows(
    config: RunnableConfig,
    user_id: str,
) -> dict:
    """List all workflows for the current user."""
    try:
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


# =============================================================================
# TOOL 5: get_workflow
# =============================================================================


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def get_workflow(
    config: RunnableConfig,
    user_id: str,
    workflow_id: Annotated[str, "The ID of the workflow to retrieve"],
) -> dict:
    """Get detailed information about a specific workflow."""
    try:
        workflow = await WorkflowService.get_workflow(workflow_id, user_id)
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        writer = get_stream_writer()
        writer({"workflow_data": {"action": "get", "workflow": workflow.model_dump()}})

        return success_response(workflow.model_dump())

    except Exception as e:
        logger.error(f"Error getting workflow {workflow_id}: {e}")
        return error_response("fetch_failed", str(e))


# =============================================================================
# TOOL 6: execute_workflow
# =============================================================================


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def execute_workflow(
    config: RunnableConfig,
    user_id: str,
    workflow_id: Annotated[str, "The ID of the workflow to execute"],
) -> dict:
    """Execute a workflow immediately (run now)."""
    try:
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


# =============================================================================
# EXPORTS
# =============================================================================

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
