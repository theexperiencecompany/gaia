"""Unit tests for app.agents.tools.tracked_todo_tools.

Heavy focus on the pure helper functions (datetime/recurrence validation,
update-field builders) — no mocking needed, and this is exactly where the real
bugs in this file were hiding: both _parse_iso_future_datetime and
_build_scheduled_at_update raised an unhandled TypeError (instead of a clean
validation error) on a timezone-naive ISO datetime. Fixed at the root in
tracked_todo_tools.py; the tests here pin the fix down.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import pytest

from app.agents.tools import tracked_todo_tools
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
    _resolve_cron_first_fire,
    _resolve_first_fire,
    _schedule_execution_after_create,
    _validate_recurrence_format,
    complete_tracked_todo,
    create_tracked_todo,
    list_tracked_todos,
    search_todo_context,
    update_tracked_todo,
)
from app.constants import todos as todo_constants
from app.constants.todos import GAIA_TRACKED_LABEL
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    Priority,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
)
from app.models.user_models import UserDocument
from app.services.todos.errors import ExternalRefTakenError
from app.services.triggers.subscription_service import SubscriptionError
from shared.py.wide_events import spawn_logged_task

_FUTURE = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
_FUTURE_ISO = _FUTURE.isoformat()
_PAST_ISO = (datetime.now(UTC) - timedelta(days=1)).isoformat()


@pytest.fixture(autouse=True)
def recorded_changes() -> Iterator[AsyncMock]:
    """Capture the scheduling changes the tools put on a todo's timeline."""
    with patch(
        "app.agents.tools.tracked_todo_tools.record_field_changes", new_callable=AsyncMock
    ) as recorded:
        yield recorded


