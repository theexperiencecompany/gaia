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

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools.tracked_todo_tools import (
    _apply_cron_first_fire,
    _build_clearable_datetime_update,
    _build_labels_update,
    _build_list_detail_parts,
    _build_priority_update,
    _build_recurrence_update,
    _build_scheduled_at_update,
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
    _strip_redundant_heading,
    _validate_recurrence_format,
    complete_tracked_todo,
    create_tracked_todo,
    list_tracked_todos,
    search_todo_context,
    update_tracked_todo,
    update_tracked_todo_canvas,
)
from app.models.todo_models import (
    Priority,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
    TrackedTodoDraft,
)
from shared.py.wide_events import spawn_logged_task

_FUTURE = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
_FUTURE_ISO = _FUTURE.isoformat()
_PAST_ISO = (datetime.now(UTC) - timedelta(days=1)).isoformat()

_TOOLS = "app.agents.tools.tracked_todo_tools"


def _config(user_id: str | None = "user-1") -> dict:
    return {"metadata": {"user_id": user_id}} if user_id else {"metadata": {}}


@dataclass(frozen=True)
class _CanvasSeams:
    """The facet-storage mocks one update_tracked_todo_canvas call talks to."""

    read: AsyncMock
    write: AsyncMock
    append: AsyncMock


@contextmanager
def _canvas_seams(
    *, existing_doc: TodoDocument | None, stored_facet: str | None = None
) -> Iterator[_CanvasSeams]:
    """Patch every seam update_tracked_todo_canvas reaches out to.

    ``stored_facet`` is what ``read_facet`` returns for the todo — None models a
    facet that has never been written.
    """
    with (
        patch(f"{_TOOLS}.todo_repository.get", new_callable=AsyncMock, return_value=existing_doc),
        patch(f"{_TOOLS}.read_facet", new_callable=AsyncMock, return_value=stored_facet) as read,
        patch(f"{_TOOLS}.write_facet", new_callable=AsyncMock) as write,
        patch(f"{_TOOLS}.append_facet", new_callable=AsyncMock) as append,
        patch(f"{_TOOLS}.tracked_todo_service.reindex_canvas", new_callable=AsyncMock),
        patch(f"{_TOOLS}.tracked_todo_service.system_log", new_callable=AsyncMock),
    ):
        yield _CanvasSeams(read=read, write=write, append=append)


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

    def test_a_heading_repeated_inside_the_section_body_is_not_doubled(self):
        """The patch re-emits the heading, so a copy the model put at the top of
        its body must be dropped rather than rendered twice."""
        result = _patch_canvas_section(
            "## Current State\nOld info.", "Current State", "## Current State\nNew info."
        )

        assert result == "## Current State\nNew info."


# ---------------------------------------------------------------------------
# _strip_redundant_heading
# ---------------------------------------------------------------------------


class TestStripRedundantHeading:
    def test_a_repeated_heading_on_the_first_line_is_dropped(self):
        assert _strip_redundant_heading("## Key Details\nBody", "Key Details") == "Body"

    def test_the_match_ignores_case_and_padding_on_both_sides(self):
        assert _strip_redundant_heading("  ## KEY DETAILS  \nBody", "key details  ") == "Body"

    def test_blank_lines_before_the_repeated_heading_are_skipped(self):
        assert _strip_redundant_heading("\n\n## Key Details\nBody", "Key Details") == "Body"

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("Body", "Body"),
            # The whole body is kept, not just its first line.
            ("First\nSecond", "First\nSecond"),
            # Blank lines under the heading go; the body's own indentation stays.
            ("\n\n  - indented point", "  - indented point"),
            # Nothing but newlines is trimmed off the front of the body.
            ("XML export done", "XML export done"),
        ],
    )
    def test_the_body_under_the_heading_is_kept_verbatim_after_blank_lines(self, body, expected):
        assert _strip_redundant_heading(f"## Key Details\n{body}", "Key Details") == expected

    @pytest.mark.parametrize(
        "content",
        [
            # A whitespace-only first line is a real first line, not padding.
            "  \n## Key Details\nBody",
            # Only newlines are skipped, never any other character.
            "X\n## Key Details\nBody",
            # A heading further down the body is the body's own, not a repeat.
            "Intro line\n## Key Details\nBody",
        ],
    )
    def test_content_whose_first_line_is_not_the_heading_is_returned_verbatim(self, content):
        assert _strip_redundant_heading(content, "Key Details") == content


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

    def test_invalid_format_rejected(self):
        fields: dict[str, object] = {}
        error = _build_scheduled_at_update("garbage", fields)
        assert error is not None
        assert "invalid scheduled_at format" in error
        assert fields == {}


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

    @pytest.mark.parametrize("value", list(Priority))
    def test_valid_priority_values(self, value):
        fields: dict[str, object] = {}
        assert _build_priority_update(value, fields) is None
        assert fields["priority"] == value.value


