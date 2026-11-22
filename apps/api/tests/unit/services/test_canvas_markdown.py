"""Unit tests for canvas_markdown — section extraction and the legacy split."""

import pytest

from app.constants import task_notes
from app.constants.task_notes import CANVAS_PROMPT_MAX_CHARS
from app.services import canvas_markdown
from app.services.canvas_markdown import (
    bounded_canvas,
    canvas_problems,
    section_body,
    with_missing_sections,
)

LEGACY = """# Fix the thing

## Key Details
- Thread: 18f3a2b
- Email: rahul@example.com

## Current State
Waiting on reply.

## Activity Log
### 2026-08-20
- **Gmail agent**: sent email. Tools: GMAIL_SEND.

## Timeline
- 2026-08-21T09:00:00+00:00 ✓ scheduled run finished
- 2026-08-20T09:00:00+00:00 ▶ scheduled run started

## Context
Some accumulated context.

## Learnings
"""


class TestSectionBody:
    def test_returns_body_up_to_next_heading(self):
        assert section_body(LEGACY, "Current State") == "Waiting on reply."

    def test_none_when_missing(self):
        assert section_body(LEGACY, "Nope") is None

    def test_a_canvas_that_is_not_there_yet_is_an_empty_one_not_a_missing_one(self) -> None:
        """A todo written before the canvas existed has an empty canvas, not no canvas."""
        assert canvas_markdown.remove_section(None, "Activity Log") == ("", None)

    def test_a_todo_without_a_canvas_has_no_section(self):
        assert section_body(None, "Current State") is None

    def test_exact_heading_only(self):
        """'Current' must not match inside '## Current State'."""
        assert section_body(LEGACY, "Current") is None

    def test_first_line_heading(self):
        assert section_body("## Key Details\nx\n", "Key Details") == "x"

    def test_last_section_runs_to_end(self):
        assert section_body("## A\n1\n\n## B\n2\n3\n", "B") == "2\n3"


class TestBoundedCanvas:
    def test_a_canvas_within_the_cap_is_untouched(self) -> None:
        canvas = "x" * CANVAS_PROMPT_MAX_CHARS
        assert bounded_canvas(canvas) is canvas

    def test_an_oversized_canvas_keeps_equal_halves_around_a_marker(self) -> None:
        half = CANVAS_PROMPT_MAX_CHARS // 2
        canvas = "h" * half + "m" * 100 + "t" * half

        assert bounded_canvas(canvas) == (
            "h" * half + "\n[middle of canvas trimmed: 100 characters]\n" + "t" * half
        )

    def test_the_rest_that_fits_beside_the_rules_comes_back_whole(self) -> None:
        head = "## Standing rules\n- r\n\n"
        rest = "## Key Details\n" + "k" * (CANVAS_PROMPT_MAX_CHARS - len(head) - 15)
        canvas = f"{rest}\n\n## Standing rules\n- r\n"

        assert bounded_canvas(canvas) == head + rest

    def test_rules_past_the_whole_budget_leave_only_the_rules(self) -> None:
        rules = "r" * (CANVAS_PROMPT_MAX_CHARS + 1)
        rest = "## Key Details\nk"

        assert bounded_canvas(f"{rest}\n\n## Standing rules\n{rules}\n") == (
            f"## Standing rules\n{rules}\n\n\n[middle of canvas trimmed: {len(rest)} characters]\n"
        )


# The shape of the pitch-prep canvas from 2026-09-26: the removed append-mode tool
# left a "## Activity Log (append)" section, a dated block and a doubled Learnings.
MANGLED = """# GAIA Pitch Prep Research

## Key Details
- Pitch: Dodo Payments Pitch Days.

## Current State
- Research stored in Notion.

## Customer-Depth Research Goal
- What users like and want.

## Learnings

## Learnings

## Activity Log (append)
2026-09-26 01:45 IST: stored the research in Notion.
### 2026-09-26 Paying-user demographics
- 15 external payers
"""


