"""Attacks on the plain-language description of a gated call (app/services/hil/describe.py)."""

from datetime import UTC, datetime

import pytest

from app.constants.hil_descriptions import (
    HIL_DESCRIPTION_MAX_DETAILS,
    HIL_DESCRIPTION_PREVIEW_CHARS,
)
from app.models.hil_models import ApprovalDescription, ApprovalDetail
from app.services.hil.describe import describe_action, describe_call
from app.services.hil.when import UserClock, parse_moment, say_moment
from app.utils.general_utils import ELLIPSIS
from app.utils.timezone import Timezone

SEPARATOR = ": "  # between the browser-task lead-in and its task
OPEN, CLOSE = "“", "”"
KOLKATA = Timezone.parse("Asia/Kolkata")
# Monday 16 Nov 2026, 10:00 in Kolkata.
NOW = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)
CLOCK = UserClock(KOLKATA, NOW)

EMAIL_ARGS: dict[str, object] = {
    "recipient_email": "bob@x.com",
    "extra_recipients": ["jane@y.com"],
    "subject": "Q3 numbers",
    "body": "Hi both, attaching the Q3 numbers before Friday's review.",
}
TODO_BEFORE: dict[str, object] = {
    "title": "run5 change-test",
    "due_date": "2026-11-17T00:00:00+05:30",
    "due_date_timezone": "Asia/Calcutta",
    "priority": None,
}
TODO_AFTER: dict[str, object] = {**TODO_BEFORE, "priority": "high"}


def describe(
    tool: str,
    args: dict[str, object],
    integration: str | None = None,
    account: str | None = None,
    amended: dict[str, object] | None = None,
) -> ApprovalDescription:
    return describe_call(tool, args, integration, account, amended_args=amended, clock=CLOCK)


def headline_of(tool: str, args: dict[str, object], integration: str | None = None) -> str:
    return describe(tool, args, integration).headline


def quoted(text: str) -> str:
    return f"{OPEN}{text}{CLOSE}"


def every_word(described: ApprovalDescription) -> str:
    lines = [described.headline, described.question or ""]
    return " ".join([*lines, *(f"{d.label} {d.value}" for d in described.details)])


class TestEmail:
    def test_a_send_asks_one_sentence_naming_the_recipients_and_subject(self) -> None:
        described = describe("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail")

        assert described.headline == f"Email bob@x.com, jane@y.com about {quoted('Q3 numbers')}"
        assert (
            described.question == f"OK to email bob@x.com, jane@y.com about {quoted('Q3 numbers')}?"
        )

    def test_only_the_body_is_a_detail_and_it_sits_behind_the_toggle(self) -> None:
        assert describe("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail").details == [
            ApprovalDetail(
                label="Message",
                value=quoted("Hi both, attaching the Q3 numbers before Friday's review."),
                expandable=True,
            )
        ]

    def test_a_body_that_looks_like_a_date_is_shown_as_written(self) -> None:
        [detail] = describe("GMAIL_SEND_EMAIL", {"body": "2026-11-17"}, "Gmail").details

        assert detail.value == quoted("2026-11-17")

    def test_long_content_is_previewed_with_an_ellipsis(self) -> None:
        details = describe("GMAIL_SEND_EMAIL", {"body": "word " * 100}, "Gmail").details

        preview = details[0].value
        assert preview.endswith(f"{ELLIPSIS}{CLOSE}")
        assert len(preview) == HIL_DESCRIPTION_PREVIEW_CHARS + len(ELLIPSIS) + 2

    def test_a_long_recipient_list_is_capped_with_a_count(self) -> None:
        to = [f"p{i}@x.com" for i in range(7)]

        assert headline_of("GMAIL_SEND_EMAIL", {"extra_recipients": to}) == (
            "Email p0@x.com, p1@x.com, p2@x.com, p3@x.com and 3 more"
        )

    def test_a_list_exactly_at_the_cap_is_shown_whole(self) -> None:
        to = [f"p{i}@x.com" for i in range(4)]

        assert headline_of("GMAIL_SEND_EMAIL", {"extra_recipients": to}) == (
            "Email p0@x.com, p1@x.com, p2@x.com, p3@x.com"
        )

    def test_content_split_across_keys_reads_as_one_message(self) -> None:
        details = describe(
            "GMAIL_REPLY_TO_THREAD", {"message_body": "Thanks,", "body": "see you"}, "Gmail"
        ).details

        assert details == [
            ApprovalDetail(label="Message", value=quoted("Thanks, see you"), expandable=True)
        ]

    def test_a_part_whose_slot_is_empty_is_left_out(self) -> None:
        assert headline_of("GMAIL_REPLY_TO_THREAD", {"body": "ok"}) == "Reply"

    def test_the_closing_verb_names_the_action(self) -> None:
        assert describe("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail").confirm == "send it"