def _config(user_id: str | None = "user-1") -> dict:
    return {"metadata": {"user_id": user_id}} if user_id else {"metadata": {}}


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
        """Regression: a naive datetime used to raise an unhandled TypeError instead of a clean validation error."""
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

    @pytest.mark.regression
    @pytest.mark.parametrize("value", ["2026-09-30", "2026-09-30T17:00:00"])
    def test_a_date_without_an_offset_is_refused(self, value):
        """A naive wall time would be saved as UTC, off by the user's offset."""
        fields: dict[str, object] = {}
        error = _build_clearable_datetime_update(value, "due_date", fields)
        assert error == f"Error: due_date '{value}' must include a timezone offset."
        assert fields == {}

    def test_valid_datetime_sets_field_no_future_requirement(self):
        """Unlike scheduled_at, due_date/expires_at may legitimately be in the past (an overdue due_date is still meaningful)."""
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
        """A typo'd shortcut is neither a known shortcut nor a valid cron — the error must still point the caller at the valid shortcut options, not just say "invalid"."""
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
    """The update-path equivalent of _resolve_first_fire — recomputes the cron first-fire against the user's stored timezone (a real Mongo lookup via _get_user_tz, mocked here at that boundary)."""

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
        """A shortcut ("daily") has no cron to recompute a first-fire from — scheduled_at is update_tracked_todo's own guard, required separately."""
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
# Tool-level: update_tracked_todo — recurrence-without-scheduled_at guard
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoValidation:
    async def test_missing_user_id_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(None), todo_id="t1")
        assert "user_id not found" in result

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        result = await update_tracked_todo.coroutine(config={}, todo_id="t1")
        assert "user_id not found" in result

    async def test_no_fields_provided_returns_error(self):
        result = await update_tracked_todo.coroutine(config=_config(), todo_id="t1")
        assert "No fields to update" in result

    async def test_clearing_scheduled_at_while_recurrence_remains_set_is_rejected(self):
        """The in-call guards alone can't see this: clearing scheduled_at while an existing recurrence stays set would leave a broken recurring todo with nothing to anchor it."""
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

    @pytest.mark.parametrize("value", [True, False])
    async def test_toggling_delivery_writes_that_field(self, value):
        """A mistyped key or a dropped value leaves the todo on its old setting, silently."""
        existing = TodoDocument(id="t1", user_id="u1", title="t")
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=existing,
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
                return_value=existing,
            ) as update,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", notify_on_run=value
            )

        written = update.await_args.kwargs["update"]
        assert written.model_dump(exclude_unset=True) == {"notify_on_run": value}
        assert "notify_on_run" in result

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
        result = await create_tracked_todo.coroutine(config=_config(None), title="t")
        assert "user_id not found" in result

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        # config with no "metadata" at all: the {} default keeps .get("user_id")
        # returning None -> clean error. A None default would crash on None.get().
        result = await create_tracked_todo.coroutine(config={}, title="t")
        assert "user_id not found" in result

    @pytest.mark.regression
    def test_priority_is_an_enum_in_the_schema(self):
        schema = create_tracked_todo.tool_call_schema.model_json_schema()
        assert schema["$defs"]["Priority"]["enum"] == [p.value for p in Priority]

    @pytest.mark.regression
    async def test_unknown_priority_is_refused_before_the_tool_runs(self):
        with pytest.raises(ValidationError):
            await create_tracked_todo.ainvoke(
                {"title": "t", "priority": "urgent"}, config=_config()
            )

    async def test_a_new_tracked_todo_delivers_its_run_results_by_default(self):
        """The agent usually omits this argument, so the default is what almost every todo gets."""
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
        ) as create:
            create.return_value = TodoResponse(
                id="t1",
                user_id="u1",
                title="t",
                created_at=_FUTURE,
                updated_at=_FUTURE,
            )
            await create_tracked_todo.coroutine(config=_config(), title="t")

        assert create.await_args.kwargs["notify_on_run"] is True

    async def test_the_agent_can_create_a_silent_tracked_todo(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
        ) as create:
            create.return_value = TodoResponse(
                id="t1",
                user_id="u1",
                title="t",
                created_at=_FUTURE,
                updated_at=_FUTURE,
            )
            await create_tracked_todo.coroutine(config=_config(), title="t", notify_on_run=False)

        assert create.await_args.kwargs["notify_on_run"] is False

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

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        result = await complete_tracked_todo.coroutine(config={}, todo_id="t1", summary="done")
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
            return_value=UserDocument(timezone="America/New_York"),
        ):
            tz = await _get_user_tz("u1")
        assert tz == "America/New_York"

    async def test_invalid_timezone_name_falls_back_to_utc(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.get_user_by_id",
            new_callable=AsyncMock,
            return_value=UserDocument(timezone="Not/A_Real_Zone"),
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

    async def test_no_user_found_records_only_the_fallback_warning(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.get_user_by_id",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("app.agents.tools.tracked_todo_tools.log") as mock_log,
        ):
            await _get_user_tz("u1")
        mock_log.warning.assert_called_once_with("tracked_todo.user_tz_fallback_utc", user_id="u1")

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
# _creation_field_update
# ---------------------------------------------------------------------------


class TestCreationFieldUpdate:
    def test_nothing_to_set_is_no_update(self):
        assert tracked_todo_tools._creation_field_update(None, None, None, None) == (None, None)

    def test_an_empty_date_is_unset_not_a_clear(self):
        assert tracked_todo_tools._creation_field_update(None, None, "", "") == (None, None)

    def test_collects_every_field_the_create_sets(self):
        update, error = tracked_todo_tools._creation_field_update(
            _FUTURE, "daily", _PAST_ISO, _FUTURE_ISO
        )
        assert error is None
        assert update.scheduled_at == _FUTURE
        assert update.recurrence == "daily"
        # A past due date is still a deadline: overdue work still needs doing.
        assert update.due_date == datetime.fromisoformat(_PAST_ISO)
        assert update.expires_at == _FUTURE

    @pytest.mark.parametrize("field", ["due_date", "expires_at"])
    def test_an_unparseable_date_is_an_error(self, field):
        dates = {"due_date": None, "expires_at": None, field: "garbage"}
        update, error = tracked_todo_tools._creation_field_update(_FUTURE, "daily", **dates)
        assert update is None
        assert error == f"Error: invalid {field} format 'garbage'."


# ---------------------------------------------------------------------------
# _schedule_execution_after_create
# ---------------------------------------------------------------------------


class TestScheduleExecutionAfterCreate:
    async def test_success_returns_none(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
            new_callable=AsyncMock,
            return_value=True,
        ) as schedule:
            error = await _schedule_execution_after_create("t1", _FUTURE)
        assert error is None
        schedule.assert_awaited_once_with("t1", _FUTURE)

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
    def test_the_summary_routes_canvas_edits_away_from_filesystem_tools(self) -> None:
        """The create result names the exact folder (slug + short id) and both files, so the model finds its notes by path."""
        now = datetime.now(UTC)
        result = TodoResponse(
            id="66f838cc8829054e5f10e407",
            user_id="user-1",
            title="Fix the thing",
            created_at=now,
            updated_at=now,
        )

        out = _format_create_output(result, None, None, [])

        assert "/workspace/gaia-tasks/fix-the-thing-5f10e407/canvas.md" in out
        assert "/workspace/gaia-tasks/fix-the-thing-5f10e407/activity.md" in out
        # The instruction sentence is verbatim: it is the model's cue for which
        # tools read/edit the notes.
        assert " (dated log). Read and edit them with the read / edit / write tools." in out
        assert "update_tracked_todo_canvas" not in out


class TestFormatFirstFireNote:
    def test_with_valid_user_timezone(self):
        note = _format_first_fire_note(_FUTURE, "America/New_York")
        assert "your timezone (America/New_York)" in note
        assert "update_tracked_todo" in note

    def test_without_user_timezone_shows_utc(self):
        note = _format_first_fire_note(_FUTURE, None)
        assert "UTC" in note

    def test_invalid_timezone_falls_back_to_utc_note_not_a_crash(self):
        """Timezone.parse itself never raises (it falls back to UTC with a warning log); this exercises that graceful path, not the astimezone except-branch below."""
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

    def test_names_the_notes_folder_so_the_agent_can_read_without_a_second_lookup(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="66f838cc8829054e5f10e407",
            user_id="u1",
            title="Fix the thing",
            labels=[GAIA_TRACKED_LABEL],
            created_at=now,
            updated_at=now,
        )

        result = _format_tracked_todo_full(doc, now)

        assert "files: /workspace/gaia-tasks/fix-the-thing-5f10e407/" in result

    def test_a_thread_todo_names_the_thread_it_owns(self):
        now = datetime.now(UTC)
        doc = TodoDocument(
            id="t1",
            user_id="u1",
            title="Reply to Sam",
            external_ref=ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18f3a2b"),
            created_at=now,
            updated_at=now,
        )
        assert "Owns gmail_thread: 18f3a2b" in _format_tracked_todo_full(doc, now)

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


# ---------------------------------------------------------------------------
# search_todo_context
# ---------------------------------------------------------------------------


class TestSearchTodoContext:
    async def test_missing_user_id_returns_error(self):
        result = await search_todo_context.coroutine(config=_config(None), query="q")
        assert "user_id not found" in result

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        result = await search_todo_context.coroutine(config={}, query="q")
        assert "user_id not found" in result

    async def test_matches_render_one_block_per_line_with_a_200_char_snippet(self):
        matches = [
            {
                "title": "Fix the thing",
                "todo_id": "66f838cc8829054e5f10e407",
                "score": 0.9,
                "snippet": "a" * 250,
                "completed": True,
            },
            {
                "title": "Fix the thing",
                "todo_id": "66f838cc8829054e5f10e407",
                "score": 0.5,
                "snippet": "short",
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
            "- [Fix the thing] [completed] (todo_id: 66f838cc8829054e5f10e407, score: 0.9)\n"
            "  files: /workspace/gaia-tasks/fix-the-thing-5f10e407/\n"
            f"  {'a' * 200}\n"
            "- [Fix the thing] (todo_id: 66f838cc8829054e5f10e407, score: 0.5)\n"
            "  files: /workspace/gaia-tasks/fix-the-thing-5f10e407/\n"
            "  short"
        )

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

    async def test_matches_name_the_notes_folder(self):
        matches = [
            {
                "title": "Fix the thing",
                "todo_id": "66f838cc8829054e5f10e407",
                "score": 0.9,
                "snippet": "ctx",
                "completed": True,
            }
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.search_canvas_context",
            new_callable=AsyncMock,
            return_value=matches,
        ):
            result = await search_todo_context.coroutine(config=_config(), query="q")

        assert "files: /workspace/gaia-tasks/fix-the-thing-5f10e407/" in result

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
# update_tracked_todo — success path
# ---------------------------------------------------------------------------


class TestUpdateTrackedTodoSuccess:
    def _existing_doc(self, **overrides) -> TodoDocument:
        base = {"id": "t1", "user_id": "user-1", "title": "t"}
        base.update(overrides)
        return TodoDocument(**base)

    async def test_clearing_recurrence_on_an_unscheduled_todo_persists_the_clear(self):
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
            ) as mock_update,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", recurrence=""
            )
        assert result == "Updated tracked todo t1: recurrence"
        mock_update.assert_awaited_once_with(
            "t1", user_id="user-1", update=TodoUpdate.model_validate({"recurrence": None})
        )

    async def test_a_reschedule_names_the_conversation_that_made_it(self, recorded_changes):
        """Regression for 2026-09-26: a chat scheduled the wrong todo and nothing on it said which."""
        config = {
            "metadata": {"user_id": "user-1"},
            "configurable": {"conversation_id": "00f7c88f-4ac1-4169-86ed-eff3a9027e78"},
        }
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
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
            ),
        ):
            await update_tracked_todo.coroutine(
                config=config, todo_id="t1", scheduled_at=_FUTURE_ISO
            )

        todo_id, user_id, update = recorded_changes.await_args.args
        assert (todo_id, user_id) == ("t1", "user-1")
        assert update.model_fields_set == {"scheduled_at"}
        assert recorded_changes.await_args.kwargs == {"by": "GAIA in conversation 00f7c88f"}

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
            ),
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority=Priority.HIGH
            )
        assert "Updated tracked todo t1: priority" in result

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
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
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
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
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
        refs = ["66f838cc8829054e5f10e402", "66f838cc8829054e5f10e403"]
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.get",
                new_callable=AsyncMock,
                return_value=self._existing_doc(),
            ),
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.find_by_ids",
                new_callable=AsyncMock,
                return_value=[
                    self._existing_doc(id=ref, labels=[GAIA_TRACKED_LABEL]) for ref in refs
                ],
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
                references=refs,
            )
        mock_add_refs.assert_awaited_once_with("t1", user_id="user-1", references=refs)
        assert result == "Updated tracked todo t1: priority, references"

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
        """The doc existed at the pre-check but the update call itself found nothing (raced delete) — must report not-found, not a silent no-op."""
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
        ):
            result = await create_tracked_todo.coroutine(config=_config(), title="t")
        assert "Tracked todo created: t1" in result
        assert "/workspace/gaia-tasks/" in result and "canvas.md" in result

    async def test_source_conversation_id_is_read_from_configurable_and_passed_through(self):
        # build_agent_config puts conversation_id in configurable, not metadata (which only
        # carries user_id/langfuse fields), so the tool must read it from there, matching
        # reminder_tool — reading metadata yields None in production.
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
            )
        assert create.await_args.kwargs["source_conversation_id"] == "conv-9"

    async def test_create_with_scheduled_at_persists_and_schedules(self):
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
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
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
                side_effect=ConnectionError("redis down"),
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", scheduled_at=_FUTURE_ISO
            )
        assert "scheduling failed" in result

    async def test_cron_recurrence_with_scheduled_at_surfaces_the_ignored_note(self):
        """Passing both a cron recurrence and scheduled_at is allowed but the cron wins — the output must tell the caller scheduled_at was ignored, not silently drop it."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
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

    @pytest.mark.parametrize("field", ["due_date", "expires_at"])
    async def test_an_unparseable_date_creates_nothing(self, field):
        """A create that reports an error must not leave a todo behind for the retry to duplicate."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ) as create,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", **{field: "garbage"}
            )
        assert f"invalid {field} format" in result
        create.assert_not_awaited()

    @pytest.mark.regression
    async def test_a_create_saves_its_schedule_with_the_insert(self, recorded_changes):
        """A second write after the insert left a half-made todo behind when it failed, for a retry to duplicate."""
        with (
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
                new_callable=AsyncMock,
                return_value=self._response(),
            ) as create,
            patch(
                "app.agents.tools.tracked_todo_tools.todo_repository.update",
                new_callable=AsyncMock,
            ) as update,
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
            ),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(),
                title="t",
                scheduled_at=_FUTURE_ISO,
                recurrence="daily",
                due_date=_PAST_ISO,
                expires_at=_FUTURE_ISO,
            )

        assert "Tracked todo created: t1" in result
        schedule = create.await_args.kwargs["schedule"]
        assert schedule.model_fields_set == {"scheduled_at", "recurrence", "due_date", "expires_at"}
        assert schedule.scheduled_at == _FUTURE
        assert schedule.recurrence == "daily"
        assert schedule.due_date == datetime.fromisoformat(_PAST_ISO)
        assert schedule.expires_at == _FUTURE
        update.assert_not_awaited()
        recorded_changes.assert_not_awaited()

    @pytest.mark.regression
    @pytest.mark.parametrize("due_date", ["2026-09-30", "2026-09-30T17:00:00"])
    async def test_a_due_date_without_an_offset_creates_nothing(self, due_date):
        """Mongo reads a naive wall time as UTC, which moves the user's local deadline."""
        with patch(
            "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo",
            new_callable=AsyncMock,
            return_value=self._response(),
        ) as create:
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", due_date=due_date
            )

        assert result == f"Error: due_date '{due_date}' must include a timezone offset."
        create.assert_not_awaited()