class TestCanvasProblems:
    def test_the_mangled_canvas_names_every_problem(self) -> None:
        assert canvas_problems(MANGLED) == [
            'merge the 2 "## Learnings" sections into one',
            'drop "## Activity Log (append)": GAIA keeps the run log in log.md itself',
            'drop the dated "### YYYY-MM-DD" entries: GAIA keeps the run log in log.md itself',
        ]

    @pytest.mark.parametrize("heading", ["Timeline", "History", "Run log", "Log of runs"])
    def test_a_log_by_any_name_is_activity(self, heading: str) -> None:
        assert canvas_problems(f"## Key Details\n\n## {heading}\n- x\n") == [
            f'drop "## {heading}": GAIA keeps the run log in log.md itself'
        ]

    def test_a_template_canvas_with_its_own_sections_is_fine(self) -> None:
        canvas = "## Key Details\n\n## Current State\n\n## Risks\n\n## Context\n\n## Learnings\n"
        assert canvas_problems(canvas) == []


class TestWithMissingSections:
    def test_each_missing_section_goes_to_its_place_in_the_template_order(self) -> None:
        canvas = "# T\n\n## Key Details\nk\n\n## Learnings\n"

        assert with_missing_sections(canvas) == (
            "# T\n\n## Standing rules\n\n## Done when\n\n## Evidence\n\n## Key Details\nk\n\n## Current State\n\n"
            "## Context\n\n## Learnings\n"
        )

    def test_a_complete_canvas_is_returned_as_is(self) -> None:
        canvas = (
            "## Standing rules\n\n## Done when\n\n## Evidence\n\n## Key Details\n\n## Current State\n\n## Context\n\n"
            "## Learnings\n"
        )
        assert with_missing_sections(canvas) == canvas


class TestWithSectionAppended:
    def test_the_addition_closes_its_section_ahead_of_the_next(self) -> None:
        text = "# O\n\n## Senders\n<!-- c -->\n### a\n\n## People\n"

        assert canvas_markdown.with_section_appended(text, "senders", "### b") == (
            "# O\n\n## Senders\n<!-- c -->\n### a\n\n### b\n\n## People\n"
        )

    def test_a_missing_section_is_added_at_the_end(self) -> None:
        assert canvas_markdown.with_section_appended(
            "# O\n\n## People\n\n", "Recurring", "### r"
        ) == ("# O\n\n## People\n\n## Recurring\n### r\n")

    @pytest.mark.parametrize("tail", ["kX   ", "note   ", "xX"])
    def test_only_trailing_newlines_go_before_an_added_heading(self, tail: str) -> None:
        """The last line's own characters are the user's: only the blank lines under it go."""
        assert canvas_markdown.with_section_appended(f"# O\n{tail}\n\n", "Recurring", "### r") == (
            f"# O\n{tail}\n\n## Recurring\n### r\n"
        )

    @pytest.mark.parametrize("tail", ["kX   ", "note   ", "xX"])
    def test_only_trailing_newlines_go_before_an_appended_line(self, tail: str) -> None:
        text = f"# O\n\n## Senders\n{tail}\n\n## People\n"

        assert canvas_markdown.with_section_appended(text, "Senders", "### b") == (
            f"# O\n\n## Senders\n{tail}\n\n### b\n\n## People\n"
        )


class TestWithMissingSectionsKeepsTheLastLine:
    @pytest.mark.parametrize("last_line", ["- owner: MAX", "- owner: max  "])
    def test_only_trailing_newlines_are_dropped_before_the_added_sections(
        self, last_line: str
    ) -> None:
        canvas = with_missing_sections(f"## Key Details\n{last_line}\n")

        assert canvas == (
            f"## Standing rules\n\n## Done when\n\n## Evidence\n\n## Key Details\n{last_line}\n\n## Current State\n\n"
            "## Context\n\n## Learnings\n"
        )


