"""Unit tests for app.agents.tools.tracked_todo_tools.

Heavy focus on the pure helper functions (canvas patching, datetime/recurrence
validation, update-field builders) — no mocking needed, and this is exactly
where the real bugs in this file were hiding: _patch_canvas_section silently
duplicated a section instead of replacing it when that section was the first
line of the canvas, and both _parse_iso_future_datetime and
_build_scheduled_at_update raised an unhandled TypeError (instead of a clean
validation error) on a timezone-naive ISO datetime. Both are fixed at the root
in tracked_todo_tools.py; the tests here pin the fix down.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.agents.tools.tracked_todo_tools import (
    _apply_cron_first_fire,
    _build_clearable_datetime_update,
    _build_labels_update,
    _build_list_detail_parts,
    _build_priority_update,
    _build_recurrence_update,
    _build_scheduled_at_update,
    _compute_first_fire_from_cron,
    _format_create_output,
    _format_first_fire_note,
    _format_tracked_todo_full,
    _get_user_tz,
    _is_cron_expression,
    _parse_iso_future_datetime,
    _patch_canvas_section,
    _persist_scheduling_fields,
    _resolve_cron_first_fire,
    _resolve_first_fire,
    _schedule_execution_after_create,
    _validate_recurrence_format,
    complete_tracked_todo,
    create_tracked_todo,
    list_tracked_todos,
    search_todo_context,
    update_tracked_todo,
    update_tracked_todo_canvas,
)
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import Priority, TodoDocument, TodoResponse, TodoUpdate
from app.utils.timezone import Timezone
from shared.py.wide_events import spawn_logged_task

_FUTURE = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
_FUTURE_ISO = _FUTURE.isoformat()
_PAST_ISO = (datetime.now(UTC) - timedelta(days=1)).isoformat()
# Fixed summer instant: New York is EDT (UTC-4) — a deterministic %Z assertion.
_FIXED_UTC = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    """datetime subclass whose now() is pinned — for the parsed == now boundary."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 15, 12, 0, 0, tzinfo=tz)


class _RecordingDatetime:
    """datetime stand-in that records the exact string handed to
    fromisoformat — pins the 'Z' → '+00:00' normalization that precedes
    parsing (Python ≥3.11 parses 'Z' natively, so only the recorded input
    distinguishes a dropped normalization)."""

    last_input: str | None = None

    @classmethod
    def fromisoformat(cls, iso_str: str) -> datetime:
        cls.last_input = iso_str
        return datetime.fromisoformat(iso_str)

    @classmethod
    def now(cls, tz=None) -> datetime:
        return datetime.now(tz)


def _config(user_id: str | None = "user-1") -> dict:
    return {"metadata": {"user_id": user_id}} if user_id else {"metadata": {}}


# ---------------------------------------------------------------------------
# _patch_canvas_section — the leading-section duplication bug
# ---------------------------------------------------------------------------


class TestPatchCanvasSection:
    def test_replaces_a_section_that_is_the_first_line_of_the_canvas(self):
        """Regression test for the bug: a freshly-created canvas's first
        section (no leading blank line before its heading) must be replaced
        in place, not duplicated at the end."""
        canvas = "## Current State\nOld info.\n\n## Learnings\nA learning."
        result = _patch_canvas_section(canvas, "Current State", "New info.")

        assert result.count("## Current State") == 1
        assert "Old info." not in result
        assert "New info." in result
        assert "## Learnings\nA learning." in result

    def test_replaces_a_middle_section(self):
        canvas = "## First\nA\n\n## Middle\nOld middle\n\n## Last\nC"
        result = _patch_canvas_section(canvas, "Middle", "New middle")

        assert result.count("## Middle") == 1
        assert "Old middle" not in result
        assert "New middle" in result
        assert "## First\nA" in result
        assert "## Last\nC" in result

    def test_replaces_the_last_section(self):
        canvas = "## First\nA\n\n## Last\nOld last"
        result = _patch_canvas_section(canvas, "Last", "New last")

        assert result.count("## Last") == 1
        assert "Old last" not in result
        assert "New last" in result

    def test_appends_a_section_that_does_not_exist(self):
        canvas = "## First\nA"
        result = _patch_canvas_section(canvas, "New Section", "Body")

        assert "## First\nA" in result
        assert "## New Section\nBody" in result

    def test_does_not_match_a_section_whose_name_is_a_prefix_of_another(self):
        """'## Current' must not accidentally match inside '## Current State'."""
        canvas = "## Current State\nDetail here."
        result = _patch_canvas_section(canvas, "Current", "New content")

        # A false-prefix-match would have folded this into "Current State"
        # instead of appending a genuinely new "## Current" section.
        assert "## Current State\nDetail here." in result
        assert "## Current\nNew content" in result

    def test_append_shape_is_exact(self):
        assert _patch_canvas_section("## First\nA", "New Section", "Body") == (
            "## First\nA\n\n## New Section\nBody"
        )

    def test_leading_whitespace_is_preserved_when_appending(self):
        """rstrip (not lstrip) on the append path — leading whitespace survives."""
        assert _patch_canvas_section("  ## First\nA", "New", "Body") == (
            "  ## First\nA\n\n## New\nBody"
        )

    def test_first_line_replace_shape_is_exact(self):
        canvas = "## Current State\nOld info.\n\n## Learnings\nA learning."
        assert _patch_canvas_section(canvas, "Current State", "New info.") == (
            "## Current State\nNew info.\n\n## Learnings\nA learning."
        )

    def test_middle_replace_shape_is_exact(self):
        canvas = "## First\nA\n\n## Middle\nOld middle\n\n## Last\nC"
        assert _patch_canvas_section(canvas, "Middle", "New middle") == (
            "## First\nA\n\n## Middle\nNew middle\n\n## Last\nC"
        )

    def test_last_replace_shape_is_exact(self):
        assert _patch_canvas_section("## First\nA\n\n## Last\nOld last", "Last", "New last") == (
            "## First\nA\n\n## Last\nNew last"
        )

    def test_content_trailing_whitespace_is_stripped_in_middle_replace(self):
        canvas = "## First\nA\n\n## Middle\nOld middle\n\n## Last\nC"
        assert _patch_canvas_section(canvas, "Middle", "new  ") == (
            "## First\nA\n\n## Middle\nnew\n\n## Last\nC"
        )

    def test_replaces_first_occurrence_when_section_repeats(self):
        """A repeated heading must patch the FIRST block, not the last (rfind
        would silently replace the wrong copy)."""
        canvas = "## Notes\nold\n## Notes\ndup"
        assert _patch_canvas_section(canvas, "Notes", "new") == (
            "## Notes\nnew\n\n## Notes\ndup"
        )

    def test_prefix_miss_then_exact_match_still_replaces(self):
        """The loop must keep scanning past a non-exact prefix occurrence and
        land on the real heading — a one-char off search_start would either
        append a duplicate or never terminate."""
        canvas = "## Current State\nold\n## Current\nA"
        assert _patch_canvas_section(canvas, "Current", "new") == (
            "## Current State\nold\n## Current\nnew"
        )

    def test_heading_after_leading_newline_is_replaced(self):
        assert _patch_canvas_section("\n## Current\nold", "Current", "new") == (
            "\n## Current\nnew"
        )

    def test_adjacent_sections_keep_the_following_section(self):
        """No blank line between sections: the next-section scan must still
        find the sibling heading that starts exactly one line below."""
        assert _patch_canvas_section("## X\n\n## Y\nz", "X", "new") == "## X\nnew\n\n## Y\nz"

    def test_next_section_search_uses_first_sibling_not_last(self):
        canvas = "## X\nold\n## A\nx\n## B\ny"
        assert _patch_canvas_section(canvas, "X", "new") == (
            "## X\nnew\n\n## A\nx\n## B\ny"
        )

    def test_next_section_scan_end_offset_does_not_skip_immediate_sibling(self):
        assert _patch_canvas_section("a\n## Sec\nbody", "Sec", "new") == "a\n## Sec\nnew"

    def test_heading_preceded_by_other_line_content_is_not_matched(self):
        assert _patch_canvas_section("x\n## Notes\nold", "Notes", "new") == "x\n## Notes\nnew"


