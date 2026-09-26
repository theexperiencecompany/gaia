"""The code-written entries of a tracked todo's activity.md timeline."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.constants.todos import TodoActivityEvent
from app.models.todo_models import TodoUpdate, TodoUpdateRequest
from app.services.todo_activity import activity_line, record_activity, record_field_changes

pytestmark = pytest.mark.unit

_MOD = "app.services.todo_activity"
AT = datetime(2026, 9, 26, 4, 30, tzinfo=UTC)


class TestActivityLine:
    def test_an_entry_is_a_stamped_dash_line_tagged_with_its_event(self) -> None:
        line = activity_line(TodoActivityEvent.RUN_STARTED, "scheduled run", at=AT)

        assert line == "- 2026-09-26T04:30:00+00:00 [run_started] scheduled run"

    def test_an_entry_with_no_detail_has_no_trailing_space(self) -> None:
        assert activity_line(TodoActivityEvent.CREATED, "", at=AT).endswith("[created]")


class TestRecordActivity:
    async def test_the_entry_is_appended_to_that_todos_activity(self) -> None:
        with patch(f"{_MOD}.append_activity", AsyncMock(return_value=True)) as append:
            assert await record_activity("t1", "u1", TodoActivityEvent.COMPLETED, "done") is True

        todo_id, user_id, line = append.await_args.args
        assert (todo_id, user_id) == ("t1", "u1")
        assert line.endswith(" [completed] done")

    async def test_a_failed_append_costs_the_entry_not_the_caller(self) -> None:
        with (
            patch(f"{_MOD}.append_activity", AsyncMock(side_effect=RuntimeError("mongo down"))),
            patch(f"{_MOD}.log") as log,
        ):
            assert await record_activity("t1", "u1", TodoActivityEvent.COMPLETED, "x") is False

        log.warning.assert_called_once_with(
            "tracked_todo.activity_append_failed",
            todo_id="t1",
            activity_event="completed",
            error_type="RuntimeError",
        )


class TestRecordFieldChanges:
    async def _recorded(self, update: TodoUpdate | TodoUpdateRequest) -> list[tuple[str, str]]:
        with patch(f"{_MOD}.record_activity", AsyncMock(return_value=True)) as record:
            await record_field_changes("t1", "u1", update, by="GAIA in conversation 00f7c88f")
        assert {c.args[:2] for c in record.await_args_list} <= {("t1", "u1")}
        return [(c.args[2].value, c.args[3]) for c in record.await_args_list]

    async def test_a_schedule_names_the_time_and_who_set_it(self) -> None:
        """Regression for 2026-09-26: a wrong todo was scheduled and nothing on it said so."""
        entries = await self._recorded(TodoUpdate(scheduled_at=AT))

        assert entries == [
            ("scheduled", "run at 2026-09-26T04:30:00+00:00, by GAIA in conversation 00f7c88f")
        ]

    async def test_clearing_each_field_is_recorded_as_cleared(self) -> None:
        update = TodoUpdate(scheduled_at=None, recurrence=None, expires_at=None, due_date=None)

        entries = await self._recorded(update)

        assert [detail.split(",")[0] for _, detail in entries] == [
            "no run scheduled",
            "no longer repeats",
            "no expiry",
            "no due date",
        ]
        assert [event for event, _ in entries] == [
            "schedule_cleared",
            "recurrence_changed",
            "expiry_changed",
            "due_date_changed",
        ]

    async def test_turning_delivery_off_is_recorded(self) -> None:
        entries = await self._recorded(TodoUpdateRequest(notify_on_run=False))

        assert entries == [
            ("delivery_changed", "runs never message the user, by GAIA in conversation 00f7c88f")
        ]

    async def test_fields_the_update_did_not_set_record_nothing(self) -> None:
        assert await self._recorded(TodoUpdateRequest(title="renamed", priority=None)) == []
