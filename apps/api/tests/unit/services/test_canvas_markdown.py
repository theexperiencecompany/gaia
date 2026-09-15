"""Unit tests for canvas_markdown — section extraction and the legacy split."""

from datetime import UTC, datetime

import pytest

from app.services.canvas_markdown import (
    _extract_entries,
    _line_timestamp,
    _remove_section,
    section_body,
    split_legacy_canvas,
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