# ---------------------------------------------------------------------------
# _parse_iso_future_datetime / _build_scheduled_at_update — tz-naive crash bug
# ---------------------------------------------------------------------------


class TestParseIsoFutureDatetime:
    def test_valid_future_datetime_with_offset(self):
        parsed, error = _parse_iso_future_datetime(_FUTURE_ISO, "scheduled_at")
        assert error is None
        assert parsed == _FUTURE

    def test_past_datetime_rejected(self):
        parsed, error = _parse_iso_future_datetime(_PAST_ISO, "scheduled_at")
        assert parsed is None
        assert error == "Error: scheduled_at must be in the future."

    def test_invalid_format_rejected(self):
        parsed, error = _parse_iso_future_datetime("not-a-date", "scheduled_at")
        assert parsed is None
        assert error == "Error: invalid scheduled_at format 'not-a-date'."

    def test_naive_datetime_without_timezone_offset_is_rejected_cleanly(self):
        """Regression test: a naive datetime used to raise an unhandled
        TypeError ('can't compare offset-naive and offset-aware datetimes')
        instead of a clean validation error."""
        parsed, error = _parse_iso_future_datetime("2027-03-20T09:00:00", "scheduled_at")
        assert parsed is None
        assert "timezone offset" in error

    def test_z_suffix_is_treated_as_utc(self):
        future_z = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        parsed, error = _parse_iso_future_datetime(future_z, "scheduled_at")
        assert error is None
        assert parsed.tzinfo is not None

    def test_z_suffix_is_normalized_to_offset_before_parsing(self):
        """The 'Z' suffix must be rewritten to '+00:00' before fromisoformat —
        the parser only ever sees an explicit offset."""
        with patch("app.agents.tools.tracked_todo_tools.datetime", _RecordingDatetime):
            parsed, error = _parse_iso_future_datetime("2027-07-15T12:00:00Z", "scheduled_at")
        assert error is None
        assert parsed == datetime(2027, 7, 15, 12, 0, 0, tzinfo=UTC)
        assert _RecordingDatetime.last_input == "2027-07-15T12:00:00+00:00"

    def test_datetime_exactly_now_is_rejected(self):
        """Boundary: ``parsed <= now`` — an instant equal to now is NOT future."""
        with patch("app.agents.tools.tracked_todo_tools.datetime", _FrozenDatetime):
            parsed, error = _parse_iso_future_datetime("2026-07-15T12:00:00+00:00", "scheduled_at")
        assert parsed is None
        assert error == "Error: scheduled_at must be in the future."