class TestCreateThreadTrackedTodo:
    """gmail_thread_id makes the todo the one open todo for that thread."""

    _CREATE = "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo"

    @staticmethod
    def _response() -> TodoResponse:
        now = datetime.now(UTC)
        return TodoResponse(id="t1", user_id="user-1", title="t", created_at=now, updated_at=now)

    _REFUSAL = (
        "Not created: this thread already has an open tracked todo. Update it with "
        "update_tracked_todo and its canvas.md instead of creating another.\n"
    )

    @staticmethod
    def _holder(canvas_content: str | None = None) -> TodoDocument:
        # Aware timestamps, as Mongo returns them: the age maths needs an aware now.
        created = datetime.now(UTC) - timedelta(days=3)
        return TodoDocument(
            id="held-1",
            user_id="user-1",
            title="Reply to Sam about the lease",
            labels=[GAIA_TRACKED_LABEL, "waiting-for-reply"],
            canvas_content=canvas_content,
            created_at=created,
            updated_at=created,
        )

    @classmethod
    async def _refused_for(cls, holder: TodoDocument) -> str:
        with patch(cls._CREATE, new_callable=AsyncMock, side_effect=ExternalRefTakenError(holder)):
            return await create_tracked_todo.coroutine(
                config=_config(), title="t", gmail_thread_id="abc"
            )

    async def test_the_thread_id_becomes_the_todo_ref(self):
        with patch(self._CREATE, new_callable=AsyncMock, return_value=self._response()) as create:
            await create_tracked_todo.coroutine(config=_config(), title="t", gmail_thread_id="abc")
        assert create.await_args.kwargs["external_ref"] == ExternalRef(
            source=ExternalRefSource.GMAIL_THREAD, id="abc"
        )

    async def test_every_field_reaches_the_service(self):
        with patch(self._CREATE, new_callable=AsyncMock, return_value=self._response()) as create:
            await create_tracked_todo.coroutine(
                config=_config(),
                title="Reply to Sam",
                description="about the lease",
                initial_canvas="# Lease",
                labels=["waiting-for-reply"],
                priority=Priority.HIGH,
                notify_on_run=False,
                gmail_thread_id="abc",
            )
        assert create.await_args.kwargs == {
            "user_id": "user-1",
            "title": "Reply to Sam",
            "description": "about the lease",
            "initial_canvas": "# Lease",
            "labels": ["waiting-for-reply"],
            "priority": Priority.HIGH,
            "source_conversation_id": None,
            "notify_on_run": False,
            "external_ref": ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="abc"),
            "references": None,
            "schedule": None,
        }

    async def test_no_thread_id_means_no_ref(self):
        with patch(self._CREATE, new_callable=AsyncMock, return_value=self._response()) as create:
            await create_tracked_todo.coroutine(config=_config(), title="t")
        assert create.await_args.kwargs["external_ref"] is None

    async def test_a_thread_already_tracked_returns_its_todo_to_update(self):
        holder = self._holder(
            "# Lease\n\n## Key Details\n- thread: abc\n\n"
            "## Current State\nDraft sent Monday; waiting on Sam.\n\n## Context\n"
        )
        with (
            patch(self._CREATE, new_callable=AsyncMock, side_effect=ExternalRefTakenError(holder)),
            patch(
                "app.agents.tools.tracked_todo_tools.tracked_todo_service.schedule_execution",
                new_callable=AsyncMock,
            ) as schedule,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", gmail_thread_id="abc", scheduled_at=_FUTURE_ISO
            )

        assert result.startswith(self._REFUSAL)
        assert "held-1" in result
        assert "Reply to Sam about the lease" in result
        assert "waiting-for-reply" in result
        assert "Age: 3d" in result
        assert result.endswith("\n  Current State: Draft sent Monday; waiting on Sam.")
        schedule.assert_not_awaited()

    async def test_a_holder_with_no_current_state_says_so(self):
        result = await self._refused_for(self._holder("# Lease\n\n## Key Details\n- a\n"))
        assert result.endswith("\n  Current State: (empty)")

    async def test_a_holder_caught_before_its_canvas_is_written_says_so(self):
        """A losing insert reads the winner right after its insert, before the canvas lands."""
        result = await self._refused_for(self._holder(None))
        assert result.startswith(self._REFUSAL)
        assert result.endswith("\n  Current State: (empty)")

    async def test_a_watch_that_cannot_be_set_reports_nothing_was_created(self):
        with patch(
            self._CREATE,
            new_callable=AsyncMock,
            side_effect=SubscriptionError("Could not register 'gmail_email_sent'"),
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="t", gmail_thread_id="abc"
            )

        assert "Tracked todo created" not in result
        assert "Could not register 'gmail_email_sent'" in result


