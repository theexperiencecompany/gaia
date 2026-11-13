"""What an executor run files with the outbox when it ends: the facts of the run, never the words that tell them.

A run's outcome is the typed finish_task report it filed, checked against the calls that
ran. A report the calls do not back, or no report at all, is delivered as unverified and
never as done; an error is a failed outcome with the reason the runner knows.
"""

from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from app.agents.core.background.session import ExecutorRun
from app.agents.core.outcome_review import OutcomeReview
from app.constants.agents import OutcomeState
from app.constants.executor import EXECUTOR_FAILURE_REASONS
from app.constants.outbox import (
    ASK_LABEL_FALLBACK,
    ASK_REPORT_PREFIX,
    WORKFLOW_LABEL_FALLBACK,
    WORKFLOW_REPORT_PREFIX,
)
from app.constants.task_report import FailureReason, FailureRecovery
from app.models.ownership_models import DeliveryPolicy
from app.models.task_report_models import ReportFailure, TaskReport
from app.services.outbox.models import (
    DecidedApproval,
    Initiative,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
)
from app.utils import clock


class RunOutcome(BaseModel):
    """How one run ended, before it is attached to what it was a run of."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report: TaskReport
    result: str = ""
    review_problem: str | None = None
    decided_approvals: list[DecidedApproval] = Field(default_factory=list)


def _unconfirmed(result: str, problem: str | None) -> RunOutcome:
    report = TaskReport(
        outcome=OutcomeState.UNVERIFIED,
        failure=ReportFailure(
            reason=FailureReason.UNCONFIRMED, recovery=FailureRecovery.USER_CAN_RERUN
        ),
    )
    return RunOutcome(report=report, result=result, review_problem=problem)


def failed_outcome(error_type: str | None) -> RunOutcome:
    """Return the outcome of a run that ended in an error of this type: failed, with the runner's reason."""
    reason = EXECUTOR_FAILURE_REASONS.get(error_type or "", FailureReason.CRASH)
    report = TaskReport(
        outcome=OutcomeState.FAILED,
        failure=ReportFailure(reason=reason, recovery=FailureRecovery.USER_CAN_RERUN),
    )
    return RunOutcome(report=report)


def finished_outcome(review: OutcomeReview | None, result_text: str) -> RunOutcome:
    """Return the outcome of a run that ended with an answer, from its reviewed finish_task report.

    review is None when the run's thread could not be read: nothing backs what it says.
    """
    if review is None or review.report is None:
        return _unconfirmed(result_text, review.problem if review is not None else None)
    filed = TaskReport.model_validate(review.report.model_dump(exclude={"result"}))
    if review.problem is None:
        return RunOutcome(report=filed, result=review.report.result)
    downgraded = filed.model_copy(
        update={
            "outcome": OutcomeState.UNVERIFIED,
            "failure": ReportFailure(
                reason=FailureReason.UNCONFIRMED, recovery=FailureRecovery.USER_CAN_RERUN
            ),
        }
    )
    return RunOutcome(report=downgraded, result=review.report.result, review_problem=review.problem)


class WorkflowRunRef(NamedTuple):
    """The execution of a workflow a report is about, and whose it is."""

    workflow_id: str
    title: str
    execution_id: str
    user_id: str
    conversation_id: str
    notify: bool


def workflow_run_report(
    workflow: WorkflowRunRef, *, run_key: str, outcome: RunOutcome
) -> RunReport:
    """Return the report of one run of a workflow: the user set its schedule, so its result is an answer.

    run_key names the run within the execution, so a second submit of it is a no-op.
    """
    subject_id = f"{workflow.workflow_id}:{workflow.execution_id}"
    return RunReport(
        report_id=f"{WORKFLOW_REPORT_PREFIX}{subject_id}:{run_key}",
        recipient=workflow.user_id,
        producer=ProducerKind.WORKFLOW,
        subject=Subject(
            kind=SubjectKind.WORKFLOW_RUN,
            id=subject_id,
            owner_conversation_id=workflow.conversation_id,
            label=workflow.title or WORKFLOW_LABEL_FALLBACK,
        ),
        occurred_at=clock.now(),
        initiative=Initiative.USER_SCHEDULED,
        delivery_policy=DeliveryPolicy(notify=workflow.notify),
        report=outcome.report,
        result=outcome.result,
        review_problem=outcome.review_problem,
        decided_approvals=outcome.decided_approvals,
    )


def run_report(run: ExecutorRun, outcome: RunOutcome) -> RunReport:
    """Attach an outcome to the ask or workflow run it is the outcome of.

    The report id is the run's own: a second submit of the same finalize is a no-op, a resumed
    run (a new stream) is a new report.
    """
    if run.workflow_id:
        workflow = WorkflowRunRef(
            workflow_id=run.workflow_id,
            title=run.workflow_title,
            execution_id=run.workflow_execution_id or run.stream_id,
            user_id=run.user.user_id,
            conversation_id=run.conversation_id,
            notify=run.workflow_notify_on_completion,
        )
        return workflow_run_report(workflow, run_key=run.stream_id, outcome=outcome)
    subject_id = run.task_id or run.stream_id
    return RunReport(
        report_id=f"{ASK_REPORT_PREFIX}{subject_id}:{run.stream_id}",
        recipient=run.user.user_id,
        producer=ProducerKind.EXECUTOR,
        subject=Subject(
            kind=SubjectKind.ASK,
            id=subject_id,
            owner_conversation_id=run.conversation_id,
            label=run.request_excerpt or ASK_LABEL_FALLBACK,
        ),
        occurred_at=clock.now(),
        initiative=Initiative.ASKED,
        delivery_policy=run.delivery_policy,
        report=outcome.report,
        result=outcome.result,
        review_problem=outcome.review_problem,
        decided_approvals=outcome.decided_approvals,
    )
