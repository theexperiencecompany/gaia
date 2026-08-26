"""
Workflow Execution Service.

Service functions for tracking workflow execution history.
"""

from datetime import UTC, datetime
from uuid import uuid4

from app.constants.log_tags import LogTag
from app.db.repositories.workflow_executions import workflow_executions_repository
from app.models.workflow_execution_models import (
    RecordedCall,
    WorkflowExecution,
    WorkflowExecutionDocument,
    WorkflowExecutionsResponse,
    WorkflowExecutionStatus,
)
from app.services.workflow.run_trace import render_last_run
from shared.py.wide_events import log


async def create_execution(
    workflow_id: str,
    user_id: str,
    trigger_type: str = "manual",
    conversation_id: str | None = None,
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
    execution = await workflow_executions_repository.create(
        WorkflowExecutionDocument(
            execution_id=f"exec_{uuid4().hex[:12]}",
            workflow_id=workflow_id,
            user_id=user_id,
            status="running",
            started_at=datetime.now(UTC),
            trigger_type=trigger_type,
            conversation_id=conversation_id,
        )
    )
    # set_ns, not set(workflow=...): the caller already stamped the namespace with
    # trigger_type/steps_count, and a whole-dict set replaces it rather than merging.
    log.set_ns(
        "workflow",
        id=workflow_id,
        status="running",
        execution_id=execution.execution_id,
        trigger_type=trigger_type,
    )
    log.info(
        f"{LogTag.WORKFLOW} Created execution for workflow",
        execution_id=execution.execution_id,
        workflow_id=workflow_id,
    )

    return execution


async def complete_execution(
    execution_id: str,
    status: WorkflowExecutionStatus,
    summary: str | None = None,
    error_message: str | None = None,
    conversation_id: str | None = None,
    trace: list[RecordedCall] | None = None,
) -> bool:
    """
    Update an execution record on completion.

    Args:
        execution_id: The execution to update
        status: Final status ('success' or 'failed')
        summary: Brief summary of what was accomplished
        error_message: Error message if failed
        conversation_id: Conversation ID if not set at creation
        trace: The tool calls this run made, which the next run reads instead of
            replaying the conversation's checkpoints

    Returns:
        True if update succeeded, False otherwise
    """
    updated = await workflow_executions_repository.complete(
        execution_id,
        status=status,
        summary=summary,
        error_message=error_message,
        conversation_id=conversation_id,
        trace=trace,
    )
    if updated is None:
        log.warning(
            f"{LogTag.WORKFLOW} Execution not found for completion",
            execution_id=execution_id,
            conversation_id=conversation_id,
        )
        return False

    duration_seconds = updated.duration_seconds
    duration_ms = int(duration_seconds * 1000) if duration_seconds is not None else None
    # set_ns, not set(workflow=...): this is the LAST write of the namespace on a
    # run, so a whole-dict set is what erased trigger_type from 34,247 of 34,413
    # production workflow fires — leaving no way to tell scheduled fires from
    # webhook ones.
    log.set_ns(
        "workflow",
        id=updated.workflow_id,
        status=status,
        execution_id=execution_id,
        duration_ms=duration_ms,
    )
    log.info(
        f"{LogTag.WORKFLOW} Completed execution",
        execution_id=execution_id,
        status=status,
        duration_seconds=duration_seconds,
    )

    return True


async def get_last_run_brief(workflow_id: str, user_id: str) -> str:
    """The previous run's recorded trace, rendered for the next run's executor brief.

    Empty when the workflow has never recorded one — a first run, or every prior
    run predating the trace.
    """
    previous = await workflow_executions_repository.find_latest_with_trace(workflow_id, user_id)
    return "" if previous is None else render_last_run(previous)


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
    executions, total = await workflow_executions_repository.list_for_workflow(
        workflow_id, user_id, limit=limit, offset=offset
    )
    has_more = offset + len(executions) < total

    return WorkflowExecutionsResponse(
        executions=list(executions),
        total=total,
        has_more=has_more,
    )
