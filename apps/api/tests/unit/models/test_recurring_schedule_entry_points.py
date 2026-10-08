"""Every model that accepts a recurring schedule applies the same rule.

The every-minute reminder that fired ~1,440 times a day for a free user, and the
6-field '0 6 30 * * *' that croniter read as per-second, both got in because
each entry point only checked that croniter could parse the string.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
import pytest

from app.models.reminder_models import (
    CreateReminderRequest,
    CreateReminderToolRequest,
    ReminderUpdate,
    StaticReminderPayload,
    UpdateReminderRequest,
)
from app.models.scheduler_models import ScheduleConfig
from app.models.todo_models import TodoModel, TodoUpdate, TodoUpdateRequest
from app.models.workflow_models import CreateWorkflowRequest, UpdateWorkflowRequest

pytestmark = pytest.mark.unit

_PAYLOAD = StaticReminderPayload(title="Stretch", body="Time to stretch")
_TOO_FREQUENT = "Schedules can repeat at most once an hour."
_FIVE_FIELDS = "Use 5 fields: minute hour day month weekday."


def _workflow_trigger(cron: str) -> dict[str, Any]:
    return {"type": "schedule", "cron_expression": cron, "timezone": "UTC"}


ENTRY_POINTS: dict[str, Callable[[str], BaseModel]] = {
    "POST /reminders": lambda cron: CreateReminderRequest(
        agent="static", repeat=cron, payload=_PAYLOAD
    ),
    "create_reminder_tool": lambda cron: CreateReminderToolRequest(repeat=cron, payload=_PAYLOAD),
    "PUT /reminders": lambda cron: UpdateReminderRequest(repeat=cron),
    "update_reminder_tool": lambda cron: ReminderUpdate(repeat=cron),
    "scheduler": lambda cron: ScheduleConfig(repeat=cron),
    "POST /workflows": lambda cron: CreateWorkflowRequest(
        title="Digest", prompt="Summarize", trigger_config=_workflow_trigger(cron)
    ),
    "PUT /workflows": lambda cron: UpdateWorkflowRequest(trigger_config=_workflow_trigger(cron)),
    "POST /todos": lambda cron: TodoModel(title="Check inbox", recurrence=cron),
    "PUT /todos": lambda cron: TodoUpdateRequest(recurrence=cron),
    "tracked todo $set": lambda cron: TodoUpdate(recurrence=cron),
}


@pytest.mark.regression
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("cron", ["* * * * *", "*/5 * * * *"])
def test_a_schedule_faster_than_hourly_is_rejected(entry_point: str, cron: str) -> None:
    with pytest.raises(ValidationError, match=_TOO_FREQUENT):
        ENTRY_POINTS[entry_point](cron)


@pytest.mark.regression
@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("cron", ["0 6 30 * * *", "* * * * * *", "0 9 * * * 0 2026"])
def test_a_schedule_without_exactly_five_fields_is_rejected(entry_point: str, cron: str) -> None:
    with pytest.raises(ValidationError, match=_FIVE_FIELDS):
        ENTRY_POINTS[entry_point](cron)


@pytest.mark.parametrize("entry_point", ENTRY_POINTS)
@pytest.mark.parametrize("cron", ["0 * * * *", "0 9 * * 1-5"])
def test_hourly_and_slower_schedules_are_accepted(entry_point: str, cron: str) -> None:
    ENTRY_POINTS[entry_point](cron)


def test_a_one_shot_reminder_a_minute_out_is_still_accepted() -> None:
    request = CreateReminderToolRequest(delay_seconds=60, payload=_PAYLOAD)

    assert request.to_create_reminder_request().repeat is None


@pytest.mark.parametrize("shortcut", ["daily", "weekly", "every_4h", "every_1h"])
def test_todo_recurrence_shortcuts_stay_valid(shortcut: str) -> None:
    assert TodoUpdateRequest(recurrence=shortcut).recurrence == shortcut
