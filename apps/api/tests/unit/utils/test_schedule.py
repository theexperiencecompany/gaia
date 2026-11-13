"""The recurring-schedule rule itself: field count, parse, hourly floor, next occurrence."""

from pydantic import TypeAdapter, ValidationError
import pytest

from app.constants.scheduling import ScheduleRejection
from app.utils.schedule import (
    InvalidScheduleError,
    RecurringSchedule,
    schedule_rejection,
    validate_recurring_schedule,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("expression", "reason"),
    [
        ("* * * * *", ScheduleRejection.TOO_FREQUENT),
        ("*/5 * * * *", ScheduleRejection.TOO_FREQUENT),
        ("*/30 * * * *", ScheduleRejection.TOO_FREQUENT),
        ("0,30 * * * *", ScheduleRejection.TOO_FREQUENT),
        ("0-59 * * * *", ScheduleRejection.TOO_FREQUENT),
        ("0 6 30 * * *", ScheduleRejection.WRONG_FIELD_COUNT),
        ("* * * * * *", ScheduleRejection.WRONG_FIELD_COUNT),
        ("0 9 * * * 0 2026", ScheduleRejection.WRONG_FIELD_COUNT),
        ("@hourly", ScheduleRejection.WRONG_FIELD_COUNT),
        ("", ScheduleRejection.WRONG_FIELD_COUNT),
        ("every minute please", ScheduleRejection.WRONG_FIELD_COUNT),
        ("a b c d e", ScheduleRejection.UNPARSEABLE),
        ("60 * * * *", ScheduleRejection.UNPARSEABLE),
        ("0 25 * * *", ScheduleRejection.UNPARSEABLE),
        ("0 0 31 2 *", ScheduleRejection.NEVER_FIRES),
    ],
)
def test_a_broken_schedule_is_rejected_with_its_reason(
    expression: str, reason: ScheduleRejection
) -> None:
    assert schedule_rejection(expression) is reason


@pytest.mark.parametrize(
    "expression",
    ["0 * * * *", "22 * * * *", "0 9 * * 1-5", "0 9,20 * * *", "0 */2 * * *", "0 0 29 2 *"],
)
def test_hourly_or_slower_schedules_pass(expression: str) -> None:
    assert validate_recurring_schedule(expression) == expression


def test_the_error_carries_the_user_facing_message_and_reason() -> None:
    with pytest.raises(InvalidScheduleError) as caught:
        validate_recurring_schedule("* * * * *")

    assert str(caught.value) == "Schedules can repeat at most once an hour."
    assert caught.value.as_tool_error() == {
        "error": "Schedules can repeat at most once an hour.",
        "error_code": "invalid_schedule",
        "reason": "too_frequent",
        "suggestion": (
            "Tell the user in plain words, then offer an hourly schedule ('0 * * * *') "
            "or a one-off reminder instead."
        ),
    }


def test_the_annotated_type_surfaces_the_same_message_through_pydantic() -> None:
    with pytest.raises(ValidationError, match="Use 5 fields: minute hour day month weekday."):
        TypeAdapter(RecurringSchedule).validate_python("0 6 30 * * *")
