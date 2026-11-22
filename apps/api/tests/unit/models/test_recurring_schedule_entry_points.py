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
from app.models.workflow_models import CreateWorkflowRequest, UpdateWorkflowRequest

pytestmark = pytest.mark.unit

_PAYLOAD = StaticReminderPayload(title="Stretch", body="Time to stretch")
_TOO_FREQUENT = "Schedules can repeat at most once an hour."
_FIVE_FIELDS = "Use 5 fields: minute hour day month weekday."


def _workflow_trigger(cron: str) -> dict[str, Any]:
    return {"type": "schedule", "cron_expression": cron, "timezone": "UTC"}


ENTRY_POINTS: dict[str, Callable[[str], BaseModel]] = {
    "POST /reminders": lambda cron: CreateReminderRequest.model_validate(
        {"agent": "static", "repeat": cron, "payload": _PAYLOAD}
    ),
    "create_reminder_tool": lambda cron: CreateReminderToolRequest.model_validate(
        {"repeat": cron, "payload": _PAYLOAD}
    ),
    "PUT /reminders": lambda cron: UpdateReminderRequest.model_validate({"repeat": cron}),
    "update_reminder_tool": lambda cron: ReminderUpdate.model_validate({"repeat": cron}),
    "scheduler": lambda cron: ScheduleConfig.model_validate({"repeat": cron}),
    "POST /workflows": lambda cron: CreateWorkflowRequest.model_validate(
        {"title": "Digest", "prompt": "Summarize", "trigger_config": _workflow_trigger(cron)}
    ),
    "PUT /workflows": lambda cron: UpdateWorkflowRequest.model_validate(
        {"trigger_config": _workflow_trigger(cron)}
    ),
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
    request = CreateReminderToolRequest.model_validate({"delay_seconds": 60, "payload": _PAYLOAD})

    assert request.to_create_reminder_request().repeat is None
