"""
Workflow tools for the executor and workflow subagent.

Provides tools for:
- Searching for integration triggers (with config_fields embedded)
- Creating and editing workflows (via the workflow assistant)
- Managing workflows (list, get, execute, pause, resume)

The create_workflow and edit_workflow tools invoke WorkflowSubagentRunner which
handles the subagent execution and returns structured JSON for streaming.

Direct creation: For simple, unambiguous workflows (manual/scheduled triggers),
we can create them directly without user confirmation. Integration triggers
always require confirmation due to config_fields (calendar_ids, channel_ids, etc).
"""

from typing import Annotated, Any

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.agents.tools.workflow_shared_tools import (
    SUBAGENT_WORKFLOW_TOOLS as _SUBAGENT_WORKFLOW_TOOLS,
    list_workflows,
    search_triggers,
)
from app.constants.log_tags import LogTag
from app.decorators import with_rate_limiting
from app.models.agent_models import agent_configurable
from app.models.workflow_models import WorkflowExecutionRequest
from app.services.workflow.service import WorkflowService
from app.services.workflow.subagent_output import parse_subagent_response
from app.services.workflow.workflow_subagent import WorkflowSubagentRunner
from app.utils.timezone import home_timezone_from_config
from app.utils.workflow_utils import (
    apply_workflow_edit,
    build_edit_workflow_task,
    build_new_workflow_task,
    can_create_directly,
    create_workflow_directly,
    error_response,
    get_thread_id,
    get_user_id,
    success_response,
)
from shared.py.wide_events import log

SUBAGENT_WORKFLOW_TOOLS = _SUBAGENT_WORKFLOW_TOOLS


