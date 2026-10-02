"""The Inbox desk's operating prompt and the thread contract: their structure, never model output."""

import json
import re

import pytest

from app.agents.prompts import todo_prompts
from app.agents.prompts.todo_prompts import (
    GMAIL_THREAD_RUN_GUIDANCE,
    INBOX_DESK_DESCRIPTION,
    INBOX_DESK_RUN_GUIDANCE,
)
from app.agents.templates.mail_templates import message_view_needs_body
from app.agents.tools.coding.query_json_tool import query_json
from app.constants import agents as agent_constants, todos as todo_constants
from app.constants.email import DEFAULT_SUMMARY_FIELDS
from app.constants.todos import INBOX_DESK_TITLE, NEEDS_REPLY_LABEL, WAITING_FOR_REPLY_LABEL
from app.models.composio_schemas.gmail import FetchMessagesInput
from app.models.todo_models import TodoModel

BRIEFING_SECTIONS = ["Needs you", "Waiting on others", "Done", "Today", "FYI", "Filtered"]
THREAD_CLASSES = ["TO_REPLY", "AWAITING_REPLY", "FYI", "ACTIONED"]


def _step(number: int) -> list[str]:
    """Return the lines of one numbered step, its heading line first."""
    body = INBOX_DESK_RUN_GUIDANCE.split(f"\n{number}. ", 1)[1]
    return body.split(f"\n{number + 1}. ", 1)[0].splitlines()


def _heads(lines: list[str]) -> list[str]:
    return [line.split(":", 1)[0] for line in lines if ":" in line]


FETCH_STEP = 2
SWEEP_STEP = 3
SKIP_STEP = 4
CLASSIFY_STEP = 5
THREAD_TODO_STEP = 6
OBSERVATIONS_STEP = 9
CURSOR_STEP = 10
BRIEFING_STEP = 11


def test_the_briefing_is_the_five_sections_in_order() -> None:
    assert _heads(_step(BRIEFING_STEP)[1:])[: len(BRIEFING_SECTIONS)] == BRIEFING_SECTIONS


def test_each_thread_class_is_defined_where_threads_are_classified() -> None:
    assert _heads(_step(CLASSIFY_STEP)[1:]) == THREAD_CLASSES


@pytest.mark.parametrize("label", [NEEDS_REPLY_LABEL, WAITING_FOR_REPLY_LABEL])
def test_thread_todos_are_filed_and_briefed_under_the_label_constants(label: str) -> None:
    assert f'["{label}"]' in "\n".join(_step(THREAD_TODO_STEP))
    assert f"your {label} sub-todos" in "\n".join(_step(BRIEFING_STEP))


def test_thread_todos_are_opened_as_the_desks_sub_todos() -> None:
    step = "\n".join(_step(THREAD_TODO_STEP))

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
    step = "\n".join(_step(FETCH_STEP))

    assert "newer_than:1d" in step
    assert "after:<last processed time as Unix seconds>" in step
    assert "never a date or a clock time" in step
    assert '"after:<that time>"' not in step


@pytest.mark.regression
def test_the_query_filters_automated_senders_and_rules_may_change_the_filter() -> None:
    step = "\n".join(_step(FETCH_STEP))

    assert todo_constants.INBOX_DESK_MAIL_FILTER in step
    assert "Standing rules may widen or narrow" in step


@pytest.mark.regression
def test_the_cursor_is_the_first_fetchs_own_stamp() -> None:
    assert agent_constants.TOOL_RESULT_FETCHED_AT_KEY in "\n".join(_step(CURSOR_STEP))


@pytest.mark.regression
def test_a_document_nobody_awaits_an_answer_on_is_fyi_not_to_reply() -> None:
    step = _step(CLASSIFY_STEP)

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


def _thread_guidance() -> str:
    return GMAIL_THREAD_RUN_GUIDANCE.format(ref_id="18c2f0a9b7d4e611")


