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

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools.tracked_todo_tools import (
    _build_clearable_datetime_update,
    _build_labels_update,
    _build_list_detail_parts,
    _build_priority_update,
    _build_recurrence_update,
    _build_scheduled_at_update,
    _is_cron_expression,
    _parse_iso_future_datetime,
    _patch_canvas_section,
    _resolve_first_fire,
    _validate_recurrence_format,
    complete_tracked_todo,
    create_tracked_todo,
    update_tracked_todo,
    update_tracked_todo_canvas,
)
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import TodoDocument

pytestmark = pytest.mark.unit

_FUTURE = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
_FUTURE_ISO = _FUTURE.isoformat()
_PAST_ISO = (datetime.now(UTC) - timedelta(days=1)).isoformat()


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
        assert "must be in the future" in error

    def test_invalid_format_rejected(self):
        parsed, error = _parse_iso_future_datetime("not-a-date", "scheduled_at")
        assert parsed is None
        assert "invalid scheduled_at format" in error

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
        assert "must be in the future" in error
        assert fields == {}

    def test_valid_future_datetime_sets_the_field(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update(_FUTURE_ISO, fields)
        assert error is None
        assert fields["scheduled_at"] == _FUTURE


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

    def test_unknown_shortcut_word_is_rejected(self):
        error = _validate_recurrence_format("monthly")
        assert error is not None


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
        assert "requires scheduled_at" in error

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
        ):
            error = await _build_recurrence_update("0 9 * * *", None, "u1", fields, notes)

        assert error is None
        assert fields["recurrence"] == "0 9 * * *"
        assert isinstance(fields["scheduled_at"], datetime)

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
        assert any("OVERDUE" in p for p in parts)

    def test_future_due_date_is_not_flagged_overdue(self):
        now = datetime.now(UTC)
        doc = self._doc(due_date=now + timedelta(days=3))
        parts = _build_list_detail_parts(doc, now)
        assert not any("OVERDUE" in p for p in parts)
        assert any("Due: 3d" in p for p in parts)

    def test_expired_is_flagged(self):
        now = datetime.now(UTC)
        doc = self._doc(expires_at=now - timedelta(days=2))
        parts = _build_list_detail_parts(doc, now)
        assert any("EXPIRED" in p for p in parts)

    def test_retry_count_shown_only_when_positive(self):
        now = datetime.now(UTC)
        doc = self._doc(gaia_retry_count=0)
        assert not any("Retries" in p for p in _build_list_detail_parts(doc, now))
        doc2 = self._doc(gaia_retry_count=2)
        assert any("Retries: 2" in p for p in _build_list_detail_parts(doc2, now))


# ---------------------------------------------------------------------------
# Tool-level: update_tracked_todo_canvas mode validation
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoCanvasValidation:
    async def test_missing_user_id_returns_error(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(None), todo_id="t1", content="x"
        )
        assert "user_id not found" in result

    async def test_invalid_mode_rejected(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(), todo_id="t1", content="x", mode="overwrite"
        )
        assert "invalid mode" in result

    async def test_section_mode_without_section_name_rejected(self):
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(), todo_id="t1", content="x", mode="section", section=None
        )
        assert "requires a section name" in result

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

    async def test_no_fields_provided_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(), todo_id="t1")
        assert "No fields to update" in result

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
        assert "cannot have recurrence without scheduled_at" in result

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


# ---------------------------------------------------------------------------
# Tool-level: create_tracked_todo — validation short-circuits
# ---------------------------------------------------------------------------


class TestCreateTrackedTodoValidation:
    async def test_missing_user_id_returns_error(self):
        result = await create_tracked_todo.coroutine(config=_config(None), title="t")
        assert "user_id not found" in result

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
