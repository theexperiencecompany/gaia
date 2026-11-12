"""Attacks on the plain-language description of a gated call (app/services/hil/describe.py)."""

from app.constants.hil_descriptions import (
    HIL_DESCRIPTION_MAX_DETAILS,
    HIL_DESCRIPTION_PREVIEW_CHARS,
)
from app.models.hil_models import ApprovalDescription, ApprovalDetail
from app.services.hil.describe import describe_call
from app.utils.general_utils import ELLIPSIS

SEPARATOR = ": "  # between the browser-task lead-in and its task

EMAIL_ARGS: dict[str, object] = {
    "recipient_email": "bob@x.com",
    "extra_recipients": ["jane@y.com"],
    "subject": "Q3 numbers",
    "body": "Hi both, attaching the Q3 numbers before Friday's review.",
}


def headline(tool: str, args: dict[str, object], integration: str | None) -> str:
    return describe_call(tool, args, integration).headline


class TestCuratedTool:
    def test_an_email_reads_as_a_sentence_naming_every_recipient_and_the_subject(self) -> None:
        assert (
            headline("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail")
            == 'Send an email to bob@x.com, jane@y.com: "Q3 numbers"'
        )

    def test_details_are_labelled_lines_in_the_curated_order(self) -> None:
        details = describe_call("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail").details

        assert details == [
            ApprovalDetail(label="To", value="bob@x.com, jane@y.com"),
            ApprovalDetail(label="Subject", value="Q3 numbers"),
            ApprovalDetail(
                label="Message",
                value='"Hi both, attaching the Q3 numbers before Friday\'s review."',
            ),
        ]

    def test_the_closing_verb_names_the_action(self) -> None:
        assert describe_call("GMAIL_SEND_EMAIL", EMAIL_ARGS, "Gmail").confirm == "send it"

    def test_long_content_is_previewed_with_an_ellipsis(self) -> None:
        body = "word " * 100
        details = describe_call("GMAIL_SEND_EMAIL", {"body": body}, "Gmail").details

        preview = details[0].value
        assert preview.endswith(f'{ELLIPSIS}"')
        assert len(preview) == HIL_DESCRIPTION_PREVIEW_CHARS + len(ELLIPSIS) + 2

    def test_a_place_detail_joins_the_headline_with_its_preposition(self) -> None:
        assert (
            headline("GOOGLECALENDAR_DELETE_EVENT", {"calendar_id": "Work"}, "Google Calendar")
            == "Delete a calendar event from Work"
        )

    def test_a_long_recipient_list_is_capped_with_a_count(self) -> None:
        to = [f"p{i}@x.com" for i in range(7)]
        details = describe_call("GMAIL_SEND_EMAIL", {"extra_recipients": to}, None).details

        assert details[0].value == "p0@x.com, p1@x.com, p2@x.com, p3@x.com and 3 more"

    def test_a_list_exactly_at_the_cap_is_shown_whole(self) -> None:
        to = [f"p{i}@x.com" for i in range(4)]
        details = describe_call("GMAIL_SEND_EMAIL", {"extra_recipients": to}, None).details

        assert details[0].value == "p0@x.com, p1@x.com, p2@x.com, p3@x.com"

    def test_content_split_across_keys_reads_as_one_message(self) -> None:
        details = describe_call(
            "GMAIL_REPLY_TO_THREAD", {"message_body": "Thanks,", "body": "see you"}, "Gmail"
        ).details

        assert details == [ApprovalDetail(label="Message", value='"Thanks, see you"')]


class TestFallback:
    def test_blank_and_nested_values_show_nothing(self) -> None:
        details = describe_call(
            "NOTION_ARCHIVE_PAGE",
            {"note": "  ", "tags": ["q3", "  ", {"x": 1}, ["y"]], "owner": None},
            "Notion",
        ).details

        assert details == [ApprovalDetail(label="Tags", value="q3")]

    def test_an_unmapped_tool_is_named_in_words_with_its_integration(self) -> None:
        assert headline("GMAIL_DELETE_LABEL", {}, "Gmail") == "Delete label in Gmail"

    def test_hyphens_in_an_unmapped_slug_read_as_spaces(self) -> None:
        assert headline("GMAIL_LIST-ALL_LABELS", {}, "Gmail") == "List all labels in Gmail"

    def test_short_scalars_and_lists_become_humanised_details(self) -> None:
        details = describe_call(
            "NOTION_ARCHIVE_PAGE",
            {"page_title": "Roadmap", "tags": ["q3", "plan"], "meta": {"x": 1}},
            "Notion",
        ).details

        assert details == [
            ApprovalDetail(label="Page title", value="Roadmap"),
            ApprovalDetail(label="Tags", value="q3, plan"),
        ]

    def test_no_more_than_the_detail_cap_is_shown(self) -> None:
        args = {f"field_{i}": f"value_{i}" for i in range(10)}

        assert len(describe_call("x_tool", args, None).details) == HIL_DESCRIPTION_MAX_DETAILS

    def test_a_named_account_is_named_in_the_headline(self) -> None:
        assert (
            describe_call("GMAIL_DELETE_LABEL", {}, "Gmail", "work@acme.com").headline
            == "Delete label in Gmail (as work@acme.com)"
        )

    def test_the_fallback_confirm_verb_is_generic(self) -> None:
        assert describe_call("GMAIL_DELETE_LABEL", {}, "Gmail").confirm == "go ahead"


