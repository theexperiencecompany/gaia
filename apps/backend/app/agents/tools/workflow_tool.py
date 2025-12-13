"""
Clean workflow tools for GAIA workflow system.
Includes both workflow generation and chat interface tools.
"""

from functools import wraps
from typing import Annotated, Any, Optional, Literal

from langchain_core.runnables.config import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.config.loggers import general_logger as logger
from app.decorators import with_rate_limiting
from app.models.workflow_models import (
    CreateWorkflowRequest,
    TriggerConfig,
    TriggerType,
)
from app.services.workflow import WorkflowService


# Helper functions
def error_response(error_code: str, message: str) -> dict:
    return {"success": False, "error": error_code, "message": message}


def success_response(data: Any, message: Optional[str] = None) -> dict:
    response = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response


def require_user_auth(func):
    @wraps(func)
    async def wrapper(config: RunnableConfig, *args, **kwargs):
        user_id = config.get("configurable", {}).get("user_id")
        if not user_id:
            return error_response("auth_required", "User authentication required")
        return await func(config, user_id, *args, **kwargs)

    return wrapper


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def create_workflow_tool(
    config: RunnableConfig,
    user_id: str,
    title: Annotated[str, "The title of the workflow"],
    description: Annotated[str, "Description of what the workflow should accomplish"],
    trigger_type: Annotated[
        Literal["manual", "schedule", "email", "calendar"], "Type of trigger"
    ] = "manual",
    cron_expression: Annotated[
        Optional[str], "Cron expression for scheduled workflows"
    ] = None,
    generate_immediately: Annotated[
        bool, "Whether to generate steps immediately"
    ] = True,
) -> dict:
    """Create a new workflow from a title and description."""
    try:
        trigger_config = TriggerConfig(type=TriggerType(trigger_type), enabled=True)
        if trigger_type == "schedule" and cron_expression:
            trigger_config.cron_expression = cron_expression

        request = CreateWorkflowRequest(
            title=title,
            description=description,
            trigger_config=trigger_config,
            generate_immediately=generate_immediately,
        )

        workflow = await WorkflowService.create_workflow(request, user_id)

        writer = get_stream_writer()
        writer(
            {"workflow_data": {"action": "created", "workflow": workflow.model_dump()}}
        )

        return success_response(workflow.model_dump(), "Workflow created successfully")

    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        return error_response("creation_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def get_workflow_tool(
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


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def list_workflows_tool(config: RunnableConfig, user_id: str) -> dict:
    """List all workflows for the current user."""
    try:
        workflows = await WorkflowService.list_workflows(user_id)

        writer = get_stream_writer()
        writer(
            {
                "workflow_list": {
                    "action": "list",
                    "workflows": [workflow.model_dump() for workflow in workflows],
                    "total": len(workflows),
                }
            }
        )

        return success_response(
            {
                "workflows": [workflow.model_dump() for workflow in workflows],
                "total": len(workflows),
            }
        )

    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return error_response("fetch_failed", str(e))


@tool
@with_rate_limiting("workflow_operations")
@require_user_auth
async def execute_workflow_tool(
    config: RunnableConfig,
    user_id: str,
    workflow_id: Annotated[str, "The ID of the workflow to execute"],
) -> dict:
    """Execute a workflow immediately (run now)."""
    try:
        from app.models.workflow_models import WorkflowExecutionRequest

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


tools = [
    create_workflow_tool,
    get_workflow_tool,
    list_workflows_tool,
    execute_workflow_tool,
]
