"""Unit tests for canvas_markdown — section extraction and the legacy split."""

from datetime import UTC, datetime

import pytest

from app.constants import todos as todo_constants
from app.constants.todos import CANVAS_PROMPT_MAX_CHARS
from app.services.canvas_markdown import (
    _extract_entries,
    _line_timestamp,
    _remove_section,
    bounded_canvas,
    canvas_problems,
    normalize_canvas,
    section_body,
    split_legacy_canvas,
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

    def test_exact_heading_only(self):
        """'Current' must not match inside '## Current State'."""
        assert section_body(LEGACY, "Current") is None

    def test_first_line_heading(self):
        assert section_body("## Key Details\nx\n", "Key Details") == "x"

    def test_last_section_runs_to_end(self):
        assert section_body("## A\n1\n\n## B\n2\n3\n", "B") == "2\n3"


class TestSplitLegacyCanvas:
    def test_moves_activity_and_timeline_out(self):
        canvas, activity = split_legacy_canvas(LEGACY)

        assert "## Activity Log" not in canvas
        assert "## Timeline" not in canvas
        assert "## Key Details" in canvas
        assert "## Context" in canvas
        assert "## Learnings" in canvas
        assert activity is not None
        assert "sent email" in activity
        assert "scheduled run finished" in activity

    def test_timeline_reordered_chronologically(self):
        """Legacy Timeline inserted newest-first; activity.md is oldest-first."""
        _, activity = split_legacy_canvas(LEGACY)

        assert activity is not None
        assert activity.index("run started") < activity.index("run finished")

    def test_activity_precedes_timeline_entries(self):
        _, activity = split_legacy_canvas(LEGACY)

        assert activity is not None
        assert activity.index("sent email") < activity.index("run started")

    def test_none_when_nothing_to_move(self):
        canvas = "# T\n\n## Key Details\nx\n\n## Learnings\n"

        assert split_legacy_canvas(canvas) == (canvas, None)

    def test_empty_legacy_sections_are_dropped_without_activity(self):
        canvas = "# T\n\n## Activity Log\n\n## Timeline\n\n## Learnings\n"

        new_canvas, activity = split_legacy_canvas(canvas)

        assert activity is None
        assert "## Activity Log" not in new_canvas
        assert "## Timeline" not in new_canvas

    def test_entries_appended_after_learnings_are_rescued(self):
        """The production symptom: append mode dumped activity under Learnings."""
        canvas = (
            "# T\n\n## Key Details\nx\n\n## Learnings\n\n"
            "### 2026-08-20\n- **Gmail agent**: sent email.\n"
            "### 2026-08-21\n- **Slack agent**: posted update.\n"
        )

        new_canvas, activity = split_legacy_canvas(canvas)

        assert activity is not None
        assert "sent email" in activity and "posted update" in activity
        assert "sent email" not in new_canvas
        assert section_body(new_canvas, "Learnings") == ""

    def test_removed_section_leaves_one_blank_line_before_the_next_heading(self):
        canvas = "# T\n\n## Current State\nWaiting.\n\n## Timeline\n- x\n\n## Learnings\n"

        new_canvas, _ = split_legacy_canvas(canvas)

        assert new_canvas == "# T\n\n## Current State\nWaiting.\n\n## Learnings\n"

    def test_real_learnings_are_kept(self):
        canvas = "# T\n\n## Learnings\nSarah replies in 2-3 days.\n\n## Activity Log\n- did x\n"

        new_canvas, activity = split_legacy_canvas(canvas)

        assert section_body(new_canvas, "Learnings") == "Sarah replies in 2-3 days."
        assert activity == "- did x"

    def test_interleaved_dates_merge_chronologically_across_sources(self):
        """Activity Log / Learnings / Timeline entries interleave by date, not by source."""
        canvas = (
            "# T\n\n## Key Details\nk\n\n"
            "## Activity Log\n- 2026-08-22T10:00:00+00:00 activity late\n\n"
            "## Learnings\nReal learning.\n\n### 2026-08-20\n- rescued early\n\n"
            "## Timeline\n- 2026-08-21T10:00:00+00:00 timeline middle\n"
        )

        new_canvas, activity = split_legacy_canvas(canvas)

        # Exact output, not just relative order: pins the sort key (a lambda over
        # the timestamp) and the blank-line join separator — a looser index()
        # check let those mutants survive.
        assert activity == (
            "### 2026-08-20\n- rescued early\n\n"
            "- 2026-08-21T10:00:00+00:00 timeline middle\n\n"
            "- 2026-08-22T10:00:00+00:00 activity late"
        )
        assert new_canvas == "# T\n\n## Key Details\nk\n\n## Learnings\nReal learning.\n"

    def test_idempotent(self):
        once, activity = split_legacy_canvas(LEGACY)

        assert split_legacy_canvas(once) == (once, None)
        assert activity is not None

    def test_blank_section_at_start_yields_leading_newline_not_none(self):
        """A section removed with no preceding content leaves a leading newline, not empty or None."""
        new_canvas, activity = split_legacy_canvas("## Timeline\n- a")

        assert new_canvas == "\n"
        assert activity == "- a"

    def test_undated_block_is_kept_verbatim_and_trailing_lines_join_with_newline(self):
        """A ### block with no date is undated; the surrounding text rejoins with a newline, not concatenation."""
        dated, undated = _extract_entries("### nope\ntail one\ntail two")

        assert dated == []
        assert undated == ["### nope", "tail one", "tail two"]

    def test_undated_dated_block_keeps_the_block_text(self):
        """A ###-headed block whose date does not parse is kept verbatim in the undated list, not dropped to None."""
        dated, undated = _extract_entries("### 2026-13-99\n- nonsense")

        assert dated == []
        assert undated == ["### 2026-13-99\n- nonsense"]

    def test_naive_timestamps_are_tagged_utc(self):
        """A timeline line with no offset is assumed UTC; an aware one is kept as-is."""
        assert _line_timestamp("- 2026-08-21T09:00:00 rest") == datetime(
            2026, 8, 21, 9, 0, tzinfo=UTC
        )
        assert _line_timestamp("- 2026-08-21T09:00:00+02:00 rest") == datetime.fromisoformat(
            "2026-08-21T09:00:00+02:00"
        )

    def test_root_level_section_removal_has_no_extra_blank_line(self):
        """The first heading has no preceding content, so blank-line preservation must not fire."""
        new_canvas, activity = split_legacy_canvas("## Timeline\n- a\n\n## B\n2\n")

        assert new_canvas == "\n## B\n2\n"
        assert activity == "- a"

    def test_multiple_dated_blocks_and_undated_text_merge(self):
        """Each ###-headed block is captured whole, and text after the last block is scanned for standalone entries."""
        dated, undated = _extract_entries(
            "### 2026-01-01\n- early\ntail one\ntail two\n### 2026-01-02\n- late"
        )

        assert [entry for _, entry in dated] == [
            "### 2026-01-01\n- early\ntail one\ntail two",
            "### 2026-01-02\n- late",
        ]
        assert undated == []

    def test_blank_line_before_dated_content_does_not_stop_the_scan(self):
        """Blank lines are skipped, not a stop signal — an entry after one is still collected."""
        dated, undated = _extract_entries(
            "note\n\n- 2026-01-02T00:00:00+00:00 late\n- 2026-01-03T00:00:00+00:00 later"
        )

        assert [entry for _, entry in dated] == [
            "- 2026-01-02T00:00:00+00:00 late",
            "- 2026-01-03T00:00:00+00:00 later",
        ]
        assert undated == ["note"]

    def test_dated_entries_merge_chronologically_across_sections(self):
        """Entries from two sections, deliberately out of order and reverse-alphabetical, pin sorting by date not text."""
        _, activity = split_legacy_canvas(
            "## Activity Log\n"
            "- 2026-08-24T10:00:00+00:00 alpha\n"
            "- 2026-08-22T10:00:00+00:00 zulu\n"
            "- 2026-08-20T10:00:00+00:00 mike\n\n"
            "## Timeline\n"
            "- 2026-08-23T10:00:00+00:00 yankee\n"
            "- 2026-08-21T10:00:00+00:00 xray\n"
        )

        assert activity == (
            "- 2026-08-20T10:00:00+00:00 mike\n\n"
            "- 2026-08-21T10:00:00+00:00 xray\n\n"
            "- 2026-08-22T10:00:00+00:00 zulu\n\n"
            "- 2026-08-23T10:00:00+00:00 yankee\n\n"
            "- 2026-08-24T10:00:00+00:00 alpha"
        )

    def test_same_timestamp_entries_keep_source_order(self):
        """Same-date entries keep source order (stable sort on timestamp) — sorting by text would swap them."""
        _, activity = split_legacy_canvas(
            "## Activity Log\n- 2026-08-20T10:00:00+00:00 zulu\n- 2026-08-20T10:00:00+00:00 alpha\n"
        )

        assert activity == ("- 2026-08-20T10:00:00+00:00 zulu\n\n- 2026-08-20T10:00:00+00:00 alpha")

    def test_undated_entry_sorts_after_a_same_date_dated_entry(self):
        """An undated line whose text sorts first still follows a same-date entry — the key is the timestamp."""
        _, activity = split_legacy_canvas(
            "## Activity Log\n- a-note\n- 2026-08-20T10:00:00+00:00 z\n"
        )

        assert activity == "- 2026-08-20T10:00:00+00:00 z\n\n- a-note"

    def test_trailing_whitespace_before_a_removed_section_is_preserved(self):
        """Only newlines are stripped from the preceding text — a trailing space stays."""
        new_canvas, _ = split_legacy_canvas("# T \n\n## Timeline\n- a\n\n## B\n2\n")

        assert new_canvas == "# T \n\n## B\n2\n"

    def test_trailing_non_newline_whitespace_chars_are_preserved(self):
        """Only the newline is stripped: a trailing space or char before it stays."""
        assert (
            split_legacy_canvas("# T X\n\n## Timeline\n- a\n\n## B\n2\n")[0] == "# T X\n\n## B\n2\n"
        )
        assert (
            split_legacy_canvas("# T\t\n\n## Timeline\n- a\n\n## B\n2\n")[0] == "# T\t\n\n## B\n2\n"
        )

    def test_a_rescued_block_with_an_unparseable_date_is_kept_verbatim(self):
        """A ### YYYY-MM-DD block whose date fails to parse (month 13) is rescued as undated text, not dropped to None."""
        _, activity = split_legacy_canvas("# T\n\n## Learnings\n\n### 2026-13-99\n- nonsense\n")

        assert activity == "### 2026-13-99\n- nonsense"

    def test_section_between_content_keeps_blank_line_before_the_next_heading(self):
        """A removed section with content both before and after preserves the blank line before the next heading."""
        new_canvas, activity = split_legacy_canvas("pre\n\n## Timeline\n- a\n\n## B\n2\n")

        assert new_canvas == "pre\n\n## B\n2\n"
        assert activity == "- a"

    def test_remove_section_is_a_noop_when_absent(self):
        assert _remove_section("# T\n\n## B\n2\n", "Missing") == ("# T\n\n## B\n2\n", None)


@pytest.mark.parametrize("heading", ["Activity Log", "Timeline"])
def test_split_removes_each_legacy_section_alone(heading: str):
    canvas = f"# T\n\n## Key Details\nk\n\n## {heading}\n- entry\n\n## Learnings\n"

    new_canvas, activity = split_legacy_canvas(canvas)

    assert f"## {heading}" not in new_canvas
    assert activity == "- entry"


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
            'move "## Activity Log (append)" into activity.md',
            'move the dated "### YYYY-MM-DD" entries into activity.md',
        ]

    @pytest.mark.parametrize("heading", ["Timeline", "History", "Run log", "Log of runs"])
    def test_a_log_by_any_name_is_activity(self, heading: str) -> None:
        assert canvas_problems(f"## Key Details\n\n## {heading}\n- x\n") == [
            f'move "## {heading}" into activity.md'
        ]

    def test_a_template_canvas_with_its_own_sections_is_fine(self) -> None:
        canvas = "## Key Details\n\n## Current State\n\n## Risks\n\n## Context\n\n## Learnings\n"
        assert canvas_problems(canvas) == []