class TestTodo:
    def test_the_founders_todo_reads_as_a_question_for_tomorrow(self) -> None:
        described = describe("create_todo", TODO_BEFORE, "todos")

        assert described.question == (
            f"Want me to add {quoted('run5 change-test')} to your todos for tomorrow?"
        )
        assert described.headline == f"Add {quoted('run5 change-test')} to your todos for tomorrow"
        assert described.details == []

    def test_no_raw_timestamp_timezone_or_category_name_reaches_the_user(self) -> None:
        words = every_word(describe("create_todo", TODO_AFTER, "todos"))

        for raw in ("2026", "T00:00", "+05:30", "Asia/Calcutta", "in todos", "wants to"):
            assert raw not in words

    def test_a_fact_the_sentence_does_not_say_is_a_detail(self) -> None:
        assert describe("create_todo", TODO_AFTER, "todos").details == [
            ApprovalDetail(label="Priority", value="high")
        ]

    def test_a_todo_with_no_due_date_drops_the_when(self) -> None:
        assert headline_of("create_todo", {"title": "Pay rent"}) == (
            f"Add {quoted('Pay rent')} to your todos"
        )


class TestCalendar:
    def test_a_new_event_names_its_title_and_local_time(self) -> None:
        args: dict[str, object] = {
            "events": [{"summary": "Standup", "start_datetime": "2026-11-20T15:00:00"}]
        }

        assert describe("GOOGLECALENDAR_CUSTOM_CREATE_EVENT", args, "Google Calendar").question == (
            f"Want me to add {quoted('Standup')} to your calendar for Fri 3 pm?"
        )

    def test_a_delete_shows_no_calendar_id(self) -> None:
        described = describe(
            "GOOGLECALENDAR_DELETE_EVENT", {"event_id": "abc", "calendar_id": "primary"}
        )

        assert described.question == "OK to delete an event from your calendar?"
        assert described.details == []


class TestFallback:
    def test_an_unmapped_tool_names_its_title_and_integration(self) -> None:
        described = describe(
            "LINEAR_CREATE_LINEAR_ISSUE", {"title": "Fix login", "priority": 2}, "Linear"
        )

        assert described.question == f"OK to create linear issue {quoted('Fix login')} in Linear?"
        assert described.details == [ApprovalDetail(label="Priority", value="2")]

    def test_ids_timezones_and_false_flags_are_never_shown(self) -> None:
        details = describe(
            "NOTION_ARCHIVE_PAGE",
            {
                "page_id": "p1",
                "id": "x",
                "block_ids": ["b1"],
                "timezone": "UTC",
                "start_tz": "Asia/Kolkata",
                "notify": False,
                "permanent": True,
            },
            "Notion",
        ).details

        assert details == [ApprovalDetail(label="Permanent", value="Yes")]

    def test_a_date_argument_reads_in_the_users_zone(self) -> None:
        details = describe("x_tool", {"send_at": "2026-11-16T09:30:00Z"}).details

        assert details == [ApprovalDetail(label="Send at", value="today at 3 pm")]

    def test_a_long_plain_value_sits_behind_the_toggle(self) -> None:
        [detail] = describe("x_tool", {"text": "w " * 60}).details

        assert detail.expandable is True

    def test_blank_and_nested_values_show_nothing(self) -> None:
        details = describe(
            "NOTION_ARCHIVE_PAGE",
            {"note": "  ", "tags": ["q3", "  ", {"x": 1}, ["y"]], "owner": None},
            "Notion",
        ).details

        assert details == [ApprovalDetail(label="Tags", value="q3")]

    def test_hyphens_in_an_unmapped_slug_read_as_spaces(self) -> None:
        assert headline_of("GMAIL_LIST-ALL_LABELS", {}, "Gmail") == "List all labels in Gmail"

    def test_no_more_than_the_detail_cap_is_shown(self) -> None:
        args: dict[str, object] = {f"field_{i}": f"value_{i}" for i in range(10)}

        assert len(describe("x_tool", args).details) == HIL_DESCRIPTION_MAX_DETAILS

    def test_a_named_account_is_named_in_the_sentence(self) -> None:
        described = describe("GMAIL_DELETE_LABEL", {}, "Gmail", "work@acme.com")

        assert described.question == "OK to delete label in Gmail as work@acme.com?"

    def test_the_fallback_confirm_verb_is_generic(self) -> None:
        assert describe("GMAIL_DELETE_LABEL", {}, "Gmail").confirm == "go ahead"

    def test_the_action_keeps_the_integrations_own_case(self) -> None:
        assert describe_action("GMAIL_DELETE_LABEL", "Gmail") == "Delete label in Gmail"
        assert describe_action("create_todo", None) == "Add a todo"

    def test_an_unmapped_tool_with_no_integration_names_only_its_action(self) -> None:
        assert describe_action("archive_old_notes", None) == "Archive old notes"

    def test_a_browser_task_is_named_as_one_without_its_arguments(self) -> None:
        assert describe_action("browser_task", None) == "Start a browser task"