class TestBuildLabelsUpdate:
    def test_none_is_a_no_op(self):
        fields: dict[str, object] = {}
        assert _build_labels_update(None, fields) is None
        assert fields == {}

    def test_labels_are_set_exactly_as_passed(self):
        fields: dict[str, object] = {}
        _build_labels_update(["work"], fields)
        assert fields["labels"] == ["work"]

    def test_labels_are_not_deduplicated(self):
        fields: dict[str, object] = {}
        _build_labels_update(["work", "work"], fields)
        assert fields["labels"] == ["work", "work"]

    def test_empty_list_sets_labels_to_empty(self):
        # The unified todo model uses `assignee` as the GAIA discriminator, so
        # labels are the caller's own and set exactly as passed.
        fields: dict[str, object] = {}
        _build_labels_update([], fields)
        assert fields["labels"] == []


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
        error = _validate_recurrence_format("monthly")
        assert error is not None
        assert "Use one of:" in error
        assert "daily" in error


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

    def test_expired_is_flagged_with_the_days_elapsed_as_a_positive_count(self):
        now = datetime.now(UTC)
        doc = self._doc(expires_at=now - timedelta(days=2))
        assert _build_list_detail_parts(doc, now) == ["Expires: EXPIRED 2d ago"]

    def test_an_expiry_still_in_the_future_counts_down_instead_of_reading_expired(self):
        """Today's expiry rounds to 0 days out. It has not passed yet, so it must
        read as remaining time, not as already expired."""
        now = datetime.now(UTC)
        doc = self._doc(expires_at=now + timedelta(hours=1))
        assert _build_list_detail_parts(doc, now) == ["Expires: in 0d"]

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
        assert result == "Error: invalid mode 'overwrite'. Use 'replace', 'append', or 'section'."

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        result = await update_tracked_todo_canvas.coroutine(config={}, todo_id="t1", content="x")
        assert result == "Error: user_id not found in config"

    async def test_invalid_facet_is_rejected_and_names_every_valid_facet(self):
        """The model only recovers from this if the rejection lists what it may
        write to, so the message carries the facets in a stable sorted order."""
        result = await update_tracked_todo_canvas.coroutine(
            config=_config(), todo_id="t1", content="x", facet="scratch"
        )
        assert result == "Error: invalid facet 'scratch'. Use one of: deliverable, log, notes."

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

    async def test_no_fields_provided_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(), todo_id="t1")
        assert result == "No fields to update. Provide at least one field to change."

    async def test_clearing_scheduled_at_while_recurrence_remains_set_is_rejected(self):
        """The in-call guards alone can't see this: clearing scheduled_at while
        an existing recurrence stays set would leave a broken recurring todo
        with nothing to anchor it."""
        existing = TodoDocument(
            id="t1",
            user_id="u1",
            title="t",
            assignee="gaia",
            recurrence="daily",
            scheduled_at=_FUTURE,
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
                config=_config(), todo_id="missing", priority=Priority.HIGH
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

    @pytest.mark.regression
    def test_priority_is_an_enum_in_the_schema(self):
        # A str-typed priority let the model guess synonyms ("normal", "urgent")
        # that only failed inside the tool; the schema now closes the set.
        schema = update_tracked_todo.tool_call_schema.model_json_schema()
        assert schema["$defs"]["Priority"]["enum"] == [p.value for p in Priority]

    @pytest.mark.regression
    async def test_unknown_priority_is_refused_before_the_tool_runs(self):
        with pytest.raises(ValidationError):
            await update_tracked_todo.ainvoke(
                {"todo_id": "t1", "priority": "urgent"}, config=_config()
            )

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
        result = await create_tracked_todo.coroutine(
            config=_config(None), title="t", serves="s", requires_approval=False
        )
        assert "user_id not found" in result

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        # config with no "metadata" at all: the {} default keeps .get("user_id")
        # returning None -> clean error. A None default would crash on None.get().
        result = await create_tracked_todo.coroutine(
            config={}, title="t", serves="s", requires_approval=False
        )
        assert "user_id not found" in result

    @pytest.mark.regression
    def test_priority_is_an_enum_in_the_schema(self):
        schema = create_tracked_todo.tool_call_schema.model_json_schema()
        assert schema["$defs"]["Priority"]["enum"] == [p.value for p in Priority]

    @pytest.mark.regression
    async def test_unknown_priority_is_refused_before_the_tool_runs(self):
        with pytest.raises(ValidationError) as exc_info:
            await create_tracked_todo.ainvoke(
                {
                    "title": "t",
                    "serves": "s",
                    "requires_approval": False,
                    "priority": "urgent",
                },
                config=_config(),
            )
        assert [e["loc"] for e in exc_info.value.errors()] == [("priority",)]

    async def test_shortcut_recurrence_without_scheduled_at_returns_error(self):
        result = await create_tracked_todo.coroutine(
            config=_config(), title="t", serves="s", requires_approval=False, recurrence="daily"
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

    async def test_success_returns_confirmation(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.complete_tracked_todo",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await complete_tracked_todo.coroutine(
                config=_config(), todo_id="t1", summary="done"
            )
        assert "completed and archived" in result


# ---------------------------------------------------------------------------
# _get_user_tz
# ---------------------------------------------------------------------------


class TestGetUserTz:
    async def test_valid_timezone_is_returned(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value={"timezone": "America/New_York"},
        ):
            tz = await _get_user_tz("u1")
        assert tz == "America/New_York"

    async def test_invalid_timezone_name_falls_back_to_utc(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value={"timezone": "Not/A_Real_Zone"},
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"

    async def test_no_user_found_falls_back_to_utc(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value=None,
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"

    async def test_lookup_failure_falls_back_to_utc_not_a_crash(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            side_effect=RuntimeError("mongo down"),
        ):
            tz = await _get_user_tz("u1")
        assert tz == "UTC"


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
# _resolve_cron_first_fire — exception path
# ---------------------------------------------------------------------------


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
        # Pinned whole: the note has to say WHICH input won and where the time
        # came from, or the user reads "ignored" and cannot tell what was booked.
        assert notes == [
            "scheduled_at was ignored: for a cron recurrence the first fire "
            "is computed from the cron in the user's timezone."
        ]

    def test_no_note_when_scheduled_at_not_provided(self):
        parsed, notes, error = _resolve_cron_first_fire("0 9 * * *", None, "UTC")
        assert error is None
        assert notes == []


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
        mock_update.assert_awaited_once_with(
            "t1", user_id="u1", update=TodoUpdate(scheduled_at=_FUTURE, recurrence="daily")
        )

    async def test_a_z_suffixed_expires_at_is_persisted_as_a_utc_datetime(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, "2030-01-02T03:04:05Z")
        assert error is None
        mock_update.assert_awaited_once_with(
            "t1",
            user_id="u1",
            update=TodoUpdate(expires_at=datetime(2030, 1, 2, 3, 4, 5, tzinfo=UTC)),
        )

    async def test_a_lowercase_z_suffix_is_rejected_as_a_bad_format(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, "2030-01-02T03:04:05z")
        assert error == "Error: invalid expires_at format '2030-01-02T03:04:05z'."
        mock_update.assert_not_awaited()

    async def test_invalid_expires_at_format_returns_error_without_persisting(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.update",
            new_callable=AsyncMock,
        ) as mock_update:
            error = await _persist_scheduling_fields("t1", "u1", None, None, "garbage")
        assert error == "Error: invalid expires_at format 'garbage'."
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
        ):
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert error is None

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
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
            new_callable=AsyncMock,
            side_effect=RuntimeError("arq connection lost"),
        ):
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert "scheduling failed" in error
        assert "arq connection lost" in error


# ---------------------------------------------------------------------------
# _format_first_fire_note
# ---------------------------------------------------------------------------


class TestFormatCreateOutput:
    def test_the_summary_routes_facet_edits_away_from_filesystem_tools(self) -> None:
        """The facets live on the todo, not on disk. Without this line the model
        reaches for the file tools, edits nothing the todo can see, and reports
        success — so the sentence is the guardrail, pinned verbatim."""
        now = datetime.now(UTC)
        result = TodoResponse(id="t1", user_id="user-1", title="t", created_at=now, updated_at=now)

        out = _format_create_output(result, None, None, [])

        assert (
            "Its facets (deliverable / notes / log) are stored on this todo. Edit them "
            "ONLY via update_tracked_todo_canvas(todo_id='t1', facet=..., ...), "
            "never with filesystem tools."
        ) in out

    def test_the_first_fire_note_is_appended_to_the_summary_in_the_users_timezone(self) -> None:
        """The note is an addition to the confirmation, not a replacement for it,
        and it is rendered in the timezone the caller resolved."""
        now = datetime.now(UTC)
        result = TodoResponse(id="t1", user_id="user-1", title="t", created_at=now, updated_at=now)

        out = _format_create_output(result, _FUTURE, "Asia/Kolkata", [])

        assert out.startswith("Tracked todo created: t1\nTitle: t\n")
        assert out.endswith(_format_first_fire_note(_FUTURE, "Asia/Kolkata"))
        assert "your timezone (Asia/Kolkata)" in out


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
        # The update path addresses the user directly ("your timezone"), unlike
        # the create path's third-person copy — same fact, different speaker.
        assert notes == [
            "scheduled_at was ignored: for a cron recurrence the first fire "
            "is computed from the cron in your timezone."
        ]
        assert isinstance(fields["scheduled_at"], datetime)


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
            labels=["work", "urgent"],
            priority=Priority.HIGH,
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(days=1),
        )
        result = _format_tracked_todo_full(doc, now)
        assert result == (
            '- "My todo" [work, urgent] (ID: t1)\n  Priority: high | Age: 3d | Last updated: 1d ago'
        )

    def test_a_todo_with_no_title_is_labelled_untitled_and_carries_no_label_brackets(self):
        now = datetime.now(UTC)
        doc = TodoDocument(id="t1", user_id="u1", title="", created_at=now, updated_at=now)
        result = _format_tracked_todo_full(doc, now)
        assert result == (
            '- "Untitled" (ID: t1)\n  Priority: none | Age: 0d | Last updated: 0d ago'
        )

    def test_includes_detail_line_when_scheduling_fields_present(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="Scheduled todo",
            recurrence="daily",
            due_date=now + timedelta(days=4),
            created_at=now,
            updated_at=now,
        )
        result = _format_tracked_todo_full(doc, now)
        assert result == (
            '- "Scheduled todo" (ID: t1)\n'
            "  Priority: none | Age: 0d | Last updated: 0d ago\n"
            "  Due: 4d | Recurrence: daily"
        )


# ---------------------------------------------------------------------------
# search_todo_context
# ---------------------------------------------------------------------------


class TestSearchTodoContext:
    async def test_missing_user_id_returns_error(self):
        result = await search_todo_context.coroutine(config=_config(None), query="q")
        assert "user_id not found" in result

    async def test_no_matches_returns_friendly_message(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")
        assert result == "No matching tracked todo context found."

    async def test_matches_are_formatted_with_score_and_snippet(self):
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
        assert "My todo" in result
        assert "t1" in result
        assert "some context" in result
        assert "[completed]" not in result

    async def test_completed_match_is_flagged(self):
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
        assert "[completed]" in result


# ---------------------------------------------------------------------------
# update_tracked_todo_canvas — success paths
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoCanvasSuccess:
    def _existing_doc(self) -> TodoDocument:
        return TodoDocument(id="t1", user_id="user-1", title="t")

    async def test_append_mode_calls_append_facet(self):
        with _canvas_seams(existing_doc=self._existing_doc()) as seams:
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="new note", mode="append"
            )
        seams.append.assert_awaited_once_with("t1", "user-1", "notes", "new note")
        seams.write.assert_not_awaited()
        assert result == "Updated notes (mode=append)."

    async def test_replace_mode_calls_write_facet(self):
        with _canvas_seams(existing_doc=self._existing_doc()) as seams:
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(), todo_id="t1", content="full rewrite", mode="replace"
            )
        seams.write.assert_awaited_once_with("t1", "user-1", "notes", "full rewrite")
        seams.append.assert_not_awaited()
        assert result == "Updated notes (mode=replace)."

    async def test_section_mode_reads_current_facet_and_patches_it(self):
        with _canvas_seams(
            existing_doc=self._existing_doc(), stored_facet="## Notes\nold\n\n## Log\nentry"
        ) as seams:
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="new",
                mode="section",
                section="Notes",
            )
        seams.read.assert_awaited_once_with("t1", "user-1", "notes")
        seams.write.assert_awaited_once_with(
            "t1", "user-1", "notes", "## Notes\nnew\n\n## Log\nentry"
        )
        assert result == "Updated notes (mode=section, section=Notes)."

    async def test_section_mode_on_a_facet_that_was_never_written_creates_the_section(self):
        """read_facet returns None for an unwritten facet; the patch must start
        from an empty canvas, not from a stand-in string."""
        with _canvas_seams(existing_doc=self._existing_doc(), stored_facet=None) as seams:
            await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="new",
                mode="section",
                section="Notes",
            )
        seams.write.assert_awaited_once_with("t1", "user-1", "notes", "\n\n## Notes\nnew")

    async def test_a_non_notes_facet_is_read_and_written_on_its_own(self):
        with _canvas_seams(
            existing_doc=self._existing_doc(), stored_facet="## Draft\nold"
        ) as seams:
            result = await update_tracked_todo_canvas.coroutine(
                config=_config(),
                todo_id="t1",
                content="polished",
                mode="section",
                section="Draft",
                facet="deliverable",
            )
        seams.read.assert_awaited_once_with("t1", "user-1", "deliverable")
        seams.write.assert_awaited_once_with("t1", "user-1", "deliverable", "## Draft\npolished")
        assert result == "Updated deliverable (mode=section, section=Draft)."


