"""Unit tests for the open-state migration: every open tracked todo ends with a next step."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest
from scripts.migrate_tracked_todo_open_states import (
    FIRST_CHECK_AFTER,
    SPREAD,
    Migration,
    apply_plan,
    build_plan,
)

from app.constants.todos import MAX_NEXT_CHECK_AHEAD, TodoActivityEvent, WaitingOn
from app.models.todo_models import TodoUpdate

MODULE = "scripts.migrate_tracked_todo_open_states"
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in self._docs:
            yield doc


def _row(**fields: object) -> dict:
    return {"_id": ObjectId(), "user_id": "u1", "title": "t", "labels": ["gaia-tracked"], **fields}


async def _plan(rows: list[dict]) -> list[Migration]:
    collection = MagicMock()
    collection.find = MagicMock(return_value=_Cursor(rows))
    with patch(f"{MODULE}.get_async_collection", return_value=collection):
        plan = await build_plan(NOW)
    return plan


class TestThePlan:
    async def test_it_looks_only_for_open_unpaused_one_time_tracked_todos_without_a_state(self):
        collection = MagicMock()
        collection.find = MagicMock(return_value=_Cursor([]))
        with patch(f"{MODULE}.get_async_collection", return_value=collection):
            await build_plan(NOW)

        assert collection.find.call_args.args[0] == {
            "labels": "gaia-tracked",
            "completed": False,
            "recurrence": {"$in": [None, ""]},
            "pause_reason": None,
            "waiting_on": None,
        }

    async def test_a_failed_todo_is_left_for_the_user(self):
        plan = await _plan([_row(labels=["gaia-tracked", "failed"]), _row()])

        assert len(plan) == 1

    async def test_a_future_check_within_the_limit_is_kept(self):
        keep = NOW + timedelta(days=5)

        (row,) = await _plan([_row(scheduled_at=keep)])

        assert (row.scheduled_at, row.kept_schedule) == (keep, True)

    @pytest.mark.parametrize(
        "scheduled_at",
        [None, NOW - timedelta(days=1), NOW + MAX_NEXT_CHECK_AHEAD + timedelta(days=1)],
    )
    async def test_no_check_a_past_one_or_a_far_one_gets_a_new_one(self, scheduled_at):
        (row,) = await _plan([_row(scheduled_at=scheduled_at)])

        assert row.kept_schedule is False
        assert NOW < row.scheduled_at <= NOW + FIRST_CHECK_AFTER + SPREAD

    async def test_the_backlog_is_spread_so_it_does_not_all_run_at_once(self):
        plan = await _plan([_row() for _ in range(6)])

        checks = [row.scheduled_at for row in plan]
        assert checks == sorted(checks)
        assert len(set(checks)) == 6
        assert checks[-1] - checks[0] < SPREAD

    async def test_a_naive_stored_time_is_read_as_utc(self):
        keep = (NOW + timedelta(days=2)).replace(tzinfo=None)

        (row,) = await _plan([_row(scheduled_at=keep)])

        assert row.scheduled_at == NOW + timedelta(days=2)


class TestApplyingThePlan:
    async def test_each_todo_becomes_unplanned_and_is_recorded(self):
        row = Migration("t1", "u1", "t", NOW + timedelta(days=1), kept_schedule=False)
        repo = MagicMock()
        repo.update = AsyncMock(return_value=MagicMock())
        service = MagicMock()
        service.schedule_execution = AsyncMock()
        record = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.tracked_todo_service", service),
            patch(f"{MODULE}.record_activity", record),
        ):
            await apply_plan([row])

        repo.update.assert_awaited_once_with(
            "t1",
            user_id="u1",
            update=TodoUpdate(waiting_on=WaitingOn.UNPLANNED, scheduled_at=row.scheduled_at),
        )
        service.schedule_execution.assert_awaited_once_with("t1", row.scheduled_at)
        assert record.await_args.args[:3] == ("t1", "u1", TodoActivityEvent.WAITING_CHANGED)

    async def test_a_kept_check_is_not_enqueued_again(self):
        """Its job is already queued; a second would only be dropped as a duplicate or run twice."""
        row = Migration("t1", "u1", "t", NOW + timedelta(days=1), kept_schedule=True)
        repo = MagicMock()
        repo.update = AsyncMock(return_value=MagicMock())
        service = MagicMock()
        service.schedule_execution = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.tracked_todo_service", service),
            patch(f"{MODULE}.record_activity", AsyncMock()),
        ):
            await apply_plan([row])

        service.schedule_execution.assert_not_awaited()

    async def test_a_todo_deleted_meanwhile_is_skipped(self):
        row = Migration("t1", "u1", "t", NOW + timedelta(days=1), kept_schedule=False)
        repo = MagicMock()
        repo.update = AsyncMock(return_value=None)
        service = MagicMock()
        service.schedule_execution = AsyncMock()
        record = AsyncMock()
        with (
            patch(f"{MODULE}.todo_repository", repo),
            patch(f"{MODULE}.tracked_todo_service", service),
            patch(f"{MODULE}.record_activity", record),
        ):
            await apply_plan([row])

        service.schedule_execution.assert_not_awaited()
        record.assert_not_awaited()
