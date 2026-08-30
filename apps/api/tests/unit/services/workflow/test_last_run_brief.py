"""The last-run brief is enrichment for the executor, never a reason a run fails."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.log_tags import LogTag
from app.models.workflow_execution_models import RecordedCall, WorkflowExecutionDocument
from app.services.workflow.execution_service import (
    PlaybookFallbackFailed,
    WorkflowFireOverlapped,
    WorkflowFireQueued,
    WorkflowFireTimedOut,
    get_last_run_brief,
)
from app.services.workflow.run_trace import render_last_run

MODULE = "app.services.workflow.execution_service"


def _previous_run() -> WorkflowExecutionDocument:
    """A finished run that recorded a trace, as the finder hands it back."""
    return WorkflowExecutionDocument(
        execution_id="ex_1",
        workflow_id="wf_1",
        user_id="u_1",
        status="success",
        started_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 9, 1, tzinfo=UTC),
        summary="Mailed the agenda",
        trace=[RecordedCall(tool_name="send_email", args={"to": "team@example.com"})],
    )


@pytest.mark.unit
class TestLastRunBriefFailsOpen:
    async def test_a_first_run_has_no_brief(self) -> None:
        lookup = AsyncMock(return_value=None)
        with patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup):
            assert await get_last_run_brief("wf_1", "u_1") == ""
        lookup.assert_awaited_once_with("wf_1", "u_1")

    async def test_a_failed_lookup_yields_no_brief_and_a_warning(self) -> None:
        """The brief is read before the executor is dispatched. A store hiccup
        here must cost the run its history, not the run itself."""
        lookup = AsyncMock(side_effect=RuntimeError("mongo unavailable"))
        with (
            patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup),
            patch(f"{MODULE}.log") as log,
        ):
            assert await get_last_run_brief("wf_1", "u_1") == ""

        assert log.warning.call_count == 1
        assert log.warning.call_args.kwargs["error_type"] == "RuntimeError"

    async def test_the_warning_names_the_workflow_and_the_real_error(self) -> None:
        """The whole point of the swallow is that the wide event still says what
        broke and for which workflow. A message, id or error dropped or None'd
        here turns a silent no-brief run into an unexplainable one, and nothing
        else in the system records it."""
        lookup = AsyncMock(side_effect=RuntimeError("mongo unavailable"))
        with (
            patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup),
            patch(f"{MODULE}.log") as log,
        ):
            await get_last_run_brief("wf_1", "u_1")

        assert log.warning.call_args.args == (
            f"{LogTag.WORKFLOW} get_last_run_brief: lookup failed; the run proceeds without it",
        )
        assert log.warning.call_args.kwargs == {
            "workflow_id": "wf_1",
            "error": "mongo unavailable",
            "error_type": "RuntimeError",
        }

    async def test_a_recorded_previous_run_is_rendered_as_the_brief(self) -> None:
        """The brief IS that execution rendered — the found document is what gets
        rendered, not some other value that happens to render to a string."""
        previous = _previous_run()
        lookup = AsyncMock(return_value=previous)
        with patch(f"{MODULE}.workflow_executions_repository.find_latest_with_trace", lookup):
            brief = await get_last_run_brief("wf_1", "u_1")

        assert brief == render_last_run(previous)
        assert brief != ""


@pytest.mark.unit
class TestTheFireSignalsSayExactlyWhatHappened:
    """The fire exceptions ARE user- and log-facing copy: the timed-out text is
    delivered to the user as the run summary, and the queued/overlapped strings
    are what the worker logs as the reason a fire never ran."""

    def test_a_queued_fire_names_its_task(self) -> None:
        queued = WorkflowFireQueued(task_id="task_9", user_id="u1", conversation_id="c1", trace=[])

        assert str(queued) == "Workflow fire queued behind an in-flight run (task_id: task_9)"
        assert queued.task_id == "task_9"

    def test_an_overlapped_fire_names_its_holder(self) -> None:
        overlapped = WorkflowFireOverlapped(user_id="u1", conversation_id="c1", holder="run_3")

        assert (
            str(overlapped)
            == "Workflow fire overlapped an in-flight run of the same workflow (holder: run_3)"
        )

    def test_the_timed_out_fire_reads_as_the_user_facing_summary(self) -> None:
        timed_out = WorkflowFireTimedOut(1800)

        assert timed_out.limit_seconds == 1800
        assert str(timed_out) == (
            "This run was stopped after 30 minutes, the most one run may "
            "take. Anything it had started may still finish on its own; the next scheduled "
            "run is unaffected."
        )

    def test_the_playbook_fallback_failure_carries_its_cause_text(self) -> None:
        cause = RuntimeError("graph exploded")
        failed = PlaybookFallbackFailed(cause, conversation_id="c1", trace=[])

        assert str(failed) == "graph exploded"
        assert failed.cause is cause