class TestTrackedTodoReferences:
    """A todo that references others inherits their Standing rules, so only the user's own count."""

    _CREATE = "app.agents.tools.tracked_todo_tools.tracked_todo_service.create_tracked_todo"
    _FIND = "app.agents.tools.tracked_todo_tools.todo_repository.find_by_ids"
    _GET = "app.agents.tools.tracked_todo_tools.todo_repository.get"
    _UPDATE = "app.agents.tools.tracked_todo_tools.todo_repository.update"
    _ADD = "app.agents.tools.tracked_todo_tools.todo_repository.add_references"
    DESK = "66f838cc8829054e5f10e401"

    def _owned(
        self, *ids: str, labels: tuple[str, ...] = (GAIA_TRACKED_LABEL,)
    ) -> list[TodoDocument]:
        return [
            TodoDocument(id=i, user_id="user-1", title="Inbox desk", labels=list(labels))
            for i in ids
        ]

    @staticmethod
    def _response() -> TodoResponse:
        now = datetime.now(UTC)
        return TodoResponse(id="t1", user_id="user-1", title="t", created_at=now, updated_at=now)

    async def test_a_todo_created_with_references_is_saved_with_them(self):
        find = AsyncMock(return_value=self._owned(self.DESK))
        with (
            patch(self._FIND, find),
            patch(self._CREATE, AsyncMock(return_value=self._response())) as create,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="Reply to Sam", references=[self.DESK]
            )

        assert "Tracked todo created: t1" in result
        assert create.await_args.kwargs["references"] == [self.DESK]
        find.assert_awaited_once_with("user-1", [self.DESK])

    async def test_a_reference_that_is_not_one_of_the_users_todos_creates_nothing(self):
        with (
            patch(self._FIND, AsyncMock(return_value=[])),
            patch(self._CREATE, AsyncMock(return_value=self._response())) as create,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="Reply to Sam", references=[self.DESK, "junk"]
            )

        assert result == (
            f"Error: no other tracked todo of this user has the id {self.DESK}, junk. "
            "Nothing was saved; pass ids from list_tracked_todos or search_todo_context."
        )
        create.assert_not_awaited()

    @pytest.mark.regression
    async def test_references_alone_are_an_update(self):
        """Regression: an update carrying only references was refused as "No fields to update"."""
        with (
            patch(self._FIND, AsyncMock(return_value=self._owned(self.DESK))),
            patch(self._GET, AsyncMock(return_value=self._owned("t1")[0])),
            patch(self._UPDATE, AsyncMock()) as update,
            patch(self._ADD, AsyncMock()) as add,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", references=[self.DESK]
            )

        assert result == "Updated tracked todo t1: references"
        add.assert_awaited_once_with("t1", user_id="user-1", references=[self.DESK])
        update.assert_not_awaited()

    async def test_an_update_naming_a_todo_the_user_does_not_own_links_nothing(self):
        with (
            patch(self._FIND, AsyncMock(return_value=[])),
            patch(self._GET, AsyncMock(return_value=self._owned("t1")[0])),
            patch(self._UPDATE, AsyncMock()) as update,
            patch(self._ADD, AsyncMock()) as add,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id="t1", priority=Priority.HIGH, references=[self.DESK]
            )

        assert result.startswith(
            f"Error: no other tracked todo of this user has the id {self.DESK}."
        )
        update.assert_not_awaited()
        add.assert_not_awaited()

    async def test_a_plain_todo_of_the_user_is_not_a_reference(self):
        with (
            patch(self._FIND, AsyncMock(return_value=self._owned(self.DESK, labels=()))),
            patch(self._CREATE, AsyncMock(return_value=self._response())) as create,
        ):
            result = await create_tracked_todo.coroutine(
                config=_config(), title="Reply to Sam", references=[self.DESK]
            )

        assert result.startswith(
            f"Error: no other tracked todo of this user has the id {self.DESK}."
        )
        create.assert_not_awaited()

    async def test_a_todo_cannot_reference_itself(self):
        with (
            patch(self._FIND, AsyncMock(return_value=self._owned(self.DESK))),
            patch(self._GET, AsyncMock(return_value=self._owned(self.DESK)[0])),
            patch(self._ADD, AsyncMock()) as add,
        ):
            result = await update_tracked_todo.coroutine(
                config=_config(), todo_id=self.DESK, references=[self.DESK]
            )

        assert result.startswith(
            f"Error: no other tracked todo of this user has the id {self.DESK}."
        )
        add.assert_not_awaited()


