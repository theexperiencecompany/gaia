"""The Inbox desk's operating prompt and the thread contract: their structure, never model output."""

import pytest

from app.agents.prompts.todo_prompts import GMAIL_THREAD_RUN_GUIDANCE, INBOX_DESK_PROMPT
from app.constants.todos import INBOX_DESK_TITLE, NEEDS_REPLY_LABEL, WAITING_FOR_REPLY_LABEL
from app.models.todo_models import TodoModel

BRIEFING_SECTIONS = ["Needs you", "Waiting on others", "Today", "FYI", "Filtered"]
THREAD_CLASSES = ["TO_REPLY", "AWAITING_REPLY", "FYI", "ACTIONED"]


def _step(number: int) -> list[str]:
    """Return the lines of one numbered step, its heading line first."""
    body = INBOX_DESK_PROMPT.split(f"\n{number}. ", 1)[1]
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
    assert f'list_tracked_todos(labels=["{label}"])' in "\n".join(_step(9))


def test_the_prompt_fits_in_a_todo_description() -> None:
    desk = TodoModel(title=INBOX_DESK_TITLE, description=INBOX_DESK_PROMPT)

    assert desk.description == INBOX_DESK_PROMPT


def test_the_thread_contract_names_its_thread_and_both_states() -> None:
    guidance = GMAIL_THREAD_RUN_GUIDANCE.format(ref_id="18c2f0a9b7d4e611")

    assert "Gmail thread 18c2f0a9b7d4e611." in guidance
    assert NEEDS_REPLY_LABEL in guidance and WAITING_FOR_REPLY_LABEL in guidance