@tool
@with_rate_limiting("workflow_operations")
async def create_workflow(
    config: RunnableConfig,
    user_request: Annotated[
        str,
        "The user's exact words describing what workflow they want. Pass verbatim.",
    ],
) -> dict[str, Any]:
    """
    Create a workflow from the user's description. Delegates to the workflow assistant.

    IMPORTANT: Pass the user's request EXACTLY as stated. Do not interpret,
    parse schedules, extract steps, or determine trigger types yourself.

    The workflow assistant handles everything:
    - Understanding user intent
    - Searching for triggers (scheduled, integration-based)
    - Asking clarifying questions when needed
    - Creating the workflow draft for user confirmation

    EXAMPLES:

    User: "Create a workflow that checks my email every morning"
    -> create_workflow(user_request="checks my email every morning")

    User: "I want a workflow that notifies me on Slack when I get a GitHub PR"
    -> create_workflow(user_request="notifies me on Slack when I get a GitHub PR")

    DO NOT:
    - Parse cron expressions
    - Extract or guess step descriptions
    - Determine trigger types (manual/scheduled/integration)
    - Generate titles or descriptions
    - Fill in any other parameters

    Just pass user_request. The workflow assistant handles everything else. To
    change an existing workflow, use edit_workflow instead.
    """
    log.set(tool={"name": "create_workflow", "action": "create"})
    writer = get_stream_writer()

    try:
        user_id = get_user_id(config)
        thread_id = get_thread_id(config) or ""
        user_name: str | None = agent_configurable(config).get("user_name")
        # Home timezone (IANA, e.g. Asia/Kolkata) for the new workflow's schedule
        # default and the subagent's "now".
        user_timezone = home_timezone_from_config(config).value

        if not user_request or not user_request.strip():
            return error_response(
                "missing_request",
                "user_request is required. Pass the user's words describing what workflow they want.",
            )
        task_description = build_new_workflow_task(user_request.strip())

        log.info(f"{LogTag.TOOL} create_workflow: Executing")

        # Execute workflow subagent
        subagent_response = await WorkflowSubagentRunner.execute(
            task=task_description,
            user_id=user_id,
            thread_id=thread_id,
            user_name=user_name,
            user_timezone=user_timezone,
            stream_writer=writer,
            base_configurable=agent_configurable(config),
        )

        # Parse the response
        result = parse_subagent_response(subagent_response)
        log.info(f"{LogTag.TOOL} create_workflow: parsed mode", mode=result.mode)

        if result.mode == "finalized" and result.draft:
            draft = result.draft

            # Check if we can create directly (simple, unambiguous workflows)
            if can_create_directly(draft):
                log.info(
                    f"{LogTag.TOOL} create_workflow: attempting direct creation",
                    draft_title=draft.title,
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
                log.info(
                    f"{LogTag.TOOL} create_workflow: Direct creation failed, falling back to draft"
                )

            # Stream workflow draft to frontend for user confirmation
            writer(result.draft.to_stream_payload())
            log.info(
                f"{LogTag.TOOL} create_workflow: streamed draft", draft_title=result.draft.title
            )

            return success_response(
                {"status": "draft_sent"},
                "Workflow draft sent to user for confirmation.",
            )

        if result.mode == "clarifying":
            # Subagent needs to ask the user a question.
            # Return the question text so the executor can relay it
            # through comms to the user.
            question = result.message or "The workflow assistant needs more information."
            return success_response(
                {
                    "status": "clarifying",
                    "question": question,
                },
                f"The workflow assistant needs clarification from the user: {question}",
            )

        if result.mode == "parse_error":
            # Subagent returned something we couldn't parse.
            # Let the executor know so it can inform the user or retry.
            log.warning(
                f"{LogTag.TOOL} create_workflow: parse error", parse_error=result.parse_error
            )
            return error_response(
                "parse_error",
                f"Failed to process the workflow assistant's response: {result.parse_error}. "
                "Please try again or rephrase your request.",
            )

        return success_response(
            {"status": "completed"},
            "Workflow creation completed.",
        )

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} create_workflow: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("subagent_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def get_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to retrieve"],
) -> dict[str, Any]:
    """Get detailed information about a specific workflow."""
    try:
        log.set(tool={"name": "get_workflow", "action": "get"})
        user_id = get_user_id(config)
        workflow = await WorkflowService.get_workflow(workflow_id, user_id)
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        writer = get_stream_writer()
        writer({"workflow_data": {"action": "get", "workflow": workflow.model_dump()}})

        return success_response(workflow.model_dump())

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error getting workflow",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
        )
        return error_response("fetch_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def execute_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to execute"],
) -> dict[str, Any]:
    """Execute a workflow immediately (run now)."""
    try:
        log.set(tool={"name": "execute_workflow", "action": "execute"})
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
        log.error(
            f"{LogTag.TOOL} Error executing workflow",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
        )
        return error_response("execution_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def pause_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to pause"],
) -> dict[str, Any]:
    """Pause (deactivate) a workflow so its schedule and integration triggers stop firing.

    Reversible with resume_workflow. Use list_workflows or get_workflow first to
    find the workflow_id. Returns not_found if the workflow does not belong to the
    current user.
    """
    try:
        log.set(tool={"name": "pause_workflow", "action": "pause"})
        user_id = get_user_id(config)
        workflow = await WorkflowService.deactivate_workflow(workflow_id, user_id)
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        writer = get_stream_writer()
        writer({"workflow_data": {"action": "paused", "workflow": workflow.model_dump()}})

        return success_response(
            {"workflow_id": workflow.id, "title": workflow.title, "activated": workflow.activated}
        )

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error pausing workflow",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
        )
        return error_response("pause_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def resume_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to resume"],
) -> dict[str, Any]:
    """Resume (reactivate) a paused workflow so its trigger fires again.

    Recomputes the next scheduled run from the cron. For integration triggers the
    underlying integration must be connected, or this returns an error explaining
    what to connect. Returns not_found if the workflow does not belong to the
    current user.
    """
    try:
        log.set(tool={"name": "resume_workflow", "action": "resume"})
        user_id = get_user_id(config)
        user_timezone = home_timezone_from_config(config).value
        workflow = await WorkflowService.activate_workflow(
            workflow_id, user_id, user_timezone=user_timezone
        )
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        writer = get_stream_writer()
        writer({"workflow_data": {"action": "resumed", "workflow": workflow.model_dump()}})

        return success_response(
            {"workflow_id": workflow.id, "title": workflow.title, "activated": workflow.activated}
        )

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} Error resuming workflow",
            workflow_id=workflow_id,
            error_type=type(e).__name__,
        )
        return error_response("resume_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
async def edit_workflow(
    config: RunnableConfig,
    workflow_id: Annotated[str, "The ID of the workflow to edit"],
    user_request: Annotated[
        str, "The user's change request in their words. Pass verbatim — do not parse it yourself."
    ],
) -> dict[str, Any]:
    """Edit an existing workflow's behavior, schedule, or trigger.

    Delegates to the workflow assistant: pass the user's change request EXACTLY as
    stated. Use list_workflows or get_workflow first to resolve the workflow_id.
    Returns 'updated' on success, 'clarifying' if the assistant needs more info,
    or not_found if the workflow does not belong to the current user.

    Changing an integration trigger's config (which channels/repos/calendars) is
    done by the user in the app's workflow editor, not here.
    """
    log.set(tool={"name": "edit_workflow", "action": "edit"})
    writer = get_stream_writer()

    try:
        user_id = get_user_id(config)
        thread_id = get_thread_id(config) or ""
        user_name: str | None = agent_configurable(config).get("user_name")
        user_timezone = home_timezone_from_config(config).value

        if not user_request or not user_request.strip():
            return error_response(
                "missing_request",
                "user_request is required — pass the user's change in their words.",
            )

        workflow = await WorkflowService.get_workflow(workflow_id, user_id)
        if not workflow:
            return error_response("not_found", f"Workflow {workflow_id} not found")

        task_description = build_edit_workflow_task(workflow, user_request.strip())
        subagent_response = await WorkflowSubagentRunner.execute(
            task=task_description,
            user_id=user_id,
            thread_id=thread_id,
            user_name=user_name,
            user_timezone=user_timezone,
            stream_writer=writer,
        )

        result = parse_subagent_response(subagent_response)
        log.info(f"{LogTag.TOOL} edit_workflow: parsed mode", mode=result.mode)

        if result.mode == "finalized" and result.draft:
            return await apply_workflow_edit(
                draft=result.draft,
                workflow=workflow,
                user_id=user_id,
                writer=writer,
                user_timezone=user_timezone,
            )

        if result.mode == "clarifying":
            question = result.message or "The workflow assistant needs more information."
            return success_response(
                {"status": "clarifying", "question": question},
                f"The workflow assistant needs clarification from the user: {question}",
            )

        if result.mode == "parse_error":
            log.warning(f"{LogTag.TOOL} edit_workflow: parse error", parse_error=result.parse_error)
            return error_response(
                "parse_error",
                f"Failed to process the workflow assistant's response: {result.parse_error}. "
                "Please try again or rephrase the change.",
            )

        return success_response({"status": "completed"}, "Workflow edit completed.")

    except Exception as e:
        log.error(
            f"{LogTag.TOOL} edit_workflow: exception", error_type=type(e).__name__, exc_info=True
        )
        return error_response("edit_failed", str(e))


# Tools for the executor - directly accessible
EXECUTOR_WORKFLOW_TOOLS = [
    search_triggers,
    create_workflow,
    list_workflows,
    get_workflow,
    execute_workflow,
    pause_workflow,
    resume_workflow,
    edit_workflow,
]

# Default export for registry
tools = EXECUTOR_WORKFLOW_TOOLS