class TestBuildScheduledAtUpdate:
    def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        assert _build_scheduled_at_update(None, fields) is None
        assert fields == {}

    def test_empty_string_clears_the_field(self):
        fields: dict[str, object] = {}
        assert _build_scheduled_at_update("", fields) is None
        assert fields == {"scheduled_at": None}

    def test_naive_datetime_is_rejected_cleanly_not_a_crash(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update("2027-03-20T09:00:00", fields)
        assert error is not None
        assert "timezone offset" in error
        assert fields == {}

    def test_past_datetime_rejected(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update(_PAST_ISO, fields)
        assert error == "Error: scheduled_at must be in the future."
        assert fields == {}

    def test_valid_future_datetime_sets_the_field(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update(_FUTURE_ISO, fields)
        assert error is None
        assert fields["scheduled_at"] == _FUTURE

    def test_invalid_format_rejected(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update("garbage", fields)
        assert error is not None
        assert "invalid scheduled_at format" in error
        assert fields == {}

    def test_datetime_exactly_now_is_rejected(self):
        """Boundary: ``parsed_at <= now`` — an instant equal to now is NOT future."""
        fields: dict[str, object] = {}
        with patch("app.agents.tools.tracked_todo_tools.datetime", _FrozenDatetime):
            error = _build_scheduled_at_update("2026-07-15T12:00:00+00:00", fields)
        assert error == "Error: scheduled_at must be in the future."
        assert fields == {}

    def test_z_suffix_is_normalized_to_offset_before_parsing(self):
        fields: dict[str, object] = {}
        with patch("app.agents.tools.tracked_todo_tools.datetime", _RecordingDatetime):
            error = _build_scheduled_at_update("2027-07-15T12:00:00Z", fields)
        assert error is None
        assert fields["scheduled_at"] == datetime(2027, 7, 15, 12, 0, 0, tzinfo=UTC)
        assert _RecordingDatetime.last_input == "2027-07-15T12:00:00+00:00"


# ---------------------------------------------------------------------------
# _build_clearable_datetime_update / _build_priority_update / _build_labels_update
# ---------------------------------------------------------------------------


class TestBuildClearableDatetimeUpdate:
    def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        assert _build_clearable_datetime_update(None, "due_date", fields) is None
        assert fields == {}

    def test_empty_string_clears(self):
        fields: dict[str, object] = {}
        assert _build_clearable_datetime_update("", "due_date", fields) is None
        assert fields == {"due_date": None}

    def test_invalid_format_returns_error_and_does_not_touch_fields(self):
        fields: dict[str, object] = {}
        error = _build_clearable_datetime_update("garbage", "due_date", fields)
        assert "invalid due_date format" in error
        assert fields == {}

    def test_valid_datetime_sets_field_no_future_requirement(self):
        """Unlike scheduled_at, due_date/expires_at may legitimately be in the
        past (an overdue due_date is still meaningful)."""
        fields: dict[str, object] = {}
        error = _build_clearable_datetime_update(_PAST_ISO, "due_date", fields)
        assert error is None
        assert fields["due_date"] is not None

    def test_z_suffix_is_normalized_to_offset_before_parsing(self):
        fields: dict[str, object] = {}
        with patch("app.agents.tools.tracked_todo_tools.datetime", _RecordingDatetime):
            error = _build_clearable_datetime_update("2026-07-15T12:00:00Z", "due_date", fields)
        assert error is None
        assert fields["due_date"] == datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)
        assert _RecordingDatetime.last_input == "2026-07-15T12:00:00+00:00"


class TestBuildPriorityUpdate:
    def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        assert _build_priority_update(None, fields) is None
        assert fields == {}

    @pytest.mark.parametrize("value", ["high", "medium", "low", "none"])
    def test_valid_priority_values(self, value):
        fields: dict[str, object] = {}
        assert _build_priority_update(value, fields) is None
        assert fields["priority"] == value

    def test_invalid_priority_rejected(self):
        fields: dict[str, object] = {}
        error = _build_priority_update("urgent", fields)
        assert "invalid priority" in error
        assert fields == {}


class TestBuildLabelsUpdate:
    def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        assert _build_labels_update(None, fields) is None
        assert fields == {}

    def test_gaia_tracked_label_is_added_if_missing(self):
        fields: dict[str, object] = {}
        _build_labels_update(["work"], fields)
        assert GAIA_TRACKED_LABEL in fields["labels"]
        assert "work" in fields["labels"]

    def test_gaia_tracked_label_is_not_duplicated_if_already_present(self):
        fields: dict[str, object] = {}
        _build_labels_update(["work", GAIA_TRACKED_LABEL], fields)
        assert fields["labels"].count(GAIA_TRACKED_LABEL) == 1

    def test_empty_list_still_gets_the_tracked_label(self):
        fields: dict[str, object] = {}
        _build_labels_update([], fields)
        assert fields["labels"] == [GAIA_TRACKED_LABEL]


# ---------------------------------------------------------------------------
# Recurrence: _is_cron_expression / _validate_recurrence_format / _resolve_first_fire
# ---------------------------------------------------------------------------


class TestRecurrenceValidation:
    @pytest.mark.parametrize("shortcut", ["daily", "weekly", "every_4h", "every_1h"])
    def test_shortcuts_are_not_cron_expressions(self, shortcut):
        assert _is_cron_expression(shortcut) is False

    def test_cron_string_is_a_cron_expression(self):
        assert _is_cron_expression("0 9 * * *") is True

    def test_valid_cron_passes_format_validation(self):
        assert _validate_recurrence_format("0 9,20 * * *") is None

    def test_invalid_cron_is_rejected(self):
        error = _validate_recurrence_format("not a cron")
        assert error is not None
        assert "invalid recurrence" in error

    def test_valid_shortcut_passes_format_validation(self):
        assert _validate_recurrence_format("daily") is None

    def test_unknown_shortcut_word_is_rejected_with_shortcut_guidance(self):
        """A typo'd shortcut ('monthly', 'dailyy', ...) is not a known shortcut
        and not a valid cron either — the error must still point the caller at
        the valid shortcut options, not just say "invalid" with no guidance."""
        assert _validate_recurrence_format("monthly") == (
            "Error: invalid recurrence 'monthly'. "
            "Use one of: daily, every_1h, every_4h, weekly, "
            "or a valid 5-field cron expression."
        )


class TestResolveCronFirstFire:
    def test_compute_failure_returns_clean_error_not_a_crash(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
            side_effect=RuntimeError("bad timezone data"),
        ):
            parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", None, "UTC")
        assert parsed is None
        assert "could not compute first fire" in error

    def test_scheduled_at_ignored_note_added_when_provided_alongside_cron(self):
        parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", _FUTURE_ISO, "UTC")
        assert error is None
        assert any("ignored" in n for n in notes)

    def test_no_note_when_scheduled_at_not_provided(self):
        parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", None, "UTC")
        assert error is None
        assert notes == []

    def test_invalid_cron_error_is_exact(self):
        _, notes, error = _resolve_cron_first_fire("not a cron", None, "UTC")
        assert error == (
            "Error: invalid recurrence 'not a cron'. "
            "Use one of: daily, every_1h, every_4h, weekly, "
            "or a valid 5-field cron expression."
        )

    def test_scheduled_at_ignored_note_is_exact(self):
        _, notes, error = _resolve_cron_first_fire("0 9 * * *", _FUTURE_ISO, "UTC")
        assert error is None
        assert notes == [
            "scheduled_at was ignored — for a cron recurrence the first fire "
            "is computed from the cron in the user's timezone."
        ]

    def test_first_fire_is_computed_in_the_given_user_timezone(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
            return_value=_FUTURE,
        ) as mock_compute:
            parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", None, "America/New_York")
        assert parsed == _FUTURE
        assert error is None
        mock_compute.assert_called_once_with("0 9 * * *", "America/New_York")

    def test_missing_user_timezone_falls_back_to_utc_for_computation(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
            return_value=_FUTURE,
        ) as mock_compute:
            parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", None, None)
        assert parsed == _FUTURE
        assert error is None
        mock_compute.assert_called_once_with("0 9 * * *", "UTC")


class TestResolveFirstFire:
    def test_no_recurrence_no_scheduled_at_returns_nothing(self):
        parsed, notes, error = _resolve_first_fire(None, None, "UTC")
        assert parsed is None
        assert error is None

    def test_plain_scheduled_at_without_recurrence(self):
        parsed, notes, error = _resolve_first_fire(None, _FUTURE_ISO, "UTC")
        assert error is None
        assert parsed == _FUTURE

    def test_shortcut_recurrence_without_scheduled_at_is_an_error(self):
        parsed, notes, error = _resolve_first_fire("daily", None, "UTC")
        assert parsed is None
        assert error == (
            "Error: recurrence 'daily' is a shortcut and requires "
            "scheduled_at as the first-fire anchor. Either provide scheduled_at "
            "or use a cron expression that fully specifies when to fire."
        )

    def test_shortcut_recurrence_with_scheduled_at_anchors_on_it(self):
        parsed, notes, error = _resolve_first_fire("daily", _FUTURE_ISO, "UTC")
        assert error is None
        assert parsed == _FUTURE

    def test_cron_recurrence_ignores_scheduled_at_and_notes_it(self):
        parsed, notes, error = _resolve_first_fire("0 9 * * *", _FUTURE_ISO, "UTC")
        assert error is None
        assert parsed is not None
        assert any("ignored" in n for n in notes)

    def test_invalid_cron_recurrence_is_rejected(self):
        parsed, notes, error = _resolve_first_fire("not a cron", None, "UTC")
        assert parsed is None
        assert error is not None

    def test_cron_delegation_passes_the_user_timezone_through(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._resolve_cron_first_fire",
            return_value=(_FUTURE, [], None),
        ) as mock_resolve:
            parsed, notes, error = _resolve_first_fire("0 9 * * *", None, "America/New_York")
        assert (parsed, notes, error) == (_FUTURE, [], None)
        mock_resolve.assert_called_once_with("0 9 * * *", None, "America/New_York")

    def test_shortcut_branch_parses_with_field_name_scheduled_at(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._parse_iso_future_datetime",
            return_value=(_FUTURE, None),
        ) as mock_parse:
            parsed, notes, error = _resolve_first_fire("daily", _FUTURE_ISO, "UTC")
        assert (parsed, error) == (_FUTURE, None)
        mock_parse.assert_called_once_with(_FUTURE_ISO, "scheduled_at")

    def test_no_recurrence_branch_parses_with_field_name_scheduled_at(self):
        with patch(
            "app.agents.tools.tracked_todo_tools._parse_iso_future_datetime",
            return_value=(_FUTURE, None),
        ) as mock_parse:
            parsed, notes, error = _resolve_first_fire(None, _FUTURE_ISO, "UTC")
        assert (parsed, error) == (_FUTURE, None)
        mock_parse.assert_called_once_with(_FUTURE_ISO, "scheduled_at")


class TestBuildRecurrenceUpdate:
    """The update-path equivalent of _resolve_first_fire — recomputes the
    cron first-fire against the user's stored timezone (a real Mongo lookup
    via _get_user_tz, mocked here at that boundary)."""

    async def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        error = await _build_recurrence_update(None, None, "u1", fields, [])
        assert error is None
        assert fields == {}

    async def test_empty_string_clears_recurrence(self):
        fields: dict[str, object] = {}
        error = await _build_recurrence_update("", None, "u1", fields, [])
        assert error is None
        assert fields == {"recurrence": None}

    async def test_invalid_format_returns_error(self):
        fields: dict[str, object] = {}
        error = await _build_recurrence_update("not a cron", None, "u1", fields, [])
        assert error is not None
        assert "recurrence" not in fields

    async def test_cron_recurrence_recomputes_scheduled_at_from_user_timezone(self):
        fields: dict[str, object] = {}
        notes: list[str] = []
        with patch(
            "app.agents.tools.tracked_todo_tools._get_user_tz",
            new_callable=AsyncMock,
            return_value="America/New_York",
        ) as mock_get_tz:
            error = await _build_recurrence_update("0 9 * * *", None, "u1", fields, notes)

        assert error is None
        assert fields["recurrence"] == "0 9 * * *"
        assert isinstance(fields["scheduled_at"], datetime)
        mock_get_tz.assert_awaited_once_with("u1")

    async def test_shortcut_recurrence_does_not_touch_scheduled_at(self):
        """A shortcut ('daily') has no cron to recompute a first-fire from —
        scheduled_at update_tracked_todo's own guard requires it separately."""
        fields: dict[str, object] = {}
        error = await _build_recurrence_update("daily", None, "u1", fields, [])
        assert error is None
        assert fields == {"recurrence": "daily"}


# ---------------------------------------------------------------------------
# _build_list_detail_parts — overdue/expired day-math
# ---------------------------------------------------------------------------


class TestBuildListDetailParts:
    def _doc(self, **overrides) -> TodoDocument:
        base = {"user_id": "u1", "title": "t"}
        base.update(overrides)
        return TodoDocument(**base)

    def test_overdue_due_date_is_flagged(self):
        now = datetime.now(UTC)
        doc = self._doc(due_date=now - timedelta(days=3))
        parts = _build_list_detail_parts(doc, now)
        assert "Due: OVERDUE 3d" in parts

    def test_future_due_date_is_not_flagged_overdue(self):
        now = datetime.now(UTC)
        doc = self._doc(due_date=now + timedelta(days=3))
        parts = _build_list_detail_parts(doc, now)
        assert "Due: 3d" in parts

    def test_due_date_today_is_not_overdue(self):
        """Boundary: ``days_until < 0`` — exactly today must not read OVERDUE."""
        now = datetime.now(UTC)
        doc = self._doc(due_date=now)
        parts = _build_list_detail_parts(doc, now)
        assert "Due: 0d" in parts

    def test_expired_is_flagged(self):
        now = datetime.now(UTC)
        doc = self._doc(expires_at=now - timedelta(days=2))
        parts = _build_list_detail_parts(doc, now)
        assert "Expires: EXPIRED 2d ago" in parts

    def test_expiry_today_is_not_flagged_expired(self):
        """Boundary: ``expires_days < 0`` — exactly today must not read EXPIRED."""
        now = datetime.now(UTC)
        doc = self._doc(expires_at=now)
        parts = _build_list_detail_parts(doc, now)
        assert "Expires: in 0d" in parts

    def test_retry_count_shown_only_when_positive(self):
        now = datetime.now(UTC)
        doc = self._doc(gaia_retry_count=0)
        assert not any("Retries" in p for p in _build_list_detail_parts(doc, now))
        doc2 = self._doc(gaia_retry_count=2)
        assert any("Retries: 2" in p for p in _build_list_detail_parts(doc2, now))

    def test_single_retry_is_shown(self):
        """Boundary: ``gaia_retry_count > 0`` — one retry must still be visible."""
        now = datetime.now(UTC)
        doc = self._doc(gaia_retry_count=1)
        assert "Retries: 1" in _build_list_detail_parts(doc, now)


# ---------------------------------------------------------------------------
# Tool-level: update_tracked_todo_canvas mode validation
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoCanvasValidation:
    async def test_missing_user_id_returns_error(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(None), todo_id="t1", content="x"
        )
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await update_tracked_todo_canvas.coroutine(config={}, todo_id="t1", content="x")
        assert result == "Error: user_id not found in config"

    async def test_invalid_mode_rejected(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(), todo_id="t1", content="x", mode="overwrite"
        )
        assert "invalid mode" in result

    async def test_section_mode_without_section_name_rejected(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(), todo_id="t1", content="x", mode="section", section=None
        )
        assert result == "Error: 'section' mode requires a section name."

    async def test_todo_not_found_returns_error(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="missing", content="x", mode="append"
            )
        assert "not found" in result


# ---------------------------------------------------------------------------
# Tool-level: update_tracked_todo — recurrence-without-scheduled_at guard
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoValidation:
    async def test_missing_user_id_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(None), todo_id="t1")
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await update_tracked_todo.coroutine(config={}, todo_id="t1")
        assert result == "Error: user_id not found in config"

    async def test_no_fields_provided_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(), todo_id="t1")
        assert result == "No fields to update. Provide at least one field to change."

    async def test_clearing_scheduled_at_while_recurrence_remains_set_is_rejected(self):
        """The in-call guards alone can't see this: clearing scheduled_at while
        an existing recurrence stays set would leave a broken recurring todo
        with nothing to anchor it."""
        existing = TodoDocument(
            id="t1", user_id="u1", title="t", recurrence="daily", scheduled_at=_FUTURE
        )
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.get",
            new_callable=AsyncMock,
            return_value=existing,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", scheduled_at=""
            )
        assert result == (
            "Error: cannot have recurrence without scheduled_at. "
            "Either clear recurrence or provide a scheduled_at value."
        )

    async def test_todo_not_found_returns_error(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="missing", priority="high"
            )
        assert "not found" in result

    async def test_invalid_due_date_error_short_circuits_before_any_db_read(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.get",
            new_callable=AsyncMock,
        ) as mock_get:
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", due_date="garbage"
            )
        assert "invalid due_date format" in result
        mock_get.assert_not_awaited()

    async def test_invalid_priority_error_propagates_through_the_tool(self):
        result = await update_tracked_todo.coroutine(
            config=_config(), todo_id="t1", priority="urgent"
        )
        assert "invalid priority" in result

    async def test_invalid_scheduled_at_error_propagates_through_the_tool(self):
        result = await update_tracked_todo.coroutine(
            config=_config(), todo_id="t1", scheduled_at="garbage"
        )
        assert "invalid scheduled_at format" in result

    async def test_invalid_recurrence_error_propagates_through_the_tool(self):
        result = await update_tracked_todo.coroutine(
            config=_config(), todo_id="t1", recurrence="not a cron"
        )
        assert "invalid recurrence" in result

    async def test_invalid_expires_at_error_propagates_through_the_tool(self):
        result = await update_tracked_todo.coroutine(
            config=_config(), todo_id="t1", expires_at="garbage"
        )
        assert "invalid expires_at format" in result


