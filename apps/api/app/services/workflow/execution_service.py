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


class WorkflowFireQueued(Exception):
    """A fire whose executor dispatch was queued behind an in-flight run.

    One executor runs per conversation, so a fire that arrives while the
    workflow's previous fire is still working gets put on that conversation's
    queue and answered with an acknowledgement. Nothing this fire asked for has
    happened, which is why it is a signal and not a result: completing its
    execution record from the acknowledgement records work that never ran. The
    queued task runs on its own once the lock frees, and delivers its own
    result, so this is not a failure the user needs to be told about either.

    Carries what the fire did produce so the record can still point somewhere.
    """

    def __init__(
        self,
        *,
        task_id: str,
        user_id: str,
        conversation_id: str,
        trace: list[RecordedCall],
    ) -> None:
        super().__init__(f"Workflow fire queued behind an in-flight run (task_id: {task_id})")
        self.task_id = task_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.trace = trace


class WorkflowFireTimedOut(Exception):
    """A fire the worker cut off at its job timeout; whatever it had started may still finish."""

    def __init__(self, limit_seconds: int) -> None:
        super().__init__(
            f"This run was stopped after {limit_seconds // 60} minutes, the most one run may "
            "take. Anything it had started may still finish on its own; the next scheduled "
            "run is unaffected."
        )
        self.limit_seconds = limit_seconds


class WorkflowFireOverlapped(Exception):
    """A playbook replay that found this workflow's conversation already busy.

    The replay holds the same per-conversation executor lock an agentic run
    does, so two fires of one workflow cannot both replay its playbook (seen
    live: two manual fires at the same moment, two "Replayed 1 step(s)"
    results, every side effect doubled). Unlike :class:`WorkflowFireQueued`
    nothing is put on the queue: the fire is dropped, and the run that holds
    the lock delivers the workflow's one result. So it is neither a success to
    record nor a failure to tell the user about. ``holder`` is the lock value
    of the run that was in flight, for the record and the log.
    """

    def __init__(self, *, user_id: str, conversation_id: str, holder: str) -> None:
        super().__init__(
            f"Workflow fire overlapped an in-flight run of the same workflow (holder: {holder})"
        )
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.holder = holder


class PlaybookFallbackFailed(Exception):
    """A fire that failed AFTER its playbook replay had already run some steps.

    The replay's calls are side effects that happened; if the record of this
    fire does not carry them, the next fire reads an empty history and repeats
    them. Wraps the real failure rather than replacing it, so the caller's
    bookkeeping (rate-limit and budget classification, the user notification)
    still sees the error that actually occurred.
    """

    def __init__(
        self, cause: Exception, *, conversation_id: str, trace: list[RecordedCall]
    ) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.conversation_id = conversation_id
        self.trace = trace


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

    Never raises: the brief is enrichment read before the executor is dispatched,
    and a store hiccup here costs the run its history, not the run itself.
    """
    try:
        previous = await workflow_executions_repository.find_latest_with_trace(workflow_id, user_id)
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} get_last_run_brief: lookup failed; the run proceeds without it",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ""
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
