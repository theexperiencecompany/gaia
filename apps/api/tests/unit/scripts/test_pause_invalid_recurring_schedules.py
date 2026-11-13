"""The invalid-schedule cleanup pauses exactly the rows that break the rule, and only with --apply."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
import pytest
from scripts.pause_invalid_recurring_schedules import (
    CleanupPlan,
    apply_plan,
    plan_reminder,
    plan_todo,
    plan_workflow,
)

MODULE = "scripts.pause_invalid_recurring_schedules"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
LEGACY_CREATED = datetime(2025, 8, 3, tzinfo=UTC)

pytestmark = pytest.mark.unit


def _reminder(repeat: str, **over: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "_id": ObjectId(),
        "user_id": "u1",
        "repeat": repeat,
        "status": "scheduled",
        "stop_after": NOW + timedelta(days=30),
        "created_at": LEGACY_CREATED,
    }
    doc.update(over)
    return doc


@pytest.mark.parametrize(
    ("repeat", "reason"), [("* * * * *", "too_frequent"), ("0 6 30 * * *", "wrong_field_count")]
)
def test_the_known_prod_offenders_are_paused(repeat: str, reason: str) -> None:
    plan = CleanupPlan()
    plan_reminder(_reminder(repeat), NOW, plan)

    assert [(r.expression, r.reason) for r in plan.reminders_to_pause] == [(repeat, reason)]


@pytest.mark.parametrize("repeat", ["0 * * * *", "22 * * * *", "0 9 * * *"])
def test_hourly_and_slower_reminders_are_left_running(repeat: str) -> None:
    plan = CleanupPlan()
    plan_reminder(_reminder(repeat), NOW, plan)

    assert plan.reminders_to_pause == []


def test_a_reminder_already_paused_for_its_schedule_is_skipped_on_a_rerun() -> None:
    plan = CleanupPlan()
    plan_reminder(
        _reminder("* * * * *", status="paused", pause_reason="invalid_schedule"), NOW, plan
    )

    assert plan.reminders_to_pause == []


def test_a_legacy_reminder_past_its_lifetime_gets_a_fresh_one() -> None:
    plan = CleanupPlan()
    doc = _reminder("0 9 * * *", stop_after=None)
    plan_reminder(doc, NOW, plan)

    assert plan.stop_after_backfill == {str(doc["_id"]): NOW + timedelta(days=180)}


def test_a_recent_reminder_ends_180_days_after_creation() -> None:
    plan = CleanupPlan()
    created = NOW - timedelta(days=10)
    doc = _reminder("0 9 * * *", stop_after=None, created_at=created)
    plan_reminder(doc, NOW, plan)

    assert plan.stop_after_backfill == {str(doc["_id"]): created + timedelta(days=180)}


def test_an_invalid_workflow_cron_is_paused_once() -> None:
    plan = CleanupPlan()
    doc = {"_id": "wf_1", "user_id": "u1", "trigger_config": {"cron_expression": "*/15 * * * *"}}
    plan_workflow(doc, plan)
    plan_workflow({**doc, "deactivated_reason": "invalid_schedule"}, plan)

    assert [w.id for w in plan.workflows_to_pause] == ["wf_1"]


def test_todo_shortcuts_are_never_reported() -> None:
    plan = CleanupPlan()
    plan_todo({"_id": "t1", "user_id": "u1", "recurrence": "every_1h"}, plan)
    plan_todo({"_id": "t2", "user_id": "u1", "recurrence": "*/10 * * * *"}, plan)

    assert [t.id for t in plan.invalid_todos] == ["t2"]


async def test_apply_pauses_through_the_repositories_with_the_invalid_schedule_reason() -> None:
    plan = CleanupPlan()
    plan_reminder(_reminder("* * * * *"), NOW, plan)
    plan_workflow(
        {"_id": "wf_1", "user_id": "u1", "trigger_config": {"cron_expression": "* * * * *"}}, plan
    )
    reminders, workflows = MagicMock(), MagicMock()
    reminders.set_status = AsyncMock(return_value=True)
    workflows.deactivate = AsyncMock()
    with (
        patch(f"{MODULE}.reminder_repository", reminders),
        patch(f"{MODULE}.workflow_repository", workflows),
        patch(f"{MODULE}.get_async_collection", MagicMock()),
    ):
        await apply_plan(plan)

    assert reminders.set_status.await_args.kwargs["pause_reason"] == "invalid_schedule"
    workflows.deactivate.assert_awaited_once_with("wf_1", "u1", reason="invalid_schedule")
