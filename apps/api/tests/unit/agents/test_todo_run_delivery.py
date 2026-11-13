"""What a tracked todo's run files with the outbox that the end-to-end wiring test does not reach.

The report carries what the todo says when the run finishes: its notify flag, standing rules and
key details, whether it runs once, and the form an outside owner sets. The wiring from the run
to this module runs end to end in tests/unit/agents/test_tracked_todo_run_delivery.py.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.background import todo_run_delivery as trd
from app.agents.core.background.run_report import RunOutcome
from app.agents.core.background.session import ExecutorRun, RunKind, TodoRun
from app.agents.core.background.todo_run_delivery import deliver_todo_run_result
from app.constants import todos as todo_constants
from app.constants.agents import OutcomeState
from app.models import todo_models
from app.models.task_report_models import TaskReport
from app.models.todo_models import TodoDocument
from app.models.user_models import AuthenticatedUser
from app.models.workflow_models import TriggerType
from app.services.outbox.models import Initiative, RunReport
from app.services.tracked_todo_service import CANVAS_TEMPLATE
from tests.helpers import captured_wide_event

pytestmark = pytest.mark.unit

USER_ID = "6812f0b3c9a14e2b7d5a91cc"
OWNER_ID = "6812f0b3c9a14e2b7d5a91cd"
USER = AuthenticatedUser(user_id=USER_ID)
RUN = ExecutorRun(
    stream_id="s1",
    conversation_id="run-conv",
    user=USER,
    kind=RunKind.LIVE,
    task_id="t1",
    user_message_id=None,
)
SCHEDULED = TodoRun(todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO, runs_once=True)
OUTCOME = RunOutcome(report=TaskReport(outcome=OutcomeState.DONE), result="report")


@dataclass
class _Seams:
    submit: AsyncMock
    activity: AsyncMock
    report: AsyncMock

    def entry(self) -> str:
        return self.activity.await_args.args[3]

    def filed(self) -> RunReport:
        return self.submit.await_args.args[0]


@contextmanager
def _seams(*, todo: TodoDocument | None) -> Iterator[_Seams]:
    seams = _Seams(submit=AsyncMock(), activity=AsyncMock(return_value=True), report=AsyncMock())
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=todo)
    with (
        patch.object(trd, "submit", seams.submit),
        patch.object(trd, "record_executor_report", seams.report),
        patch.object(trd, "todo_repository", repo),
        patch.object(trd, "record_run_finished", seams.activity),
    ):
        yield seams


def _todo(**fields: object) -> TodoDocument:
    return TodoDocument.model_validate(
        {"id": "todo-1", "user_id": USER_ID, "title": "Watch the deploy", **fields}
    )


async def _deliver(result_type: str = "final", todo_run: TodoRun = SCHEDULED) -> None:
    await deliver_todo_run_result(RUN, todo_run, OUTCOME, "report", result_type)


class TestTheRunIsReportedOnceUnderItsOwnId:
    async def test_the_report_names_the_run_and_the_todo(self) -> None:
        with _seams(todo=_todo()) as seams:
            await _deliver()

        report = seams.filed()
        assert report.report_id == "todo:todo-1:s1"
        assert (report.subject.id, report.subject.series, report.subject.label) == (
            "todo-1:s1",
            "todo:todo-1",
            "Watch the deploy",
        )
        assert (report.recipient, report.report.outcome) == (USER_ID, OutcomeState.DONE)
        assert seams.entry() == "reported to the outbox: done (summary='report')"
        seams.report.assert_awaited_once_with("run-conv", "report", "final")

    async def test_the_report_is_owned_by_the_chat_the_run_ran_in(self) -> None:
        with _seams(todo=_todo()) as seams:
            await _deliver()

        assert seams.filed().subject.owner_conversation_id == "run-conv"

    async def test_a_run_once_todo_answers_in_the_conversation_that_asked_it(self) -> None:
        with _seams(todo=_todo(source_conversation_id="web-chat")) as seams:
            await _deliver()

        assert seams.filed().subject.owner_conversation_id == "web-chat"

    async def test_a_task_answers_the_turn_that_last_asked_it_and_settles_its_chip(self) -> None:
        asked = todo_models.AskOrigin(conversation_id="tg-chat", message_id="bot-msg-2")
        with _seams(todo=_todo(source_conversation_id="web-chat", ask_origin=asked)) as seams:
            await _deliver()

        report = seams.filed()
        assert report.subject.owner_conversation_id == "tg-chat"
        assert report.turn_message_id == "bot-msg-2"

    async def test_a_todo_that_runs_again_reports_in_its_own_chat(self) -> None:
        recurring = _todo(source_conversation_id="web-chat", recurrence="FREQ=DAILY")
        with _seams(todo=recurring) as seams:
            await _deliver(todo_run=replace(SCHEDULED, runs_once=False))

        assert seams.filed().subject.owner_conversation_id == "run-conv"
        assert seams.filed().turn_message_id is None

    async def test_the_report_is_the_todos_owners_not_the_runs_user(self) -> None:
        with _seams(todo=_todo(user_id=OWNER_ID)) as seams:
            await _deliver()

        assert seams.filed().recipient == OWNER_ID
        assert seams.activity.await_args.args[:2] == ("todo-1", OWNER_ID)

    async def test_an_error_result_is_left_to_the_worker(self) -> None:
        with _seams(todo=_todo()) as seams:
            await _deliver("error")

        seams.submit.assert_not_awaited()
        seams.activity.assert_not_awaited()
        seams.report.assert_awaited_once_with("run-conv", "report", "error")

    async def test_a_todo_deleted_mid_run_is_a_warning_naming_it(self) -> None:
        with _seams(todo=None) as seams:
            async with captured_wide_event() as event:
                await _deliver()

        seams.submit.assert_not_awaited()
        assert [w["todo_id"] for w in event["warnings"]] == ["todo-1"]

    async def test_a_run_already_finished_is_not_reported_again(self) -> None:
        log = "- 2026-11-06T05:32:00+00:00 [run_finished] run s1: reported to the outbox: done\n"
        with _seams(todo=_todo(activity_content=log)) as seams:
            await _deliver()

        seams.submit.assert_not_awaited()
        seams.activity.assert_not_awaited()


class TestTheReportCarriesWhatTheTodoSaysNow:
    async def test_notifications_the_run_turned_off_are_carried(self) -> None:
        with _seams(todo=_todo(notify_on_run=False)) as seams:
            await _deliver()

        assert seams.filed().delivery_policy.notify is False

    async def test_a_run_of_a_todo_that_runs_once_exists_to_answer(self) -> None:
        with _seams(todo=_todo()) as seams:
            await _deliver()

        report = seams.filed()
        assert report.initiative is Initiative.ASKED
        assert report.guidance is not None
        assert report.guidance.runs_once is True

    async def test_a_run_of_a_todo_that_repeats_reports_on_its_own(self) -> None:
        repeating = TodoRun(
            todo_id="todo-1", trigger_type=TriggerType.SCHEDULED_TODO, runs_once=False
        )
        with _seams(todo=_todo(recurrence="every_1h")) as seams:
            await _deliver(todo_run=repeating)

        report = seams.filed()
        assert report.initiative is Initiative.SELF_INITIATED
        assert report.guidance is not None
        assert report.guidance.runs_once is False

    @pytest.mark.regression
    async def test_a_watching_todo_that_completes_itself_keeps_the_silence_rule(self) -> None:
        """Regression: completing a todo tore its watch down before delivery read it."""
        completed_thread = _todo(
            completed=True,
            external_ref=todo_models.ExternalRef(
                source=todo_models.ExternalRefSource.GMAIL_THREAD, id="t1"
            ),
        )
        watching = TodoRun(todo_id="todo-1", trigger_type=TriggerType.TODO_TRIGGER, runs_once=False)
        with _seams(todo=completed_thread) as seams:
            await _deliver(todo_run=watching)

        report = seams.filed()
        assert report.initiative is Initiative.SELF_INITIATED
        assert report.guidance is not None
        assert report.guidance.runs_once is False

    async def test_the_standing_rules_are_bounded(self) -> None:
        long_rules = (
            "- 2026-09-28: tell me every time.\n" + "x" * todo_constants.STANDING_RULES_MAX_CHARS
        )
        todo = _todo(
            canvas_content=f"## Standing rules\n{long_rules}\n\n## Key Details\n- thread abc\n"
        )
        with _seams(todo=todo) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.standing_rules == long_rules[: todo_constants.STANDING_RULES_MAX_CHARS]
        assert guidance.key_details == "- thread abc"

    @pytest.mark.regression
    async def test_a_request_an_older_todo_kept_in_key_details_still_reaches_the_report(
        self,
    ) -> None:
        details = "- tell me every time.\n" + "x" * todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS
        todo = _todo(canvas_content=f"## Key Details\n{details}\n\n## Current State\n- ok\n")
        with _seams(todo=todo) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.standing_rules is None
        assert guidance.key_details == details[: todo_constants.DELIVERY_KEY_DETAILS_MAX_CHARS]

    @pytest.mark.regression
    async def test_a_new_todo_template_carries_no_rules(self) -> None:
        todo = _todo(canvas_content=CANVAS_TEMPLATE.format(title="Watch the deploy"))
        with _seams(todo=todo) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert (guidance.standing_rules, guidance.key_details) == (None, None)

    @pytest.mark.regression
    async def test_a_title_cased_heading_still_reaches_the_report(self) -> None:
        todo = _todo(canvas_content="## Standing Rules\n- 2026-09-28: tell me every time.\n")
        with _seams(todo=todo) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.standing_rules == "- 2026-09-28: tell me every time."

    async def test_a_todo_with_no_canvas_carries_no_guidance_text(self) -> None:
        with _seams(todo=_todo(canvas_content=None)) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert (guidance.standing_rules, guidance.key_details) == (None, None)


class TestABriefingThatOwnsItsForm:
    """An outside owner (the desk, a mail thread) sets its todo's report form: it is told as written."""

    @pytest.mark.regression
    async def test_a_desk_briefing_is_told_verbatim(self) -> None:
        """Regression: comms retold a sectioned desk briefing as flat lines, its headings gone."""
        desk = _todo(
            external_ref=todo_models.ExternalRef(
                source=todo_models.ExternalRefSource.INBOX_DESK, id="int-1"
            )
        )
        with _seams(todo=desk) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.verbatim is True

    async def test_a_thread_todos_alert_is_told_verbatim(self) -> None:
        """Regression: comms retold a thread's one-email alert, dropping its who, what and where."""
        thread = _todo(
            external_ref=todo_models.ExternalRef(
                source=todo_models.ExternalRefSource.GMAIL_THREAD, id="t1"
            )
        )
        with _seams(todo=thread) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.verbatim is True

    async def test_a_todo_with_no_outside_owner_has_no_form_of_its_own(self) -> None:
        with _seams(todo=_todo()) as seams:
            await _deliver()

        guidance = seams.filed().guidance
        assert guidance is not None
        assert guidance.verbatim is False