class TestWithMissingSections:
    def test_each_missing_section_goes_to_its_place_in_the_template_order(self) -> None:
        canvas = "# T\n\n## Key Details\nk\n\n## Learnings\n"

        assert with_missing_sections(canvas) == (
            "# T\n\n## Standing rules\n\n## Key Details\nk\n\n## Current State\n\n"
            "## Context\n\n## Learnings\n"
        )

    def test_a_complete_canvas_is_returned_as_is(self) -> None:
        canvas = (
            "## Standing rules\n\n## Key Details\n\n## Current State\n\n## Context\n\n"
            "## Learnings\n"
        )
        assert with_missing_sections(canvas) == canvas


class TestNormalizeCanvas:
    def test_the_mangled_canvas_becomes_a_recall_doc(self) -> None:
        canvas, moved = normalize_canvas(MANGLED)

        assert canvas_problems(canvas) == []
        assert canvas.count("## Learnings") == 1
        assert "## Customer-Depth Research Goal\n- What users like and want." in canvas
        assert "## Context" in canvas
        assert moved is not None
        assert "stored the research in Notion" in moved
        assert "15 external payers" in moved

    def test_normalizing_is_idempotent(self) -> None:
        canvas, _ = normalize_canvas(MANGLED)

        assert normalize_canvas(canvas) == (canvas, None)

    def test_repeated_sections_keep_every_body(self) -> None:
        canvas, moved = normalize_canvas(
            "## Key Details\na\n\n## Current State\n\n## Key Details\nb\n\n"
            "## Context\n\n## Learnings\n"
        )

        assert moved is None
        assert canvas.count("## Key Details") == 1
        assert section_body(canvas, "Key Details") == "a\nb"

    def test_dated_blocks_under_any_section_move_out(self) -> None:
        """Regression: a dated block under Context survived the sweep, and every later write was refused."""
        canvas, moved = normalize_canvas(
            "## Key Details\n\n## Current State\n\n## Context\nWhy we track it.\n\n"
            "### 2026-09-26\n- noted\n\n## Learnings\n\n## Research\n### 2026-09-27 call\n- done\n"
        )

        assert canvas_problems(canvas) == []
        assert moved == "### 2026-09-26\n- noted\n\n### 2026-09-27 call\n- done"
        assert section_body(canvas, "Context") == "Why we track it."
        assert "## Research" in canvas
        assert normalize_canvas(canvas) == (canvas, None)

    def test_repeats_merge_into_the_first_with_sections_a_blank_line_apart(self) -> None:
        canvas, moved = normalize_canvas(
            "## Key Details\na\n\n## Current State\ns\n\n## Key Details\nb\n\n"
            "## Context\n\n## Learnings\nx\n\n## Learnings\ny"
        )

        assert moved is None
        assert canvas == (
            "## Standing rules\n\n## Key Details\na\nb\n\n## Current State\ns\n\n## Context\n\n"
            "## Learnings\nx\ny\n"
        )

    def test_a_heading_with_trailing_spaces_is_the_same_section(self) -> None:
        """Regression: "## Context " twice survived the sweep, and the write check refused the result."""
        canvas, _ = normalize_canvas(
            "## Key Details\n\n## Current State\n\n## Context \nc1\n\n## Context\nc2\n\n## Learnings\n"
        )

        assert canvas_problems(canvas) == []
        assert section_body(canvas, "Context") == "c1\nc2"

    def test_every_log_section_moves_out_a_blank_line_apart(self) -> None:
        canvas, moved = normalize_canvas(
            "## Key Details\n\n## Activity Log\n- a\n\n## History\n- b\n\n"
            "## Current State\n\n## Context\n\n## Learnings\n"
        )

        assert moved == "- a\n\n- b"
        assert canvas == (
            "## Standing rules\n\n## Key Details\n\n## Current State\n\n## Context\n\n"
            "## Learnings\n"
        )

    def test_the_result_ends_in_exactly_one_newline(self) -> None:
        canvas, _ = normalize_canvas(
            "## Key Details\nk\n\n## Current State\n\n## Context\n\n## Learnings\nl"
        )

        assert canvas == (
            "## Standing rules\n\n## Key Details\nk\n\n## Current State\n\n## Context\n\n"
            "## Learnings\nl\n"
        )

    @pytest.mark.parametrize(
        "preamble",
        ["# Ship the BOX", "# Ship the box "],
        ids=["ends-in-a-letter", "ends-in-a-space"],
    )
    def test_merging_keeps_the_title_line_and_indented_bodies_as_written(
        self, preamble: str
    ) -> None:
        canvas, _ = normalize_canvas(
            f"{preamble}\n\n## Key Details\n  - owner: MAX\n\n## Current State\n\n"
            "## Key Details\n  - due: Friday X\n\n## Context\n\n## Learnings\n"
        )

        assert canvas == (
            f"{preamble}\n\n## Standing rules\n\n## Key Details\n  - owner: MAX\n  - due: Friday X\n\n"
            "## Current State\n\n## Context\n\n## Learnings\n"
        )