class TestWhen:
    @pytest.mark.parametrize(
        ("value", "said"),
        [
            ("2026-11-16", "today"),
            ("2026-11-15", "yesterday"),
            ("2026-11-17T00:00:00+05:30", "tomorrow"),
            ("2026-11-17T15:00:00+05:30", "tomorrow at 3 pm"),
            ("2026-11-18", "Wed"),
            ("2026-11-20T09:30:00", "Fri 9:30 am"),
            ("2026-11-22T12:00:00", "Sun 12 pm"),
            ("2026-11-23", "Mon 23 Nov"),
            ("2027-01-05", "5 Jan 2027"),
            # 20:00 UTC is 01:30 the next day in Kolkata.
            ("2026-11-16T20:00:00Z", "tomorrow at 1:30 am"),
        ],
    )
    def test_a_moment_reads_relative_to_now_in_kolkata(self, value: str, said: str) -> None:
        moment = parse_moment(value)

        assert moment is not None
        assert say_moment(moment, CLOCK) == said

    def test_now_and_the_moment_both_read_on_the_users_own_calendar(self) -> None:
        # NOW is still Sunday 23:30 in New York, so Monday 15:00 there is tomorrow.
        moment = parse_moment("2026-11-16T20:00:00Z")

        assert moment is not None
        assert (
            say_moment(moment, UserClock(Timezone.parse("America/New_York"), NOW))
            == "tomorrow at 3 pm"
        )

    @pytest.mark.parametrize("value", ["soon", "2026", "2026-13-01", "12:30"])
    def test_anything_but_an_iso_date_is_not_a_moment(self, value: str) -> None:
        assert parse_moment(value) is None


