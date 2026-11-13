"""read_task: comms answers a follow-up from a task's record, at the report level or the trace level."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.work_record_tool import read_task
from app.constants.agents import OutcomeState
from app.constants.task_report import FactKind
from app.constants.tasks import FACT_FRESHNESS_TEXT
from app.models.outbox_models import OutboxItemDocument
from app.models.run_trace_models import (
    CallEffect,
    CallStatus,
    RunCallDocument,
    RunDocument,
    RunState,
)
from app.models.task_report_models import ReportFact, TaskReport
from app.models.todo_models import TodoDocument
from app.services.executor_trace.reader import CallDetail
from app.services.outbox.models import (
    Initiative,
    NoticeOutcome,
    NoticeReport,
    ProducerKind,
    RunReport,
    Subject,
    SubjectKind,
)
from shared.py.analytics import UserId
from shared.py.analytics.catalog.tasks import TaskRead

pytestmark = pytest.mark.unit

MODULE = "app.agents.tools.work_record_tool"
USER = "6812f0b3c9a14e2b7d5a91cc"
TASK = "6812f0b3c9a14e2b7d5a91dd"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
CHAT = "chat-where-it-started"
CONFIG = {"configurable": {"thread_id": CHAT, "user_id": USER}}


def _task(**fields: object) -> TodoDocument:
    return TodoDocument(
        id=TASK,
        user_id=USER,
        title="Find the Lisbon flights",
        source_conversation_id=CHAT,
        canvas_content="# t\n\n## Done when\n- three options are listed\n",
        **fields,
    )


def _report_item(*, observed: datetime, price: str = "EUR 212 on TAP") -> OutboxItemDocument:
    report = RunReport(
        report_id=f"todo:{TASK}:r1",
        recipient=USER,
        producer=ProducerKind.TODO,
        subject=Subject(
            kind=SubjectKind.TODO_RUN, id=f"{TASK}:r1", label="Find the Lisbon flights"
        ),
        occurred_at=observed,
        initiative=Initiative.ASKED,
        report=TaskReport(
            outcome=OutcomeState.DONE,
            facts=[ReportFact(text=f"Cheapest flight is {price}", kind=FactKind.OBSERVED)],
        ),
        result="Three options found.",
    )
    return OutboxItemDocument(
        user_id=USER, report_id=report.report_id, report=report, expires_at=NOW
    )


def _run(run_id: str = "r1") -> RunDocument:
    return RunDocument(
        user_id=USER,
        run_id=run_id,
        conversation_id="task-chat",
        todo_id=TASK,
        state=RunState.FINISHED,
        started_at=NOW,
        last_activity_at=NOW,
    )


def _call(call_id: str = "c1") -> RunCallDocument:
    return RunCallDocument(
        user_id=USER,
        run_id="r1",
        call_id=call_id,
        tool_name="SKYSCANNER_SEARCH",
        effect=CallEffect.READ,
        status=CallStatus.OK,
        started_at=NOW,
        finished_at=NOW,
        summary="LIS",
        payload_ref="p1",
    )


@pytest.fixture
def captured() -> MagicMock:
    with patch(f"{MODULE}.capture") as capture:
        yield capture


@pytest.fixture(autouse=True)
def _frozen_clock():
    with patch(f"{MODULE}.datetime") as clock:
        clock.now.return_value = NOW
        yield


async def _read(**args: object) -> str:
    return await read_task.ainvoke({"task_id": TASK, **args}, config=CONFIG)


class TestReportLevel:
    async def test_it_gives_the_state_the_facts_and_how_old_they_are(
        self, captured: MagicMock
    ) -> None:
        observed = NOW - timedelta(minutes=95)
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(
                f"{MODULE}.outbox_items_repository.list_of_series",
                AsyncMock(return_value=[_report_item(observed=observed)]),
            ),
        ):
            text = await _read()

        assert "Find the Lisbon flights" in text
        assert "three options are listed" in text
        assert "observed 1 h ago" in text
        assert "[observed] Cheapest flight is EUR 212 on TAP" in text
        assert "Outcome: done" in text
        assert FACT_FRESHNESS_TEXT in text

    async def test_it_reads_the_series_of_this_task_only(self, captured: MagicMock) -> None:
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(
                f"{MODULE}.outbox_items_repository.list_of_series", AsyncMock(return_value=[])
            ) as items,
        ):
            text = await _read()

        assert items.await_args.args == (USER, f"todo:{TASK}")
        assert "No run has reported on this task yet." in text

    async def test_a_notice_about_the_task_is_not_its_run_report(self, captured: MagicMock) -> None:
        notice = NoticeReport(
            report_id="sys:overdue",
            recipient=USER,
            producer=ProducerKind.ACCOUNT,
            subject=Subject(kind=SubjectKind.TODO_RUN, id="n1", label="x"),
            occurred_at=NOW,
            initiative=Initiative.SELF_INITIATED,
            outcome=NoticeOutcome.INFO,
            facts=["It is overdue."],
        )
        item = OutboxItemDocument(
            user_id=USER, report_id="sys:overdue", report=notice, expires_at=NOW
        )
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(
                f"{MODULE}.outbox_items_repository.list_of_series", AsyncMock(return_value=[item])
            ),
        ):
            text = await _read()

        assert "No run has reported on this task yet." in text
        assert "It is overdue." not in text

    async def test_a_task_that_is_not_the_users_is_not_found(self, captured: MagicMock) -> None:
        with patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=None)) as get:
            text = await _read()

        assert get.await_args.kwargs == {"user_id": USER}
        assert "no task" in text
        captured.assert_not_called()

    async def test_the_read_is_measured_with_the_age_and_where_the_task_began(
        self, captured: MagicMock
    ) -> None:
        elsewhere = _task().model_copy(update={"source_conversation_id": "another-chat"})
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=elsewhere)),
            patch(
                f"{MODULE}.outbox_items_repository.list_of_series",
                AsyncMock(return_value=[_report_item(observed=NOW - timedelta(minutes=10))]),
            ),
        ):
            await _read()

        (user, event), _ = captured.call_args
        assert user == UserId(USER)
        assert event == TaskRead(level="report", cross_conversation=True, report_age_seconds=600)


class TestTraceLevel:
    async def test_it_lists_the_tasks_runs_with_their_calls(self, captured: MagicMock) -> None:
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(f"{MODULE}.list_todo_runs", AsyncMock(return_value=[_run()])) as runs,
            patch(f"{MODULE}.list_run_calls", AsyncMock(return_value=[_call()])),
        ):
            text = await _read(level="trace")

        assert runs.await_args.args == (USER, TASK)
        assert text == (
            "Run finished, started 2026-11-13T12:00+00:00:\n[c1] read SKYSCANNER_SEARCH ok: LIS"
        )
        assert captured.call_args.args[1] == TaskRead(level="trace", cross_conversation=False)

    async def test_a_call_id_returns_that_calls_full_input_and_output(
        self, captured: MagicMock
    ) -> None:
        detail = CallDetail(
            call=_call(), input_json='{"to": "LIS"}', output_text="EUR 212", truncated=False
        )
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(f"{MODULE}.list_todo_runs", AsyncMock(return_value=[_run()])),
            patch(f"{MODULE}.get_call_detail", AsyncMock(return_value=detail)) as get_detail,
        ):
            text = await _read(level="trace", call_id="c1")

        assert get_detail.await_args.args == (USER, "r1", "c1")
        assert '{"to": "LIS"}' in text
        assert "EUR 212" in text

    async def test_a_call_that_is_not_in_the_tasks_runs_is_not_invented(
        self, captured: MagicMock
    ) -> None:
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(f"{MODULE}.list_todo_runs", AsyncMock(return_value=[_run()])),
            patch(f"{MODULE}.get_call_detail", AsyncMock(return_value=None)),
        ):
            text = await _read(level="trace", call_id="c-other-task")

        assert text == "No call c-other-task is recorded for this task."

    async def test_a_task_that_never_ran_says_so(self, captured: MagicMock) -> None:
        with (
            patch(f"{MODULE}.todo_repository.get", AsyncMock(return_value=_task())),
            patch(f"{MODULE}.list_todo_runs", AsyncMock(return_value=[])),
        ):
            assert await _read(level="trace") == "No run of this task has been recorded."