class TestWithMissingSectionsKeepsTheLastLine:
    @pytest.mark.parametrize("last_line", ["- owner: MAX", "- owner: max  "])
    def test_only_trailing_newlines_are_dropped_before_the_added_sections(
        self, last_line: str
    ) -> None:
        canvas = with_missing_sections(f"## Key Details\n{last_line}\n")

        assert canvas == (
            f"## Standing rules\n\n## Key Details\n{last_line}\n\n## Current State\n\n"
            "## Context\n\n## Learnings\n"
        )


class TestStandingRules:
    """The user's instructions for a todo: first in the canvas, never trimmed, bounded at write."""

    def test_a_canvas_from_before_the_section_gains_it_first(self) -> None:
        canvas = "# T\n\n## Key Details\nk\n\n## Current State\n\n## Context\n\n## Learnings\n"

        assert normalize_canvas(canvas) == (
            "# T\n\n## Standing rules\n\n## Key Details\nk\n\n## Current State\n\n"
            "## Context\n\n## Learnings\n",
            None,
        )

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
        canvas = f"## Standing rules\n{'r' * (todo_constants.STANDING_RULES_MAX_CHARS + 1)}\n\n## Key Details\n"

        assert canvas_problems(canvas) == [
            f'shorten "## Standing rules" to {todo_constants.STANDING_RULES_MAX_CHARS} characters: '
            "one line per rule, merged where they overlap"
        ]

    def test_rules_at_the_cap_are_accepted(self) -> None:
        canvas = f"## Standing rules\n{'r' * todo_constants.STANDING_RULES_MAX_CHARS}\n\n## Key Details\n"

        assert canvas_problems(canvas) == []


