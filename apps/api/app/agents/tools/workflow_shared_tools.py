"""Shared workflow tools used by both executor and workflow subagent."""

from typing import Annotated

from app.agents.tools.workflow_utils import (
    error_response,
    get_user_id,
    success_response,
)
from app.config.loggers import general_logger as logger
from app.decorators import with_rate_limiting
from app.services.workflow import WorkflowService
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


SUBAGENT_WORKFLOW_TOOLS = [
    search_triggers,
    list_workflows,
]


__all__ = [
    "SUBAGENT_WORKFLOW_TOOLS",
    "list_workflows",
    "search_triggers",
]
