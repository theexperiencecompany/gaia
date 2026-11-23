"""todo_wake: the tracked todo run a finished work reports, read back from the log."""

import pytest

from app.models.conversation_log_models import (
    Batch,
    Entry,
    LoggedEntry,
    TodoReportForm,
    TodoWoke,
    WorkFinished,
    WorkOutcome,
    WorkStarted,
)
from app.services.conversation.todo_wake import nothing_to_report, todo_runs_reported
from tests.unit.services.conversation.log_helpers import at, logged, todo_run, user
from tests.unit.services.conversation.runtime_doubles import FakeClock, InMemoryConversationLog

pytestmark = pytest.mark.unit

CONVERSATION = "conv-todo"
USER = "user-1"


def _work_finished(entry_id: str, task_id: str, *, nothing_for_user: bool) -> WorkFinished:
    return WorkFinished(
        id=entry_id,
        task_id=task_id,
        outcome=WorkOutcome.DONE,
        report="report",
        nothing_for_user=nothing_for_user,
    )


async def _log(*entries: Entry) -> tuple[InMemoryConversationLog, list[LoggedEntry]]:
    log = InMemoryConversationLog(FakeClock())
    appended = [(await log.append(CONVERSATION, USER, entry)).logged for entry in entries]
    return log, appended


def _batch(*waking: LoggedEntry) -> Batch:
    return Batch(start=waking[0].seq, end=waking[-1].seq, waking=waking, first_at=at(1))


async def test_finished_work_reports_the_todo_run_that_woke_it_and_skips_work_it_never_logged() -> (
    None
):
    run = todo_run(TodoReportForm.AS_WRITTEN)
    log, [_, _, _, done] = await _log(
        user("u0"),
        TodoWoke(id="tw1", run=run),
        WorkStarted(id="work:t1", task_id="t1", cause_through=2, answers=("tw1",)),
        _work_finished("f1", "t1", nothing_for_user=True),
    )
    unlogged = logged(9, _work_finished("f9", "t9", nothing_for_user=True))

    reported = await todo_runs_reported(log, CONVERSATION, USER, _batch(unlogged, done))

    assert reported == [(done.entry, run)]


async def test_a_todo_run_that_found_nothing_has_nothing_to_report() -> None:
    log, [_, _, done] = await _log(
        TodoWoke(id="tw1", run=todo_run(TodoReportForm.AS_WRITTEN)),
        WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("tw1",)),
        _work_finished("f1", "t1", nothing_for_user=True),
    )

    assert await nothing_to_report(log, CONVERSATION, USER, _batch(done)) is True


async def test_a_batch_holding_a_message_beside_the_todo_run_needs_a_reply() -> None:
    log, [asked] = await _log(user("u1"))

    assert await todo_runs_reported(log, CONVERSATION, USER, _batch(asked)) == []
    assert await nothing_to_report(log, CONVERSATION, USER, _batch(asked)) is False


async def test_work_that_answers_no_todo_reports_none_even_after_one_woke() -> None:
    log, [_, _, done] = await _log(
        TodoWoke(id="tw1", run=todo_run(TodoReportForm.AS_WRITTEN)),
        WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=()),
        _work_finished("f1", "t1", nothing_for_user=True),
    )

    assert await todo_runs_reported(log, CONVERSATION, USER, _batch(done)) == []


async def test_a_todo_whose_report_is_a_write_up_always_reports() -> None:
    log, [_, _, done] = await _log(
        TodoWoke(id="tw1", run=todo_run(TodoReportForm.WRITE_UP)),
        WorkStarted(id="work:t1", task_id="t1", cause_through=1, answers=("tw1",)),
        _work_finished("f1", "t1", nothing_for_user=True),
    )

    assert await nothing_to_report(log, CONVERSATION, USER, _batch(done)) is False