class TestStandingRules:
    """The user's instructions for a todo: first in the canvas, never trimmed, bounded at write."""

    def test_an_oversized_canvas_keeps_every_rule_and_stays_within_the_cap(self) -> None:
        rules = "- 2026-09-28: skip newsletters\n- 2026-09-29: never draft to the landlord"
        canvas = (
            "## Key Details\n" + "k" * CANVAS_PROMPT_MAX_CHARS + "\n\n"
            f"## Standing rules\n{rules}\n\n"
            "## Context\n" + "c" * CANVAS_PROMPT_MAX_CHARS + "\n\n## Learnings\nlast"
        )

        bounded = bounded_canvas(canvas)

        assert bounded.startswith(f"## Standing rules\n{rules}\n\n## Key Details\n")
        assert bounded.endswith("## Learnings\nlast")
        assert "[middle of canvas trimmed:" in bounded
        assert len(bounded) <= CANVAS_PROMPT_MAX_CHARS + len(
            "\n[middle of canvas trimmed: 00000 characters]\n"
        )

    def test_rules_longer_than_the_cap_are_refused_at_write(self) -> None:
        canvas = f"## Standing rules\n{'r' * (task_notes.STANDING_RULES_MAX_CHARS + 1)}\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert canvas_problems(canvas) == [
            f'shorten "## Standing rules" to {task_notes.STANDING_RULES_MAX_CHARS} characters: '
            "one line per rule, merged where they overlap"
        ]

    def test_rules_at_the_cap_are_accepted(self) -> None:
        canvas = f"## Standing rules\n{'r' * task_notes.STANDING_RULES_MAX_CHARS}\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert canvas_problems(canvas) == []


class TestSectionHeadingCase:
    """One Standing rules section whatever its casing: "## Standing Rules" is the same section."""

    @pytest.mark.regression
    def test_a_title_cased_heading_is_read_as_the_section(self) -> None:
        canvas = "## Standing Rules\n- 2026-09-28: tell me every time\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert section_body(canvas, "Standing rules") == "- 2026-09-28: tell me every time"

    @pytest.mark.regression
    def test_a_write_canonicalizes_the_heading(self) -> None:
        canvas = "## STANDING RULES\n- r\n\n## key details\nk\n"

        assert with_missing_sections(canvas) == (
            "## Standing rules\n- r\n\n## Done when\n\n## Evidence\n\n## Key Details\nk\n\n## Current State\n\n## Context\n\n"
            "## Learnings\n"
        )

    @pytest.mark.regression
    def test_the_cap_holds_for_a_title_cased_heading(self) -> None:
        canvas = f"## Standing Rules\n{'r' * (task_notes.STANDING_RULES_MAX_CHARS + 1)}\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert canvas_problems(canvas) == [
            f'shorten "## Standing rules" to {task_notes.STANDING_RULES_MAX_CHARS} characters: '
            "one line per rule, merged where they overlap"
        ]

    @pytest.mark.regression
    def test_two_casings_of_one_section_are_a_repeat(self) -> None:
        canvas = "## Standing rules\n- a\n\n## Standing Rules\n- b\n"

        assert canvas_problems(canvas) == ['merge the 2 "## Standing rules" sections into one']

    @pytest.mark.regression
    def test_the_prompt_trim_keeps_title_cased_rules_whole(self) -> None:
        canvas = (
            "## Key Details\n" + "k" * CANVAS_PROMPT_MAX_CHARS + "\n\n"
            "## Standing Rules\n- keep me\n\n## Learnings\nlast"
        )

        assert bounded_canvas(canvas).startswith("## Standing rules\n- keep me\n\n## Key Details\n")


class TestTemplateComments:
    """The template's HTML comments are guidance for the writer, never section content."""

    @pytest.mark.regression
    def test_an_all_comment_section_reads_as_empty(self) -> None:
        canvas = "## Standing rules\n<!-- the user's rules,\none line each -->\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert section_body(canvas, "Standing rules") == ""

    @pytest.mark.regression
    def test_a_comment_beside_real_rules_is_dropped(self) -> None:
        canvas = "## Standing rules\n<!-- guidance -->\n- 2026-09-28: skip newsletters\n"

        assert section_body(canvas, "Standing rules") == "- 2026-09-28: skip newsletters"

    @pytest.mark.regression
    def test_template_comments_do_not_count_toward_the_cap(self) -> None:
        rules = "r" * task_notes.STANDING_RULES_MAX_CHARS
        canvas = f"## Standing rules\n<!-- guidance for the writer -->\n{rules}\n\n## Done when\n\n## Evidence\n\n## Key Details\n"

        assert canvas_problems(canvas) == []