# ---------------------------------------------------------------------------
# update_tracked_todo — success path
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoSuccess:
    def _existing_doc(self, **overrides) -> TodoDocument:
        base = {"id": "t1", "user_id": "user-1", "title": "t", "assignee": "gaia"}
        base.update(overrides)
        return TodoDocument(**base)

    async def test_priority_update_persists_and_reports_updated_keys(self):
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
            ) as mock_update,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority=Priority.HIGH
            )
        mock_update.assert_awaited_once_with(
            "t1", user_id="user-1", update=TodoUpdate(priority=Priority.HIGH)
        )
        assert result == "Updated tracked todo t1: priority"

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
            ) as mock_tz,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(),
                todo_id="t1",
                recurrence="0 9 * * *",
                scheduled_at=_FUTURE_ISO,
            )
        assert "Notes:" in result
        assert "ignored" in result
        # The cron first-fire is computed in the OWNER's timezone, so the user_id
        # must reach the tz lookup, not be dropped along the validator chain.
        mock_tz.assert_awaited_once_with("user-1")

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
                priority=Priority.HIGH,
                references=["t2", "t3"],
            )
        mock_add_refs.assert_awaited_once_with("t1", user_id="user-1", references=["t2", "t3"])
        assert "references" in result

    async def test_labels_update_persists_and_reports_key(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", labels=["gaia-tracked", "urgent"]
            )
        assert "labels" in result

    async def test_due_date_update_persists_and_reports_key(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", due_date=_FUTURE_ISO
            )
        assert "due_date" in result

    async def test_expires_at_update_persists_and_reports_key(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", expires_at=_FUTURE_ISO
            )
        assert "expires_at" in result

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
                config=_config(), todo_id="t1", priority=Priority.HIGH
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
        ) as create:
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", serves="s", requires_approval=False
            )
        # Unsupplied arguments must reach the service as the draft's own
        # defaults — in particular kind='task' and auto_execute=True, which
        # decide whether the todo is a goal lane and whether it runs now.
        create.assert_awaited_once_with(
            "user-1", TrackedTodoDraft(title="t", serves="s", requires_approval=False)
        )
        assert "Tracked todo created: t1" in result
        assert "update_tracked_todo_canvas(todo_id='t1'" in result

    async def test_every_supplied_property_reaches_the_draft_the_service_receives(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
            return_value=self._response(),
        ) as create:
            await create_tracked_todo.coroutine(
                config={
                    "configurable": {"conversation_id": "conv-9"},
                    "metadata": {"user_id": "user-1"},
                },
                title="Ship the deck",
                serves="raising a pre-seed round",
                requires_approval=True,
                kind="goal",
                goal_id="goal-1",
                description="the description",
                initial_deliverable="the deliverable",
                initial_notes="the notes",
                labels=["work", "urgent"],
                priority="high",
            )
        create.assert_awaited_once_with(
            "user-1",
            TrackedTodoDraft(
                title="Ship the deck",
                serves="raising a pre-seed round",
                requires_approval=True,
                kind="goal",
                goal_id="goal-1",
                description="the description",
                initial_deliverable="the deliverable",
                initial_notes="the notes",
                labels=["work", "urgent"],
                priority=Priority.HIGH,
                source_conversation_id="conv-9",
                auto_execute=True,
            ),
        )

    async def test_source_conversation_id_is_read_from_configurable_and_passed_through(self):
        # The chat the todo was created in is captured and handed to the service so
        # a later fire can be pushed back into that chat. build_agent_config puts
        # conversation_id in `configurable` (not `metadata`, which only carries
        # user_id/langfuse fields), so the tool must read it from there — matching
        # reminder_tool. Reading metadata yields None in production.
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
            return_value=self._response(),
        ) as create:
            await create_tracked_todo.coroutine(
                config={
                    "configurable": {"conversation_id": "conv-9"},
                    "metadata": {"user_id": "user-1"},
                },
                title="t",
                serves="s",
                requires_approval=False,
            )
        draft = create.await_args.args[1]
        assert draft.source_conversation_id == "conv-9"

    async def test_create_with_scheduled_at_persists_and_schedules(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ) as create,
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ) as mock_update,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_schedule,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(),
                title="t",
                serves="s",
                requires_approval=False,
                scheduled_at=_FUTURE_ISO,
            )
        # The scheduling fields land on the row the service just created, for
        # the same user — a wrong id here writes to somebody else's todo.
        mock_update.assert_awaited_once_with(
            "t1", user_id="user-1", update=TodoUpdate(scheduled_at=_FUTURE)
        )
        # A todo that arms its own schedule must NOT also run on creation.
        assert create.await_args.args[1].auto_execute is False
        mock_schedule.assert_awaited_once_with("t1", _FUTURE)
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
                config=_config(),
                title="t",
                serves="s",
                requires_approval=False,
                scheduled_at=_FUTURE_ISO,
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
            ) as mock_update,
            patch(
                "app.agents.tools.tracked_todo_tools.get_next_run_time",
                return_value=_FUTURE,
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
                serves="s",
                requires_approval=False,
                recurrence="0 9 * * *",
                scheduled_at=_FUTURE_ISO,
            )
        # The cron itself is persisted alongside its computed first fire —
        # without the recurrence the todo would fire once and never repeat.
        mock_update.assert_awaited_once_with(
            "t1",
            user_id="user-1",
            update=TodoUpdate(scheduled_at=_FUTURE, recurrence="0 9 * * *"),
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
                config=_config(),
                title="t",
                serves="s",
                requires_approval=False,
                expires_at="garbage",
            )
        assert "invalid expires_at format" in result