class TestBrowserTaskSummary:
    """browser_task gets a bespoke summary: the LLM's task argument, not the tool name, so the card reads as what will happen."""

    def test_a_missing_task_describes_a_generic_start(self) -> None:
        assert describe("browser_task", {}) == ApprovalDescription(
            action="Start a browser task",
            headline="Start a browser task",
            question="OK to start a browser task?",
            confirm="start it",
            details=[],
        )

    def test_a_task_is_shown_whole_as_its_own_detail(self) -> None:
        assert describe("browser_task", {"task": "Book a flight. Then a hotel."}) == (
            ApprovalDescription(
                action="Start a browser task",
                headline=f"Start a browser task{SEPARATOR}Book a flight",
                question="OK to start a browser task?",
                confirm="start it",
                details=[ApprovalDetail(label="Task", value="Book a flight. Then a hotel.")],
            )
        )

    def test_a_missing_task_argument_falls_back_to_a_generic_line(self) -> None:
        assert headline_of("browser_task", {}) == "Start a browser task"

    def test_a_whitespace_only_task_falls_back_to_a_generic_line(self) -> None:
        assert headline_of("browser_task", {"task": "   "}) == "Start a browser task"

    def test_the_task_is_stripped_of_surrounding_whitespace(self) -> None:
        summary = headline_of("browser_task", {"task": "  Book a flight  "})

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_only_the_first_sentence_is_used_and_its_period_is_dropped(self) -> None:
        summary = headline_of("browser_task", {"task": "Book a flight. Then find a hotel."})

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_a_task_with_no_sentence_break_is_used_whole_when_short(self) -> None:
        summary = headline_of("browser_task", {"task": "Book a flight to Tokyo"})

        assert summary == f"Start a browser task{SEPARATOR}Book a flight to Tokyo"

    def test_a_lead_in_exactly_at_the_clip_boundary_is_kept_whole(self) -> None:
        task = "y" * 140  # no ". " in it, so `first` == the whole (stripped) task

        summary = headline_of("browser_task", {"task": task})

        assert summary == f"Start a browser task{SEPARATOR}{task}"
        assert ELLIPSIS not in summary

    def test_a_lead_in_one_over_the_clip_boundary_is_clipped_with_an_ellipsis(self) -> None:
        task = "y" * 141

        summary = headline_of("browser_task", {"task": task})

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}{ELLIPSIS}"

    def test_a_long_task_with_no_sentence_break_is_clipped_from_the_full_task(self) -> None:
        task = "x" * 200

        summary = headline_of("browser_task", {"task": task})

        assert summary == f"Start a browser task{SEPARATOR}{'x' * 140}{ELLIPSIS}"

    def test_an_empty_lead_in_before_the_first_period_falls_back_to_the_full_task(self) -> None:
        # task.split(". ", 1)[0] is "" here, so the "0 < len(first)" guard must reject
        # it and fall through to clipping the whole task, not render an empty lead-in.
        summary = headline_of("browser_task", {"task": ". rest of the task"})

        assert summary == f"Start a browser task{SEPARATOR}. rest of the task"

    def test_only_the_first_period_space_is_treated_as_a_sentence_break(self) -> None:
        summary = headline_of("browser_task", {"task": "First. Second. Third."})

        assert summary == f"Start a browser task{SEPARATOR}First"

    def test_a_trailing_period_with_no_further_sentence_is_dropped(self) -> None:
        # No ". " anywhere in the task, so `first` is the whole (stripped) task — only
        # the final `.rstrip(".")` removes the trailing period, not the split.
        summary = headline_of("browser_task", {"task": "Book a flight."})

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_the_trailing_strip_removes_only_periods_not_other_characters(self) -> None:
        # `X` is not a character `rstrip(".")` would ever touch — this pins the exact
        # strip set against a mutant that also strips trailing `X`s.
        summary = headline_of("browser_task", {"task": "Book a flightX."})

        assert summary == f"Start a browser task{SEPARATOR}Book a flightX"

    def test_a_one_character_lead_in_is_kept_not_clipped(self) -> None:
        # Pins the lower bound at `0 <`, not `1 <`: a single-character lead-in must
        # still be treated as present and used as-is, not fall through to clip_text.
        summary = headline_of("browser_task", {"task": "A. Rest of stuff here"})

        assert summary == f"Start a browser task{SEPARATOR}A"

    def test_a_140_char_lead_in_from_a_longer_task_is_kept_whole(self) -> None:
        # Distinguishes `<= 140` from `< 140`: here `first` (the lead-in before the
        # first ". ") is exactly 140 chars but `task` (the fallback clip_text source)
        # is much longer, so a boundary off-by-one would clip a sentence that fits.
        task = "y" * 140 + ". additional sentence"

        summary = headline_of("browser_task", {"task": task})

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}"
        assert ELLIPSIS not in summary


class TestAmendedCall:
    """Run 4 bug 20: the re-ask after "yes but make it high priority" must lead with the change."""

    def test_the_re_ask_leads_with_the_change(self) -> None:
        described = describe("create_todo", TODO_AFTER, "todos", amended=TODO_BEFORE)

        assert described.changes == [ApprovalDetail(label="Priority", value="high")]
        assert described.change_note == "Updated priority to high"
        assert described.question == "Updated priority to high — still OK to add it?"

    def test_a_moved_date_is_named_in_words(self) -> None:
        moved = {**TODO_BEFORE, "due_date": "2026-11-20T00:00:00+05:30"}

        described = describe("create_todo", moved, "todos", amended=TODO_BEFORE)

        assert described.change_note == "Updated due date to Fri"

    def test_a_first_ask_names_no_change(self) -> None:
        described = describe("create_todo", TODO_AFTER, "todos")

        assert described.changes == []
        assert described.change_note is None

    def test_a_re_ask_that_changed_nothing_asks_the_plain_question(self) -> None:
        described = describe("create_todo", TODO_BEFORE, "todos", amended=TODO_BEFORE)

        assert described.change_note is None
        assert described.question is not None
        assert described.question.startswith("Want me to add")
