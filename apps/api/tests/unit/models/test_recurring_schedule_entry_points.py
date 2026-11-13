"""Every model that accepts a recurring schedule applies the same rule.

The every-minute reminder that fired ~1,440 times a day for a free user, and the
6-field '0 6 30 * * *' that croniter read as per-second, both got in because
each entry point only checked that croniter could parse the string.
"""

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
import pytest

from app.constants.todos import GAIA_TRACKED_LABEL
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


@pytest.mark.parametrize("cron", ["* * * * *", "0 6 30 * * *"])
def test_a_new_tracked_todo_holds_its_recurrence_to_the_rule(cron: str) -> None:
    with pytest.raises(ValidationError):
        TodoModel(title="Check inbox", labels=[GAIA_TRACKED_LABEL], recurrence=cron)


@pytest.mark.parametrize("shortcut", ["daily", "weekly", "every_4h", "every_1h"])
def test_tracked_todo_recurrence_shortcuts_stay_valid(shortcut: str) -> None:
    todo = TodoModel(title="Check inbox", labels=[GAIA_TRACKED_LABEL], recurrence=shortcut)
    assert todo.recurrence == shortcut


@pytest.mark.parametrize("model", [TodoModel, TodoUpdateRequest, TodoUpdate])
def test_a_plain_todos_display_rrule_is_kept_verbatim(model: type[BaseModel]) -> None:
    rrule = "FREQ=WEEKLY;BYDAY=MO"
    fields: dict[str, Any] = {"recurrence": rrule}
    if model is TodoModel:
        fields["title"] = "Water plants"
    assert model.model_validate(fields).recurrence == rrule