# ---------------------------------------------------------------------------
# list_tracked_todos
# ---------------------------------------------------------------------------


class TestListTrackedTodos:
    async def test_missing_user_id_returns_error(self):
        result = await list_tracked_todos.coroutine(config=_config(None))
        assert "user_id not found" in result

    async def test_no_active_todos_returns_friendly_message(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_tracked_todos.coroutine(config=_config())
        assert result == "No active tracked todos."

    async def test_active_todos_are_listed_with_count(self):
        """The listing is what the model reads to pick a todo, so the blank line
        between entries and the timezone-aware ages are part of the contract."""
        created = datetime.now(UTC) - timedelta(days=2)
        docs = [
            TodoDocument(
                id="t1", user_id="user-1", title="First", created_at=created, updated_at=created
            ),
            TodoDocument(
                id="t2", user_id="user-1", title="Second", created_at=created, updated_at=created
            ),
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=docs,
        ):
            result = await list_tracked_todos.coroutine(config=_config())
        assert result == (
            "Active tracked todos (2):\n"
            "\n"
            '- "First" (ID: t1)\n'
            "  Priority: none | Age: 2d | Last updated: 2d ago\n"
            "\n"
            '- "Second" (ID: t2)\n'
            "  Priority: none | Age: 2d | Last updated: 2d ago"
        )
