"""The Inbox desk's operating prompt and the thread contract: their structure, never model output."""

import pytest

from app.agents.prompts.todo_prompts import (
    GMAIL_THREAD_RUN_GUIDANCE,
    INBOX_DESK_DESCRIPTION,
    INBOX_DESK_RUN_GUIDANCE,
)
from app.constants import agents as agent_constants, todos as todo_constants
from app.constants.todos import INBOX_DESK_TITLE, NEEDS_REPLY_LABEL, WAITING_FOR_REPLY_LABEL
from app.models.todo_models import TodoModel

BRIEFING_SECTIONS = ["Needs you", "Waiting on others", "Done", "Today", "FYI", "Filtered"]
THREAD_CLASSES = ["TO_REPLY", "AWAITING_REPLY", "FYI", "ACTIONED"]


def _step(number: int) -> list[str]:
    """Return the lines of one numbered step, its heading line first."""
    body = INBOX_DESK_RUN_GUIDANCE.split(f"\n{number}. ", 1)[1]
    return body.split(f"\n{number + 1}. ", 1)[0].splitlines()


def _heads(lines: list[str]) -> list[str]:
    return [line.split(":", 1)[0] for line in lines if ":" in line]


def test_the_briefing_is_the_five_sections_in_order() -> None:
    assert _heads(_step(9)[1:])[: len(BRIEFING_SECTIONS)] == BRIEFING_SECTIONS


def test_each_thread_class_is_defined_where_threads_are_classified() -> None:
    assert _heads(_step(4)[1:]) == THREAD_CLASSES


@pytest.mark.parametrize("label", [NEEDS_REPLY_LABEL, WAITING_FOR_REPLY_LABEL])
def test_thread_todos_are_filed_and_briefed_under_the_label_constants(label: str) -> None:
    assert f'["{label}"]' in "\n".join(_step(5))
    assert f"your {label} sub-todos" in "\n".join(_step(9))


def test_thread_todos_are_opened_as_the_desks_sub_todos() -> None:
    step = "\n".join(_step(5))

    assert "parent_todo_id=this todo's id" in step
    assert "references" not in step


def test_the_description_fits_in_a_todo_description() -> None:
    desk = TodoModel(title=INBOX_DESK_TITLE, description=INBOX_DESK_DESCRIPTION)

    assert desk.description == INBOX_DESK_DESCRIPTION


def test_the_thread_contract_names_its_thread_and_both_states() -> None:
    guidance = GMAIL_THREAD_RUN_GUIDANCE.format(ref_id="18c2f0a9b7d4e611")

    assert "Gmail thread 18c2f0a9b7d4e611." in guidance
    assert NEEDS_REPLY_LABEL in guidance and WAITING_FOR_REPLY_LABEL in guidance


def _line(step: list[str], head: str) -> str:
    return next(line for line in step if line.startswith(f"{head}:"))


@pytest.mark.regression
def test_the_window_is_a_day_first_then_unix_seconds_never_a_clock_time() -> None:
    step = "\n".join(_step(2))

    assert "newer_than:1d" in step
    assert "after:<last processed time as Unix seconds>" in step
    assert "never a date or a clock time" in step
    assert '"after:<that time>"' not in step


@pytest.mark.regression
def test_the_query_filters_automated_senders_and_rules_may_change_the_filter() -> None:
    step = "\n".join(_step(2))

    assert todo_constants.INBOX_DESK_MAIL_FILTER in step
    assert "Standing rules may widen or narrow" in step


@pytest.mark.regression
def test_the_cursor_is_the_first_fetchs_own_stamp() -> None:
    assert agent_constants.TOOL_RESULT_FETCHED_AT_KEY in "\n".join(_step(8))


@pytest.mark.regression
def test_a_document_nobody_awaits_an_answer_on_is_fyi_not_to_reply() -> None:
    step = _step(4)

    assert "a person expects an answer" in _line(step, "TO_REPLY")
    assert "statements" in _line(step, "FYI")


@pytest.mark.regression
def test_the_run_leaves_activity_md_to_gaia() -> None:
    assert "GAIA records this run and your report in activity.md" in INBOX_DESK_RUN_GUIDANCE


@pytest.mark.regression
def test_the_thread_state_is_this_todos_label_never_a_gmail_label() -> None:
    guidance = GMAIL_THREAD_RUN_GUIDANCE.format(ref_id="18c2f0a9b7d4e611")

    assert "Never create, apply or remove Gmail labels" in guidance
    assert "update_tracked_todo labels" in guidance
    assert "set the label to match" not in guidance