class TestSectionHeadingCase:
    """One Standing rules section whatever its casing: "## Standing Rules" is the same section."""

    @pytest.mark.regression
    def test_a_title_cased_heading_is_read_as_the_section(self) -> None:
        canvas = "## Standing Rules\n- 2026-09-28: tell me every time\n\n## Key Details\n"

        assert section_body(canvas, "Standing rules") == "- 2026-09-28: tell me every time"

    @pytest.mark.regression
    def test_a_title_cased_heading_is_not_added_twice(self) -> None:
        canvas = (
            "# T\n\n## Standing Rules\n- 2026-09-28: tell me every time\n\n## Key Details\nk\n\n"
            "## Current State\n\n## Context\n\n## Learnings\n"
        )

        assert normalize_canvas(canvas) == (
            "# T\n\n## Standing rules\n- 2026-09-28: tell me every time\n\n## Key Details\nk\n\n"
            "## Current State\n\n## Context\n\n## Learnings\n",
            None,
        )

    @pytest.mark.regression
    def test_a_write_canonicalizes_the_heading(self) -> None:
        canvas = "## STANDING RULES\n- r\n\n## key details\nk\n"

        assert with_missing_sections(canvas) == (
            "## Standing rules\n- r\n\n## Key Details\nk\n\n## Current State\n\n## Context\n\n"
            "## Learnings\n"
        )

    @pytest.mark.regression
    def test_the_cap_holds_for_a_title_cased_heading(self) -> None:
        canvas = f"## Standing Rules\n{'r' * (todo_constants.STANDING_RULES_MAX_CHARS + 1)}\n\n## Key Details\n"

        assert canvas_problems(canvas) == [
            f'shorten "## Standing rules" to {todo_constants.STANDING_RULES_MAX_CHARS} characters: '
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
        canvas = "## Standing rules\n<!-- the user's rules,\none line each -->\n\n## Key Details\n"

        assert section_body(canvas, "Standing rules") == ""

    @pytest.mark.regression
    def test_a_comment_beside_real_rules_is_dropped(self) -> None:
        canvas = "## Standing rules\n<!-- guidance -->\n- 2026-09-28: skip newsletters\n"

        assert section_body(canvas, "Standing rules") == "- 2026-09-28: skip newsletters"

    @pytest.mark.regression
    def test_template_comments_do_not_count_toward_the_cap(self) -> None:
        rules = "r" * todo_constants.STANDING_RULES_MAX_CHARS
        canvas = f"## Standing rules\n<!-- guidance for the writer -->\n{rules}\n\n## Key Details\n"

        assert canvas_problems(canvas) == []
