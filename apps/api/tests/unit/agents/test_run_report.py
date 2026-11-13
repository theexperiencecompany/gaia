"""What an executor run reports to the outbox: its outcome, and what it is the outcome of."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.agents.core.background.run_report import (
    WorkflowRunRef,
    failed_outcome,
    finished_outcome,
    run_report,
    workflow_run_report,
)
from app.agents.core.background.session import ExecutorRun, RunKind
from app.agents.core.outcome_review import OutcomeReview
from app.constants.agents import OutcomeState
from app.constants.executor import EXECUTOR_ERROR_APPROVAL_LOST, EXECUTOR_ERROR_NO_ANSWER
from app.constants.task_report import FactKind, FailureReason, FailureRecovery
from app.models.ownership_models import DeliveryPolicy, DeliveryTiming
from app.models.task_report_models import FinishTaskArgs, ReportFact
from app.models.user_models import AuthenticatedUser
from app.services.outbox.models import Initiative, ProducerKind, SubjectKind
from app.utils import clock

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


BASE_RUN = ExecutorRun(
    stream_id="s1",
    conversation_id="conv-1",
    user=AuthenticatedUser(user_id=USER_ID),
    kind=RunKind.LIVE,
    task_id="task-1",
    user_message_id=None,
)


def _run(**fields: Any) -> ExecutorRun:
    return replace(BASE_RUN, **fields)


def _filed(outcome: OutcomeState, *, result: str = "the deliverable") -> FinishTaskArgs:
    return FinishTaskArgs(
        result=result,
        outcome=outcome,
        facts=[ReportFact(text="Sent the invoice", kind=FactKind.DID, source_call_ids=["c1"])],
    )


class TestAnErroredRunIsFailedWithTheRunnersReason:
    @pytest.mark.parametrize(
        ("error_type", "reason"),
        [
            ("GraphRecursionError", FailureReason.STEP_LIMIT),
            (EXECUTOR_ERROR_APPROVAL_LOST, FailureReason.APPROVAL_LOST),
            (EXECUTOR_ERROR_NO_ANSWER, FailureReason.CRASH),
            ("RuntimeError", FailureReason.CRASH),
            (None, FailureReason.CRASH),
        ],
    )
    def test_the_reason_comes_from_how_the_run_ended(
        self, error_type: str | None, reason: FailureReason
    ) -> None:
        outcome = failed_outcome(error_type)

        assert outcome.report.outcome is OutcomeState.FAILED
        assert outcome.report.failure is not None
        assert (outcome.report.failure.reason, outcome.report.failure.recovery) == (
            reason,
            FailureRecovery.USER_CAN_RERUN,
        )

    def test_the_raw_error_never_travels(self) -> None:
        assert failed_outcome("RuntimeError").result == ""


class TestAFinishedRunIsReportedAsItsCallsBackIt:
    def test_a_verified_report_is_filed_as_the_run_declared_it(self) -> None:
        review = OutcomeReview(OutcomeState.DONE, None, _filed(OutcomeState.DONE))

        outcome = finished_outcome(review, "rendered text")

        assert (outcome.report.outcome, outcome.review_problem) == (OutcomeState.DONE, None)
        assert [f.text for f in outcome.report.facts] == ["Sent the invoice"]
        # The deliverable, not the rendered report the comms tier used to read.
        assert outcome.result == "the deliverable"

    def test_a_report_its_calls_do_not_back_is_downgraded_and_names_why(self) -> None:
        problem = "done was declared but no work call succeeded"
        review = OutcomeReview(OutcomeState.DONE, problem, _filed(OutcomeState.DONE))

        outcome = finished_outcome(review, "rendered text")

        assert (outcome.report.outcome, outcome.review_problem) == (
            OutcomeState.UNVERIFIED,
            problem,
        )
        assert outcome.report.failure is not None
        assert outcome.report.failure.reason is FailureReason.UNCONFIRMED
        # What the run said it did is still reported, only its outcome is not trusted.
        assert [f.text for f in outcome.report.facts] == ["Sent the invoice"]

    def test_a_run_that_filed_no_report_is_unverified_never_done(self) -> None:
        problem = "the run ended without a finish_task report that declares an outcome"
        review = OutcomeReview(None, problem)

        outcome = finished_outcome(review, "I did it")

        assert (outcome.report.outcome, outcome.review_problem, outcome.result) == (
            OutcomeState.UNVERIFIED,
            problem,
            "I did it",
        )

    def test_a_run_whose_thread_could_not_be_read_is_unverified_never_done(self) -> None:
        outcome = finished_outcome(None, "I did it")

        assert outcome.report.outcome is OutcomeState.UNVERIFIED
        assert outcome.review_problem is None


class TestTheReportNamesWhatItIsAbout:
    @pytest.fixture(autouse=True)
    def _clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(clock, "now", lambda: NOW)

    def test_an_ask_is_the_users_own_request_in_the_conversation_they_made_it(self) -> None:
        run = _run(request_excerpt="send priya the invoice")

        report = run_report(run, failed_outcome(None))

        assert report.producer is ProducerKind.EXECUTOR
        assert (report.report_id, report.subject.kind, report.subject.id) == (
            "ask:task-1:s1",
            SubjectKind.ASK,
            "task-1",
        )
        assert (report.recipient, report.subject.owner_conversation_id) == (USER_ID, "conv-1")
        assert (report.subject.label, report.initiative, report.occurred_at) == (
            "send priya the invoice",
            Initiative.ASKED,
            NOW,
        )

    def test_an_ask_with_no_request_text_is_called_a_request(self) -> None:
        assert run_report(_run(), failed_outcome(None)).subject.label == "Your request"

    def test_a_resumed_run_is_a_new_report_of_the_same_ask(self) -> None:
        first = run_report(_run(stream_id="s1"), failed_outcome(None))
        resumed = run_report(_run(stream_id="queued_s2"), failed_outcome(None))

        assert first.subject.id == resumed.subject.id
        assert first.report_id != resumed.report_id

    def test_the_ask_carries_how_the_user_asked_to_be_told(self) -> None:
        policy = DeliveryPolicy(timing=DeliveryTiming.THE_MOMENT, may_wake=True)

        report = run_report(_run(delivery_policy=policy), failed_outcome(None))

        assert report.delivery_policy == policy

    def test_a_workflow_run_is_the_users_scheduled_answer_in_the_workflows_conversation(
        self,
    ) -> None:
        run = _run(
            workflow_id="wf-1",
            workflow_title="Morning digest",
            workflow_execution_id="exec-1",
            workflow_notify_on_completion=False,
        )

        report = run_report(run, failed_outcome(None))

        assert report.producer is ProducerKind.WORKFLOW
        assert (report.report_id, report.subject.kind, report.subject.id) == (
            "wf:wf-1:exec-1:s1",
            SubjectKind.WORKFLOW_RUN,
            "wf-1:exec-1",
        )
        assert (report.subject.label, report.subject.owner_conversation_id) == (
            "Morning digest",
            "conv-1",
        )
        assert (report.initiative, report.delivery_policy.notify) == (
            Initiative.USER_SCHEDULED,
            False,
        )

    def test_a_replays_report_is_a_second_run_of_the_same_execution(self) -> None:
        agent = run_report(
            _run(workflow_id="wf-1", workflow_execution_id="exec-1"), failed_outcome(None)
        )
        replay = workflow_run_report(
            WorkflowRunRef("wf-1", "", "exec-1", USER_ID, "conv-1", True),
            run_key="replay",
            outcome=failed_outcome(None),
        )

        assert replay.subject.id == agent.subject.id
        assert replay.report_id == "wf:wf-1:exec-1:replay"
        assert replay.subject.label == "Your workflow"