class TestBrowserTaskSummary:
    """browser_task gets a bespoke summary: the LLM's task argument, not the tool name, so the card reads as what will happen."""

    def test_a_missing_task_describes_a_generic_start(self) -> None:
        assert describe_call("browser_task", {}, None) == ApprovalDescription(
            action="Start a browser task",
            headline="Start a browser task",
            confirm="start it",
            details=[],
        )

    def test_a_task_is_shown_whole_as_its_own_detail(self) -> None:
        assert describe_call("browser_task", {"task": "Book a flight. Then a hotel."}, None) == (
            ApprovalDescription(
                action="Start a browser task",
                headline=f"Start a browser task{SEPARATOR}Book a flight",
                confirm="start it",
                details=[ApprovalDetail(label="Task", value="Book a flight. Then a hotel.")],
            )
        )

    def test_a_missing_task_argument_falls_back_to_a_generic_line(self) -> None:
        assert headline("browser_task", {}, None) == "Start a browser task"

    def test_a_whitespace_only_task_falls_back_to_a_generic_line(self) -> None:
        assert headline("browser_task", {"task": "   "}, None) == "Start a browser task"

    def test_the_task_is_stripped_of_surrounding_whitespace(self) -> None:
        summary = headline("browser_task", {"task": "  Book a flight  "}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_only_the_first_sentence_is_used_and_its_period_is_dropped(self) -> None:
        summary = headline("browser_task", {"task": "Book a flight. Then find a hotel."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_a_task_with_no_sentence_break_is_used_whole_when_short(self) -> None:
        summary = headline("browser_task", {"task": "Book a flight to Tokyo"}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight to Tokyo"

    def test_a_lead_in_exactly_at_the_clip_boundary_is_kept_whole(self) -> None:
        task = "y" * 140  # no ". " in it, so `first` == the whole (stripped) task

        summary = headline("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{task}"
        assert ELLIPSIS not in summary

    def test_a_lead_in_one_over_the_clip_boundary_is_clipped_with_an_ellipsis(self) -> None:
        task = "y" * 141

        summary = headline("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}{ELLIPSIS}"

    def test_a_long_task_with_no_sentence_break_is_clipped_from_the_full_task(self) -> None:
        task = "x" * 200

        summary = headline("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'x' * 140}{ELLIPSIS}"

    def test_an_empty_lead_in_before_the_first_period_falls_back_to_the_full_task(self) -> None:
        # task.split(". ", 1)[0] is "" here, so the "0 < len(first)" guard must reject
        # it and fall through to clipping the whole task, not render an empty lead-in.
        summary = headline("browser_task", {"task": ". rest of the task"}, None)

        assert summary == f"Start a browser task{SEPARATOR}. rest of the task"

    def test_only_the_first_period_space_is_treated_as_a_sentence_break(self) -> None:
        summary = headline("browser_task", {"task": "First. Second. Third."}, None)

        assert summary == f"Start a browser task{SEPARATOR}First"

    def test_a_trailing_period_with_no_further_sentence_is_dropped(self) -> None:
        # No ". " anywhere in the task, so `first` is the whole (stripped) task — only
        # the final `.rstrip(".")` removes the trailing period, not the split.
        summary = headline("browser_task", {"task": "Book a flight."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flight"

    def test_the_trailing_strip_removes_only_periods_not_other_characters(self) -> None:
        # `X` is not a character `rstrip(".")` would ever touch — this pins the exact
        # strip set against a mutant that also strips trailing `X`s.
        summary = headline("browser_task", {"task": "Book a flightX."}, None)

        assert summary == f"Start a browser task{SEPARATOR}Book a flightX"

    def test_a_one_character_lead_in_is_kept_not_clipped(self) -> None:
        # Pins the lower bound at `0 <`, not `1 <`: a single-character lead-in must
        # still be treated as present and used as-is, not fall through to clip_text.
        summary = headline("browser_task", {"task": "A. Rest of stuff here"}, None)

        assert summary == f"Start a browser task{SEPARATOR}A"

    def test_a_140_char_lead_in_from_a_longer_task_is_kept_whole(self) -> None:
        # Distinguishes `<= 140` from `< 140`: here `first` (the lead-in before the
        # first ". ") is exactly 140 chars but `task` (the fallback clip_text source)
        # is much longer, so a boundary off-by-one would clip a sentence that fits.
        task = "y" * 140 + ". additional sentence"

        summary = headline("browser_task", {"task": task}, None)

        assert summary == f"Start a browser task{SEPARATOR}{'y' * 140}"
        assert ELLIPSIS not in summary