@pytest.mark.regression
def test_the_fetched_thread_beats_the_canvas_on_whether_a_draft_still_exists() -> None:
    """Regression: a run reported a draft the user had deleted in Gmail, trusting its canvas."""
    guidance = _thread_guidance()

    assert "The thread as fetched is the truth and canvas.md only your notes" in guidance
    assert 'a message whose labels include "DRAFT"' in guidance
    assert "labels" in DEFAULT_SUMMARY_FIELDS


@pytest.mark.regression
def test_a_vanished_draft_is_sent_when_the_user_wrote_since_and_discarded_otherwise() -> None:
    guidance = _thread_guidance()

    assert (
        "If the thread has a message from the user dated after that draft was saved, they "
        "sent it, so re-classify."
    ) in guidance
    assert 'Otherwise they discarded it: record "draft discarded by the user <date>"' in guidance
    assert "the draft id with the date it was saved" in guidance


@pytest.mark.regression
def test_a_discarded_nudge_is_not_drafted_again_for_the_same_follow_up() -> None:
    guidance = _thread_guidance()

    assert "draft no nudge for that follow-up" in guidance
    assert "unless Current State says the user discarded the nudge for it" in guidance


def test_standing_rules_beat_observations_and_both_beat_the_defaults() -> None:
    assert (
        "its Standing rules (the user's instructions) beat its Observations (patterns you "
        "learned), and both beat every default below"
    ) in "\n".join(_step(1))


def test_the_observations_section_has_a_line_format_per_kind() -> None:
    section = todo_prompts.INBOX_DESK_OBSERVATIONS_SECTION

    assert section.startswith(f"## {todo_constants.CANVAS_OBSERVATIONS_SECTION}\n")
    assert re.findall(r"^### (.+)$", section, re.MULTILINE) == ["Senders", "Recurring", "People"]
    assert len(re.findall(r"^<!-- .+ -->$", section, re.MULTILINE)) == 4


def test_observations_are_kept_repeated_bounded_and_announced() -> None:
    step = "\n".join(_step(OBSERVATIONS_STEP))

    assert "only once it repeats" in step
    assert "Senders and Recurring from step 3's counts" in step
    assert f"under {todo_constants.OBSERVATIONS_MAX_CHARS} characters" in step
    assert "Noticed: treating GitHub notifications as low priority" in "\n".join(
        _step(BRIEFING_STEP)
    )


def test_observations_steer_the_query_and_the_classification() -> None:
    assert "-from:<sender>" in "\n".join(_step(FETCH_STEP))
    assert "Observations name as recurring is FYI" in "\n".join(_step(CLASSIFY_STEP))


@pytest.mark.regression
def test_the_sweep_counts_the_whole_window_the_filter_hides() -> None:
    step = "\n".join(_step(SWEEP_STEP))

    assert 'query "<window>"' in step
    assert todo_constants.INBOX_DESK_MAIL_FILTER not in step
    assert "Filtered count: the sweep's total less the messages step 2 fetched" in step
    assert "Filtered: the count only, from step 3" in "\n".join(_step(BRIEFING_STEP))


def test_the_sweep_asks_the_fetch_for_headers_and_never_a_body_or_thread() -> None:
    fields = list(todo_prompts.INBOX_DESK_SWEEP_FIELDS)
    step = "\n".join(_step(SWEEP_STEP))

    sweep = FetchMessagesInput(query="newer_than:1d", fields=fields, body_processing="none")

    assert f'fields {json.dumps(fields)}, body_processing "none"' in step
    assert not message_view_needs_body(sweep.fields, sweep.body_processing)
    assert "Never read a swept message's body or fetch its thread" in step
    assert "GMAIL_FETCH_THREAD" not in step


def test_an_offloaded_sweep_is_counted_by_query_json_grouping_never_read() -> None:
    step = "\n".join(_step(SWEEP_STEP))

    assert 'query_json(path=<that file>, group_count_by="from")' in step
    assert {"path", "group_count_by"} <= set(query_json.args)