# ---------------------------------------------------------------------------
# Tool-level: create_tracked_todo — validation short-circuits
# ---------------------------------------------------------------------------


class TestCreateTrackedTodoValidation:
    async def test_missing_user_id_returns_error(self):
        result = await create_tracked_todo.coroutine(config=_config(None), title="t")
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await create_tracked_todo.coroutine(config={}, title="t")
        assert result == "Error: user_id not found in config"

    async def test_invalid_priority_returns_error(self):
        result = await create_tracked_todo.coroutine(config=_config(), title="t", priority="urgent")
        assert "invalid priority" in result

    async def test_shortcut_recurrence_without_scheduled_at_returns_error(self):
        result = await create_tracked_todo.coroutine(
            config=_config(), title="t", recurrence="daily"
        )
        assert "requires scheduled_at" in result


class TestCompleteTrackedTodo:
    async def test_missing_user_id_returns_error(self):
        result = await complete_tracked_todo.coroutine(
            config=_config(None), todo_id="t1", summary="done"
        )
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await complete_tracked_todo.coroutine(config={}, todo_id="t1", summary="done")
        assert result == "Error: user_id not found in config"

    async def test_service_failure_returns_error(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.complete_tracked_todo",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await complete_tracked_todo.coroutine(
                config=_config(), todo_id="t1", summary="done"
            )
        assert "could not complete" in result

    async def test_success_returns_confirmation(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.complete_tracked_todo",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_complete:
            result = await complete_tracked_todo.coroutine(
                config=_config(), todo_id="t1", summary="done"
            )
        assert result == "Tracked todo t1 completed and archived."
        mock_complete.assert_awaited_once_with(todo_id="t1", user_id="user-1", summary="done")


# ---------------------------------------------------------------------------
# _get_user_tz
# ---------------------------------------------------------------------------


class TestGetUserTz:
    async def test_valid_timezone_is_returned(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value={"timezone": "America/New_York"},
        ) as mock_get:
            tz = await _get_user_tz("u1")
        assert tz == "America/New_York"
        mock_get.assert_awaited_once_with("u1")

    async def test_invalid_timezone_name_falls_back_to_utc(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value={"timezone": "Not/A_Real_Zone"},
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"

    async def test_invalid_timezone_logs_debug_with_exact_fields(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"timezone": "Not/A_Real_Zone"},
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"
        mock_log.debug.assert_called_once_with(
            "tracked_todo.invalid_user_tz", user_id="u1", tz_name="Not/A_Real_Zone"
        )
        mock_log.warning.assert_called_once_with(
            "tracked_todo.user_tz_fallback_utc", user_id="u1"
        )

    async def test_empty_timezone_skips_validation_entirely(self):
        """A falsy timezone value must take the no-timezone path — no
        validation, no invalid-tz debug log."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.get_user_by_id",
                new_callable=AsyncMock,
                return_value={"timezone": ""},
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"
        mock_log.debug.assert_not_called()

    async def test_no_user_found_falls_back_to_utc(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.get_user_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"
        mock_log.warning.assert_called_once_with(
            "tracked_todo.user_tz_fallback_utc", user_id="u1"
        )

    async def test_lookup_failure_logs_warning_with_exact_fields(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.get_user_by_id",
                new_callable=AsyncMock,
                side_effect=RuntimeError("mongo down"),
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"
        mock_log.warning.assert_any_call(
            "tracked_todo.user_tz_lookup_failed", user_id="u1", error="mongo down"
        )
        mock_log.warning.assert_any_call("tracked_todo.user_tz_fallback_utc", user_id="u1")


# ---------------------------------------------------------------------------
# spawn_logged_task (wide-event-aware fire-and-forget)
# ---------------------------------------------------------------------------


class TestSpawnBackgroundTask:
    async def test_schedules_the_coroutine_as_a_background_task(self):
        ran = {"done": False}

        async def _mark_done():
            ran["done"] = True

        spawn_logged_task("mark_done_test", _mark_done())
        # The task is scheduled, not awaited inline — give the loop one tick.
        import asyncio

        await asyncio.sleep(0)
        assert ran["done"] is True


# ---------------------------------------------------------------------------
# _persist_scheduling_fields
# ---------------------------------------------------------------------------


class TestPersistSchedulingFields:
    async def test_nothing_to_persist_is_a_no_op(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, None)
        assert error is None
        mock_update.assert_not_awaited()

    async def test_persists_scheduled_at_and_recurrence(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", _FUTURE, "daily", None)
        assert error is None
        mock_update.assert_awaited_once_with("t1", user_id="u1", update=ANY)
        update_arg = mock_update.await_args.kwargs["update"]
        assert isinstance(update_arg, TodoUpdate)
        assert update_arg.scheduled_at == _FUTURE
        assert update_arg.recurrence == "daily"

    async def test_scheduled_at_alone_still_persists(self):
        """A lone scheduled_at (no recurrence, no expires_at) must not be
        dropped by the truthiness gate."""
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", _FUTURE, None, None)
        assert error is None
        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["update"].scheduled_at == _FUTURE

    async def test_expires_at_is_persisted(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, "2026-07-15T12:00:00Z")
        assert error is None
        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["update"].expires_at == datetime(
            2026, 7, 15, 12, 0, 0, tzinfo=UTC
        )

    async def test_expires_at_z_suffix_is_normalized_before_parsing(self):
        with (
            patch("app.agents.tools.tracked_todo_tools.datetime", _RecordingDatetime),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ) as mock_update,
        ):
            error = await _persist_scheduling_fields("t1", "u1", None, None, "2026-07-15T12:00:00Z")
        assert error is None
        mock_update.assert_awaited_once()
        assert mock_update.await_args.kwargs["update"].expires_at == datetime(
            2026, 7, 15, 12, 0, 0, tzinfo=UTC
        )
        assert _RecordingDatetime.last_input == "2026-07-15T12:00:00+00:00"

    async def test_invalid_expires_at_format_returns_error_without_persisting(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, "garbage")
        assert error is not None
        assert "invalid expires_at format" in error
        mock_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# _schedule_execution_after_create
# ---------------------------------------------------------------------------


class TestScheduleExecutionAfterCreate:
    async def test_success_returns_none(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_schedule:
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert error is None
        mock_schedule.assert_awaited_once_with("t1", _FUTURE)

    async def test_scheduler_returns_false_yields_user_facing_warning(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
            new_callable=AsyncMock,
            return_value=False,
        ):
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert "scheduling failed" in error
        assert "will NOT execute automatically" in error

    async def test_scheduler_exception_yields_user_facing_warning_not_a_crash(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                side_effect=RuntimeError("arq connection lost"),
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert "scheduling failed" in error
        assert "arq connection lost" in error
        mock_log.warning.assert_called_once_with(
            "tracked_todo.schedule_after_create_failed", todo_id="t1", error="arq connection lost"
        )


# ---------------------------------------------------------------------------
# _format_first_fire_note
# ---------------------------------------------------------------------------


class TestFormatFirstFireNote:
    def test_with_valid_user_timezone(self):
        note = _format_first_fire_note(_FUTURE, "America/New_York")
        assert "your timezone (America/New_York)" in note
        assert "update_tracked_todo" in note

    def test_without_user_timezone_shows_utc(self):
        note = _format_first_fire_note(_FUTURE, None)
        assert "UTC" in note

    def test_invalid_timezone_falls_back_to_utc_note_not_a_crash(self):
        """Timezone.parse itself never raises (falls back to UTC with a
        warning log) — this exercises that graceful path, not the astimezone
        except-branch below, which needs Timezone.parse mocked to actually
        raise since nothing in real usage can trigger it otherwise."""
        note = _format_first_fire_note(_FUTURE, "Not/A_Real_Zone")
        assert "UTC" in note

    def test_astimezone_failure_falls_back_to_plain_utc_note(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.Timezone.parse",
            side_effect=RuntimeError("unexpected tz failure"),
        ):
            note = _format_first_fire_note(_FUTURE, "America/New_York")
        assert note == f"\nFirst fire (UTC): {_FUTURE.isoformat()}"

    def test_timezone_note_is_exact(self):
        """Pins the full note: the strftime format, the local conversion
        (EDT, not UTC — the tz lookup must actually be used), and the
        correction hint."""
        local_fire = _FIXED_UTC.astimezone(Timezone.parse("America/New_York").tzinfo)
        expected = (
            "\nNote: scheduled in your timezone (America/New_York). "
            f"First fire: {local_fire.strftime('%a %Y-%m-%d %H:%M %Z')}. "
            "If this isn't what you wanted, call update_tracked_todo with "
            "the corrected recurrence (or scheduled_at for one-shots)."
        )
        assert _format_first_fire_note(_FIXED_UTC, "America/New_York") == expected
        assert "08:00 EDT" in expected

    def test_utc_note_is_exact(self):
        assert _format_first_fire_note(_FIXED_UTC, None) == (
            f"\nNote: first fire (UTC): {_FIXED_UTC.isoformat()}. "
            "If this isn't what you wanted, call update_tracked_todo to correct it."
        )


# ---------------------------------------------------------------------------
# _apply_cron_first_fire — exception path
# ---------------------------------------------------------------------------


class TestApplyCronFirstFire:
    async def test_compute_failure_returns_clean_error(self):
        fields: dict[str, object] = {}
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="UTC",
            ),
            patch(
                "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
                side_effect=RuntimeError("bad cron math"),
            ),
        ):
            error = await _apply_cron_first_fire("0 9 * * *", None, "u1", fields, [])
        assert error is not None
        assert "could not compute first fire" in error
        assert "scheduled_at" not in fields

    async def test_scheduled_at_alongside_cron_is_noted_as_ignored(self):
        fields: dict[str, object] = {}
        notes: list[str] = []
        with patch(
            "app.agents.tools.tracked_todo_tools._get_user_tz",
            new_callable=AsyncMock,
            return_value="UTC",
        ):
            error = await _apply_cron_first_fire("0 9 * * *", _FUTURE_ISO, "u1", fields, notes)
        assert error is None
        assert any("ignored" in n for n in notes)
        assert isinstance(fields["scheduled_at"], datetime)

    async def test_ignored_note_is_exact_and_tz_lookup_and_cron_use_the_user(self):
        fields: dict[str, object] = {}
        notes: list[str] = []
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ) as mock_get_tz,
            patch(
                "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
                return_value=_FUTURE,
            ) as mock_compute,
        ):
            error = await _apply_cron_first_fire("0 9 * * *", _FUTURE_ISO, "u1", fields, notes)
        assert error is None
        assert notes == [
            "scheduled_at was ignored — for a cron recurrence the first fire "
            "is computed from the cron in your timezone."
        ]
        assert fields["scheduled_at"] == _FUTURE
        mock_get_tz.assert_awaited_once_with("u1")
        mock_compute.assert_called_once_with("0 9 * * *", "America/New_York")

    async def test_cron_uses_looked_up_user_timezone(self):
        fields: dict[str, object] = {}
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ) as mock_get_tz,
            patch(
                "app.agents.tools.tracked_todo_tools._compute_first_fire_from_cron",
                return_value=_FUTURE,
            ) as mock_compute,
        ):
            error = await _apply_cron_first_fire("0 9 * * *", None, "u1", fields, [])
        assert error is None
        assert fields["scheduled_at"] == _FUTURE
        mock_get_tz.assert_awaited_once_with("u1")
        mock_compute.assert_called_once_with("0 9 * * *", "America/New_York")


# ---------------------------------------------------------------------------
# _build_list_detail_parts — scheduled_at / recurrence display lines
# ---------------------------------------------------------------------------


class TestBuildListDetailPartsScheduling:
    def _doc(self, **overrides) -> TodoDocument:
        base = {"user_id": "u1", "title": "t"}
        base.update(overrides)
        return TodoDocument(**base)

    def test_scheduled_at_is_shown(self):
        now = datetime.now(UTC)
        doc = self._doc(scheduled_at=_FUTURE)
        parts = _build_list_detail_parts(doc, now)
        assert any("Scheduled:" in p for p in parts)

    def test_recurrence_is_shown(self):
        now = datetime.now(UTC)
        doc = self._doc(recurrence="daily")
        parts = _build_list_detail_parts(doc, now)
        assert any("Recurrence: daily" in p for p in parts)


# ---------------------------------------------------------------------------
# _format_tracked_todo_full
# ---------------------------------------------------------------------------


class TestFormatTrackedTodoFull:
    def test_formats_title_labels_and_priority(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="My todo",
            labels=["work", GAIA_TRACKED_LABEL],
            priority=Priority.HIGH,
            created_at=now,
            updated_at=now,
        )
        result = _format_tracked_todo_full(doc, now)
        assert '"My todo"' in result
        assert "[work]" in result
        # The internal tracking label must never leak into the display text.
        assert GAIA_TRACKED_LABEL not in result.split("\n")[0]
        assert "Priority: high" in result
        assert "(ID: t1)" in result

    def test_includes_detail_line_when_scheduling_fields_present(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="Scheduled todo",
            recurrence="daily",
            created_at=now,
            updated_at=now,
        )
        result = _format_tracked_todo_full(doc, now)
        assert "Recurrence: daily" in result

    def test_bare_doc_format_is_exact(self):
        """No labels, no timestamps, no scheduling: the (now or doc) fallbacks
        yield 0d ages and no bracket suffix must appear."""
        now = datetime.now(UTC)
        doc = TodoDocument(id="t1", user_id="u1", title="My todo", priority=Priority.HIGH)
        assert _format_tracked_todo_full(doc, now) == (
            '- "My todo" (ID: t1)\n'
            "  Priority: high | Age: 0d | Last updated: 0d ago"
        )

    def test_full_doc_format_is_exact(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="My todo",
            labels=["work", "misc"],
            priority=Priority.HIGH,
            created_at=now,
            updated_at=now,
            due_date=now + timedelta(days=1),
            gaia_retry_count=2,
        )
        assert _format_tracked_todo_full(doc, now) == (
            '- "My todo" [work, misc] (ID: t1)\n'
            "  Priority: high | Age: 0d | Last updated: 0d ago\n"
            "  Due: 1d | Retries: 2"
        )


# ---------------------------------------------------------------------------
# _format_create_output
# ---------------------------------------------------------------------------


class TestFormatCreateOutput:
    def _response(self) -> TodoResponse:
        now = datetime.now(UTC)
        return TodoResponse(
            id="t1", user_id="user-1", title="My todo", created_at=now, updated_at=now
        )

    def test_plain_output_is_exact(self):
        assert _format_create_output(self._response(), None, None, []) == (
            "Tracked todo created: t1\n"
            "Title: My todo\n"
            "Canvas + activity log are stored on this todo — edit them ONLY via "
            "update_tracked_todo_canvas(todo_id='t1', ...), never with filesystem tools."
        )

    def test_notes_are_joined_onto_the_prefix(self):
        assert _format_create_output(self._response(), None, None, ["n1", "n2"]) == (
            "Tracked todo created: t1\n"
            "Title: My todo\n"
            "Canvas + activity log are stored on this todo — edit them ONLY via "
            "update_tracked_todo_canvas(todo_id='t1', ...), never with filesystem tools."
            "\nDetails:\n  - n1\n  - n2"
        )

    def test_first_fire_note_is_appended_with_user_timezone(self):
        result = _format_create_output(self._response(), _FIXED_UTC, "America/New_York", [])
        assert result.startswith(
            "Tracked todo created: t1\n"
            "Title: My todo\n"
            "Canvas + activity log are stored on this todo — edit them ONLY via "
            "update_tracked_todo_canvas(todo_id='t1', ...), never with filesystem tools."
        )
        assert "scheduled in your timezone (America/New_York)" in result
        assert "08:00 EDT" in result


# ---------------------------------------------------------------------------
# search_todo_context
# ---------------------------------------------------------------------------


class TestSearchTodoContext:
    async def test_missing_user_id_returns_error(self):
        result = await search_todo_context.coroutine(config=_config(None), query="q")
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await search_todo_context.coroutine(config={}, query="q")
        assert result == "Error: user_id not found in config"

    async def test_no_matches_returns_friendly_message(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == "No matching tracked todo context found."
        mock_search.assert_awaited_once_with(
            query="q", user_id="user-1", top_k=5, include_completed=True
        )

    async def test_custom_top_k_and_completed_filter_are_forwarded(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_search:
            await search_todo_context.coroutine(
                config=_config(), query="q", top_k=3, include_completed=False
            )
        mock_search.assert_awaited_once_with(
            query="q", user_id="user-1", top_k=3, include_completed=False
        )

    async def test_match_line_is_formatted_exactly(self):
        matches = [
            {
                "title": "My todo",
                "todo_id": "t1",
                "score": 0.9,
                "snippet": "some context",
                "completed": False,
            }
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=matches,
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == "- [My todo] (todo_id: t1, score: 0.9)\n  some context"

    async def test_completed_match_line_is_formatted_exactly(self):
        matches = [
            {
                "title": "Old todo",
                "todo_id": "t2",
                "score": 0.5,
                "snippet": "done work",
                "completed": True,
            }
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=matches,
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == "- [Old todo] [completed] (todo_id: t2, score: 0.5)\n  done work"

    async def test_multiple_matches_are_newline_joined(self):
        matches = [
            {
                "title": "First",
                "todo_id": "t1",
                "score": 0.9,
                "snippet": "a",
                "completed": False,
            },
            {
                "title": "Second",
                "todo_id": "t2",
                "score": 0.5,
                "snippet": "b",
                "completed": False,
            },
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=matches,
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == (
            "- [First] (todo_id: t1, score: 0.9)\n  a\n- [Second] (todo_id: t2, score: 0.5)\n  b"
        )

    async def test_long_snippet_is_truncated_to_200_chars(self):
        matches = [
            {
                "title": "T",
                "todo_id": "t1",
                "score": 0.9,
                "snippet": "x" * 250,
                "completed": False,
            }
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=matches,
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == "- [T] (todo_id: t1, score: 0.9)\n  " + "x" * 200


# ---------------------------------------------------------------------------
# list_tracked_todos
# ---------------------------------------------------------------------------


class TestListTrackedTodos:
    async def test_missing_user_id_returns_error(self):
        result = await list_tracked_todos.coroutine(config=_config(None))
        assert "user_id not found" in result

    async def test_config_without_metadata_key_returns_error(self):
        result = await list_tracked_todos.coroutine(config={})
        assert result == "Error: user_id not found in config"

    async def test_no_active_todos_returns_friendly_message(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_tracked_todos.coroutine(config=_config())
        assert result == "No active tracked todos."

    async def test_active_todos_are_listed_with_count(self):
        now = datetime.now(UTC)
        docs = [
            TodoDocument(id="t1", user_id="user-1", title="First", created_at=now, updated_at=now),
            TodoDocument(id="t2", user_id="user-1", title="Second", created_at=now, updated_at=now),
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=docs,
        ) as mock_list:
            result = await list_tracked_todos.coroutine(config=_config())
        mock_list.assert_awaited_once_with("user-1", limit=50)
        assert result == (
            "Active tracked todos (2):\n\n"
            '- "First" (ID: t1)\n'
            "  Priority: none | Age: 0d | Last updated: 0d ago\n\n"
            '- "Second" (ID: t2)\n'
            "  Priority: none | Age: 0d | Last updated: 0d ago"
        )


# ---------------------------------------------------------------------------
# _compute_first_fire_from_cron
# ---------------------------------------------------------------------------


class TestComputeFirstFireFromCron:
    def test_forwards_cron_and_timezone_to_get_next_run_time(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_next_run_time",
            return_value=_FUTURE,
        ) as mock_next:
            result = _compute_first_fire_from_cron("0 9 * * *", "America/New_York")
        assert result == _FUTURE
        mock_next.assert_called_once_with(
            "0 9 * * *", tz=Timezone.parse("America/New_York")
        )


# ---------------------------------------------------------------------------
# update_tracked_todo_canvas — success paths
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoCanvasSuccess:
    def _existing_doc(self) -> TodoDocument:
        return TodoDocument(id="t1", user_id="user-1", title="t")

    async def test_default_mode_is_append(self):
        """Calling without a mode must behave exactly like mode='append'."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.append_canvas", new_callable=AsyncMock
            ) as mock_append,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ),
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="new note"
            )
        mock_append.assert_awaited_once_with("t1", "user-1", "new note")
        assert result == "Canvas updated (mode=append)."

    async def test_append_mode_calls_append_canvas(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ) as mock_get,
            patch(
                "app.agents.tools.tracked_todo_tools.append_canvas", new_callable=AsyncMock
            ) as mock_append,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ) as mock_reindex,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ) as mock_system_log,
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task") as mock_spawn,
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="new note", mode="append"
            )
        mock_get.assert_awaited_once_with("t1", user_id="user-1")
        mock_append.assert_awaited_once_with("t1", "user-1", "new note")
        assert result == "Canvas updated (mode=append)."
        mock_system_log.assert_awaited_once_with(
            todo_id="t1",
            user_id="user-1",
            event_type="CANVAS_UPDATED",
            details="Agent updated canvas (mode=append)",
        )
        mock_spawn.assert_called_once()
        spawn_call = mock_spawn.call_args
        assert spawn_call.args[0] == "canvas_reindex"
        assert asyncio.iscoroutine(spawn_call.args[1])
        assert spawn_call.kwargs == {"user": {"id": "user-1"}, "todo": {"id": "t1"}}
        mock_reindex.assert_called_once_with(todo_id="t1", user_id="user-1")

    async def test_replace_mode_calls_write_canvas(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ) as mock_get,
            patch(
                "app.agents.tools.tracked_todo_tools.write_canvas", new_callable=AsyncMock
            ) as mock_write,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ) as mock_system_log,
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="full rewrite", mode="replace"
            )
        mock_get.assert_awaited_once_with("t1", user_id="user-1")
        mock_write.assert_awaited_once_with("t1", "user-1", "full rewrite")
        assert result == "Canvas updated (mode=replace)."
        mock_system_log.assert_awaited_once_with(
            todo_id="t1",
            user_id="user-1",
            event_type="CANVAS_UPDATED",
            details="Agent updated canvas (mode=replace)",
        )

    async def test_section_mode_reads_current_canvas_and_patches_it(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ) as mock_get,
            patch(
                "app.agents.tools.tracked_todo_tools.read_canvas",
                new_callable=AsyncMock,
                return_value="## Notes\nold",
            ) as mock_read,
            patch(
                "app.agents.tools.tracked_todo_tools.write_canvas", new_callable=AsyncMock
            ) as mock_write,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ) as mock_system_log,
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="new",
                mode="section",
                section="Notes",
            )
        mock_get.assert_awaited_once_with("t1", user_id="user-1")
        mock_read.assert_awaited_once_with("t1", "user-1")
        mock_write.assert_awaited_once_with("t1", "user-1", "## Notes\nnew")
        assert result == "Canvas updated (mode=section, section=Notes)."
        mock_system_log.assert_awaited_once_with(
            todo_id="t1",
            user_id="user-1",
            event_type="CANVAS_UPDATED",
            details="Agent updated canvas (mode=section, section=Notes)",
        )

    async def test_section_mode_without_existing_canvas_appends_from_empty(self):
        """read_canvas returning None must fall back to an empty canvas, not
        a placeholder string that would leak into the written file."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.read_canvas",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.write_canvas", new_callable=AsyncMock
            ) as mock_write,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ),
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="new",
                mode="section",
                section="Notes",
            )
        mock_write.assert_awaited_once_with("t1", "user-1", "\n\n## Notes\nnew")
        assert "section=Notes" in result

    async def test_section_mode_preserves_sibling_sections(self):
        """The patch must keep sections that follow the one being replaced —
        dropping them would silently destroy canvas content."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.read_canvas",
                new_callable=AsyncMock,
                return_value="## Notes\nold\n\n## Other\nx",
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.write_canvas", new_callable=AsyncMock
            ) as mock_write,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ),
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="new",
                mode="section",
                section="Notes",
            )
        written_canvas = mock_write.await_args.args[2]
        assert written_canvas == "## Notes\nnew\n\n## Other\nx"
        assert "section=Notes" in result

    async def test_append_with_section_name_still_appends(self):
        """mode='append' with a section argument is not an error — the section
        is noted in the output/log but the content is still appended."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.append_canvas", new_callable=AsyncMock
            ) as mock_append,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reindex_canvas",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.system_log",
                new_callable=AsyncMock,
            ) as mock_system_log,
            patch("app.agents.tools.tracked_todo_tools.spawn_logged_task"),
        ):
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="x", mode="append", section="Notes"
            )
        mock_append.assert_awaited_once_with("t1", "user-1", "x")
        assert result == "Canvas updated (mode=append, section=Notes)."
        mock_system_log.assert_awaited_once_with(
            todo_id="t1",
            user_id="user-1",
            event_type="CANVAS_UPDATED",
            details="Agent updated canvas (mode=append, section=Notes)",
        )


# ---------------------------------------------------------------------------
# update_tracked_todo — success path
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoSuccess:
    def _existing_doc(self, **overrides) -> TodoDocument:
        base = {"id": "t1", "user_id": "user-1", "title": "t"}
        base.update(overrides)
        return TodoDocument(**base)

    async def test_priority_update_persists_and_reports_updated_keys(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ) as mock_get,
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(priority=Priority.HIGH),
            ) as mock_update,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority="high"
            )
        assert result == "Updated tracked todo t1: priority"
        mock_get.assert_awaited_once_with("t1", user_id="user-1")
        mock_update.assert_awaited_once_with("t1", user_id="user-1", update=ANY)
        update_arg = mock_update.await_args.kwargs["update"]
        assert isinstance(update_arg, TodoUpdate)
        assert update_arg.priority == Priority.HIGH

    async def test_scheduled_at_update_reschedules_execution(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(scheduled_at=_FUTURE),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ) as mock_reschedule,
        ):
            await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", scheduled_at=_FUTURE_ISO
            )
        mock_reschedule.assert_awaited_once_with("t1", _FUTURE)

    async def test_clearing_scheduled_at_does_not_reschedule(self):
        """A cleared scheduled_at lands in update_fields as None — not a
        datetime — so the ARQ job must NOT be rescheduled."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(scheduled_at=_FUTURE),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ) as mock_reschedule,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", scheduled_at=""
            )
        assert result == "Updated tracked todo t1: scheduled_at"
        mock_reschedule.assert_not_awaited()

    async def test_existing_schedule_survives_an_unrelated_update(self):
        """A doc that already has recurrence + scheduled_at must pass the
        state guard when only another field changes — the effective values
        come from the existing doc, not just from update_fields."""
        existing = self._existing_doc(recurrence="daily", scheduled_at=_FUTURE)
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(priority=Priority.HIGH),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority="high"
            )
        assert result == "Updated tracked todo t1: priority"

    async def test_clearing_recurrence_without_existing_scheduled_at_is_allowed(self):
        """Clearing an existing recurrence (doc has none, update clears) must
        not trip the recurrence-without-scheduled_at guard — the effective
        recurrence is None once the update lands."""
        existing = self._existing_doc(recurrence="daily")
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", recurrence=""
            )
        assert result == "Updated tracked todo t1: recurrence"

    async def test_labels_update_is_applied(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(labels=["work"]),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", labels=["work"]
            )
        assert result == "Updated tracked todo t1: labels"

    async def test_due_date_update_is_applied(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(due_date=_FUTURE),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", due_date=_FUTURE_ISO
            )
        assert result == "Updated tracked todo t1: due_date"

    async def test_expires_at_update_is_applied(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(expires_at=_FUTURE),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", expires_at=_FUTURE_ISO
            )
        assert result == "Updated tracked todo t1: expires_at"

    async def test_cron_recurrence_update_surfaces_ignored_scheduled_at_note(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(recurrence="0 9 * * *"),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.reschedule_execution",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="UTC",
            ) as mock_get_tz,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(),
                todo_id="t1",
                recurrence="0 9 * * *",
                scheduled_at=_FUTURE_ISO,
            )
        assert result == (
            "Updated tracked todo t1: scheduled_at, recurrence\n"
            "Notes:\n  - scheduled_at was ignored — for a cron recurrence the "
            "first fire is computed from the cron in your timezone."
        )
        mock_get_tz.assert_awaited_once_with("user-1")

    async def test_references_are_appended_and_reported(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(priority=Priority.HIGH),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.add_references",
                new_callable=AsyncMock,
            ) as mock_add_refs,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(),
                todo_id="t1",
                priority="high",
                references=["t2", "t3"],
            )
        mock_add_refs.assert_awaited_once_with("t1", user_id="user-1", references=["t2", "t3"])
        assert result == "Updated tracked todo t1: priority, references"

    async def test_update_returns_none_when_todo_disappears_mid_call(self):
        """The doc existed at the pre-check but the update call itself found
        nothing (raced delete) — must report not-found, not a silent no-op."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority="high"
            )
        assert "not found" in result


# ---------------------------------------------------------------------------
# create_tracked_todo — success path
# ---------------------------------------------------------------------------


class TestCreateTrackedTodoSuccess:
    def _response(self, **overrides) -> TodoResponse:
        now = datetime.now(UTC)
        base = {
            "id": "t1",
            "user_id": "user-1",
            "title": "t",
            "created_at": now,
            "updated_at": now,
        }
        base.update(overrides)
        return TodoResponse(**base)

    async def test_create_without_scheduling_returns_confirmation(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
            return_value=self._response(),
        ) as mock_create:
            result = await create_tracked_todo.coroutine(config=_config(), title="t")
        assert result == (
            "Tracked todo created: t1\n"
            "Title: t\n"
            "Canvas + activity log are stored on this todo — edit them ONLY via "
            "update_tracked_todo_canvas(todo_id='t1', ...), never with filesystem tools."
        )
        mock_create.assert_awaited_once_with(
            user_id="user-1",
            title="t",
            description=None,
            initial_canvas=None,
            labels=None,
            priority=Priority.NONE,
        )

    async def test_all_fields_are_forwarded_to_the_service(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
            return_value=self._response(),
        ) as mock_create:
            result = await create_tracked_todo.coroutine(
                config=_config(),
                title="My todo",
                description="desc",
                initial_canvas="# Canvas",
                labels=["work"],
                priority="high",
            )
        assert "Tracked todo created: t1" in result
        mock_create.assert_awaited_once_with(
            user_id="user-1",
            title="My todo",
            description="desc",
            initial_canvas="# Canvas",
            labels=["work"],
            priority=Priority.HIGH,
        )

    async def test_no_tz_lookup_without_recurrence(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ) as mock_get_tz,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
        ):
            await create_tracked_todo.coroutine(config=_config(), title="t")
        mock_get_tz.assert_not_awaited()

    async def test_recurrence_looks_up_user_tz_and_uses_it_in_the_output(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ) as mock_get_tz,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", recurrence="daily", scheduled_at=_FUTURE_ISO
            )
        mock_get_tz.assert_awaited_once_with("user-1")
        assert "scheduled in your timezone (America/New_York)" in result

    async def test_cron_recurrence_passes_user_tz_to_first_fire_resolution(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools._get_user_tz",
                new_callable=AsyncMock,
                return_value="America/New_York",
            ),
            patch(
                "app.agents.tools.tracked_todo_tools._resolve_first_fire",
                return_value=(_FUTURE, [], None),
            ) as mock_resolve,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await create_tracked_todo.coroutine(config=_config(), title="t", recurrence="0 9 * * *")
        mock_resolve.assert_called_once_with("0 9 * * *", None, "America/New_York")

    async def test_scheduling_fields_persisted_with_exact_args(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools._persist_scheduling_fields",
                new_callable=AsyncMock,
            ) as mock_persist,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await create_tracked_todo.coroutine(
                config=_config(), title="t", scheduled_at=_FUTURE_ISO, recurrence="daily"
            )
        mock_persist.assert_awaited_once_with("t1", "user-1", _FUTURE, "daily", None)

    async def test_scheduler_handoff_uses_todo_id_and_first_fire(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools._schedule_execution_after_create",
                new_callable=AsyncMock,
            ) as mock_schedule_after,
        ):
            await create_tracked_todo.coroutine(config=_config(), title="t", scheduled_at=_FUTURE_ISO)
        mock_schedule_after.assert_awaited_once_with("t1", _FUTURE)

    async def test_create_with_scheduled_at_persists_and_schedules(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_schedule,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", scheduled_at=_FUTURE_ISO
            )
        mock_schedule.assert_awaited_once()
        assert "First fire" in result or "first fire" in result

    async def test_schedule_failure_surfaces_warning_but_todo_still_created(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", scheduled_at=_FUTURE_ISO
            )
        assert "scheduling failed" in result

    async def test_cron_recurrence_with_scheduled_at_surfaces_the_ignored_note(self):
        """Passing both a cron recurrence and scheduled_at is allowed but the
        cron wins — the output must tell the caller scheduled_at was ignored,
        not silently drop it."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(),
                title="t",
                recurrence="0 9 * * *",
                scheduled_at=_FUTURE_ISO,
            )
        assert "Details:" in result
        assert "ignored" in result

    async def test_persist_scheduling_failure_is_surfaced_after_todo_is_already_created(self):
        """The todo row already exists by the time scheduling fields are
        persisted — a persist failure must still be reported to the caller,
        not swallowed just because create_tracked_todo itself succeeded."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", expires_at="garbage"
            )
        assert "invalid expires_at format" in result
