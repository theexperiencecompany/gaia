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
    """A fire that found this workflow's conversation already busy when it asked for admission.

    A workflow owns one conversation across all runs. The overlapped fire is dropped
    before it spends anything, not handed over: the run in flight delivers the
    workflow's one result, and this fire is neither a success to record nor a
    failure to notify. holder names what is in flight, for the record and the log;
    awaiting_approval says the log has that work waiting on the user's decision.
    """

    def __init__(
        self, *, user_id: str, conversation_id: str, holder: str, awaiting_approval: bool = False
    ) -> None:
        super().__init__(
            f"Workflow fire overlapped an in-flight run of the same workflow (holder: {holder})"
        )
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.holder = holder
        self.awaiting_approval = awaiting_approval


class PlaybookReplayRefused(Exception):
    """The conversation log refused to start a replay: other work or a fire got there after admission."""

    def __init__(self, conversation_id: str) -> None:
        super().__init__(
            f"conversation {conversation_id} refused the replay: other work runs there"
        )
        self.conversation_id = conversation_id


class WorkflowRunFailed(Exception):
    """A fire that failed after it had already done something on record.

    The calls in trace are side effects that happened; if the record of
    this fire does not carry them, the next fire reads an empty history and
    repeats them.
    """

    def __init__(self, message: str, *, conversation_id: str, trace: list[RecordedCall]) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.trace = trace


class PlaybookFallbackFailed(WorkflowRunFailed):
    """A fire that failed AFTER its playbook replay had already run some steps.

    Wraps the real failure rather than replacing it, so the caller's
    bookkeeping (rate-limit and budget classification, the user notification)
    still sees the error that actually occurred.
    """

    def __init__(
        self, cause: Exception, *, conversation_id: str, trace: list[RecordedCall]
    ) -> None:
        super().__init__(str(cause), conversation_id=conversation_id, trace=trace)
        self.cause = cause


class WorkflowTurnFailed(WorkflowRunFailed):
    """The workflow's turn, or the work it handed off, ended without carrying the run out.

    Failed, stopped, or lost: recording it as a successful run would say the workflow ran
    when it did not, so the fire is closed out, and the user told, as a failure.
    """


def new_execution_id() -> str:
    """Mint a workflow execution id: once per fire, by whoever starts it."""
    return f"exec_{uuid4().hex[:12]}"


async def create_execution(
    workflow_id: str,
    user_id: str,
    trigger_type: str = "manual",
    conversation_id: str | None = None,
    execution_id: str | None = None,
) -> WorkflowExecution:
    """Create a workflow execution record with status "running", under the id the fire was started with.

    Args:
        trigger_type: manual, schedule, or an integration name.
    """
    execution = await workflow_executions_repository.create(
        WorkflowExecutionDocument(
            execution_id=execution_id or new_execution_id(),
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


async def record_skipped_execution(
    workflow_id: str,
    user_id: str,
    trigger_type: str,
    summary: str,
    conversation_id: str | None = None,
    execution_id: str | None = None,
) -> WorkflowExecution:
    """Record a fire that never ran, so run history shows it and why instead of a silent gap."""
    execution = await create_execution(
        workflow_id=workflow_id,
        user_id=user_id,
        trigger_type=trigger_type,
        execution_id=execution_id,
    )
    await complete_execution(
        execution_id=execution.execution_id,
        status="skipped",
        summary=summary,
        conversation_id=conversation_id,
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
    """Update an execution record on completion.

    Args:
        trace: read by the next run instead of replaying the conversation's checkpoints.
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
    # set_ns, not set(workflow=...): a whole-dict set here erased trigger_type from
    # 34,247 of 34,413 production workflow fires (last namespace write of the run).
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
    """Return the previous run's recorded trace, rendered for the next run's executor brief.

    Empty on a first run or before the trace existed. Never raises: a lookup
    failure costs the run its history, not the run itself.
    """
    try:
        recent = await workflow_executions_repository.find_recent_with_trace(
            workflow_id, user_id, limit=1
        )
    except Exception as e:
        log.warning(
            f"{LogTag.WORKFLOW} get_last_run_brief: lookup failed; the run proceeds without it",
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
        )
        return ""
    return render_last_run(recent[0]) if recent else ""


async def get_workflow_executions(
    workflow_id: str,
    user_id: str,
    limit: int = 10,
    offset: int = 0,
) -> WorkflowExecutionsResponse:
    """Get paginated execution history for a workflow."""
    executions, total = await workflow_executions_repository.list_for_workflow(
        workflow_id, user_id, limit=limit, offset=offset
    )
    has_more = offset + len(executions) < total

    return WorkflowExecutionsResponse(
        executions=list(executions),
        total=total,
        has_more=has_more,
    )