# ---------------------------------------------------------------------------
# list_tracked_todos
# ---------------------------------------------------------------------------

_LIST_ACTIVE = "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked"


class TestListTrackedTodos:
    async def test_missing_user_id_returns_error(self):
        result = await list_tracked_todos.coroutine(config=_config(None))
        assert "user_id not found" in result

    async def test_missing_metadata_key_returns_error_not_a_crash(self):
        result = await list_tracked_todos.coroutine(config={})
        assert "user_id not found" in result

    async def test_no_active_todos_returns_friendly_message(self):
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_tracked_todos.coroutine(config=_config())
        assert result == "No active tracked todos."

    async def test_reads_the_callers_todos_up_to_the_list_limit(self):
        with patch(_LIST_ACTIVE, new_callable=AsyncMock, return_value=[]) as listed:
            await list_tracked_todos.coroutine(config=_config())
        assert listed.await_args.args == ("user-1",)
        assert listed.await_args.kwargs["limit"] == todo_constants.LIST_TRACKED_TODOS_LIMIT

    async def test_labels_filter_asks_for_todos_carrying_all_of_them(self):
        with patch(_LIST_ACTIVE, new_callable=AsyncMock, return_value=[]) as listed:
            await list_tracked_todos.coroutine(config=_config(), labels=["needs-reply", "vip"])
        assert listed.await_args.kwargs["labels"] == ["needs-reply", "vip"]
        assert listed.await_args.kwargs["external_ref"] is None

    async def test_thread_filter_asks_for_the_todo_owning_the_thread(self):
        with patch(_LIST_ACTIVE, new_callable=AsyncMock, return_value=[]) as listed:
            await list_tracked_todos.coroutine(config=_config(), gmail_thread_id="abc")
        assert listed.await_args.kwargs["external_ref"] == ExternalRef(
            source=ExternalRefSource.GMAIL_THREAD, id="abc"
        )
        assert listed.await_args.kwargs["labels"] is None

    async def test_an_empty_filtered_list_says_nothing_matched(self):
        with patch(_LIST_ACTIVE, new_callable=AsyncMock, return_value=[]):
            result = await list_tracked_todos.coroutine(config=_config(), labels=["needs-reply"])
        assert result == "No active tracked todos match those filters."

    async def test_active_todos_are_listed_with_count(self):
        docs = [
            TodoDocument(id="t1", user_id="user-1", title="First"),
            TodoDocument(id="t2", user_id="user-1", title="Second"),
        ]
        with patch(
            "app.agents.tools.tracked_todo_tools.todo_repository.list_active_tracked",
            new_callable=AsyncMock,
            return_value=docs,
        ):
            result = await list_tracked_todos.coroutine(config=_config())
        assert "Active tracked todos (2):" in result
        assert "First" in result
        assert "Second" in result
