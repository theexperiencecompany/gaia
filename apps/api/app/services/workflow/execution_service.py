"""
Workflow Execution Service.

Service functions for tracking workflow execution history.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.config.loggers import general_logger as logger
from app.db.mongodb.collections import workflow_executions_collection
from app.models.workflow_execution_models import (
    WorkflowExecution,
    WorkflowExecutionsResponse,
)


async def create_execution(
    workflow_id: str,
    user_id: str,
    trigger_type: str = "manual",
    conversation_id: Optional[str] = None,
) -> WorkflowExecution:
    """
    Create a new workflow execution record with status 'running'.

    Args:
        workflow_id: ID of the workflow being executed
        user_id: ID of the user who owns the workflow
        trigger_type: What triggered the execution (manual, schedule, integration name)
        conversation_id: Optional conversation ID where execution messages are stored

    Returns:
        The created WorkflowExecution record
    """
    execution = WorkflowExecution(
        execution_id=f"exec_{uuid4().hex[:12]}",
        workflow_id=workflow_id,
        user_id=user_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        trigger_type=trigger_type,
        conversation_id=conversation_id,
    )

    await workflow_executions_collection.insert_one(execution.model_dump())
    logger.info(
        f"Created execution {execution.execution_id} for workflow {workflow_id}"
    )

    return execution


async def complete_execution(
    execution_id: str,
    status: str,
    summary: Optional[str] = None,
    error_message: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> bool:
    """
    Update an execution record on completion.

    Args:
        execution_id: The execution to update
        status: Final status ('success' or 'failed')
        summary: Brief summary of what was accomplished
        error_message: Error message if failed
        conversation_id: Conversation ID if not set at creation

    Returns:
        True if update succeeded, False otherwise
    """
    completed_at = datetime.now(timezone.utc)

    # Calculate duration
    execution = await workflow_executions_collection.find_one(
        {"execution_id": execution_id}
    )
    if not execution:
        logger.warning(f"Execution {execution_id} not found for completion")
        return False

    started_at = execution.get("started_at")
    duration_seconds = None
    if started_at:
        if isinstance(started_at, datetime):
            duration_seconds = (completed_at - started_at).total_seconds()

    update_data = {
        "status": status,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
    }

    if summary:
        update_data["summary"] = summary
    if error_message:
        update_data["error_message"] = error_message
    if conversation_id:
        update_data["conversation_id"] = conversation_id

    result = await workflow_executions_collection.update_one(
        {"execution_id": execution_id}, {"$set": update_data}
    )

    logger.info(
        f"Completed execution {execution_id} with status {status}, duration {duration_seconds}s"
    )

    return result.modified_count > 0


async def get_workflow_executions(
    workflow_id: str,
    user_id: str,
    limit: int = 10,
    offset: int = 0,
) -> WorkflowExecutionsResponse:
    """
    Get execution history for a workflow.

    Args:
        workflow_id: ID of the workflow
        user_id: ID of the user (for authorization)
        limit: Maximum number of executions to return
        offset: Number of executions to skip

    Returns:
        WorkflowExecutionsResponse with paginated executions
    """
    query = {"workflow_id": workflow_id, "user_id": user_id}

    # Get total count
    total = await workflow_executions_collection.count_documents(query)

    # Get paginated executions, sorted by most recent first
    cursor = (
        workflow_executions_collection.find(query)
        .sort("started_at", -1)
        .skip(offset)
        .limit(limit)
    )

    executions = []
    async for doc in cursor:
        # Remove MongoDB _id field
        doc.pop("_id", None)
        executions.append(WorkflowExecution(**doc))

    has_more = offset + len(executions) < total

    return WorkflowExecutionsResponse(
        executions=executions,
        total=total,
        has_more=has_more,
    )
