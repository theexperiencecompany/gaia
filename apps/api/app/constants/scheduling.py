"""Recurring-schedule constants shared by reminders, workflows and tracked todos."""

from enum import StrEnum
from typing import Final

# minute hour day-of-month month day-of-week; croniter reads a 6th field as seconds.
CRON_FIELD_COUNT: Final[int] = 5

# Offered to the user whenever a schedule is rejected for firing too often.
HOURLY_CRON: Final[str] = "0 * * * *"


class ScheduleRejection(StrEnum):
    """Why a recurring schedule was refused; the value is the machine-readable reason code."""

    WRONG_FIELD_COUNT = "wrong_field_count"
    UNPARSEABLE = "unparseable"
    TOO_FREQUENT = "too_frequent"
    NEVER_FIRES = "never_fires"


SCHEDULE_REJECTION_MESSAGES: Final[dict[ScheduleRejection, str]] = {
    ScheduleRejection.WRONG_FIELD_COUNT: "Use 5 fields: minute hour day month weekday.",
    ScheduleRejection.UNPARSEABLE: (
        "That schedule could not be read. Use 5 fields: minute hour day month weekday."
    ),
    ScheduleRejection.TOO_FREQUENT: "Schedules can repeat at most once an hour.",
    ScheduleRejection.NEVER_FIRES: "That schedule never fires.",
}

# Told to the agent with every rejection so it can offer the user something that works.
SCHEDULE_REJECTION_SUGGESTION: Final[str] = (
    f"Tell the user in plain words, then offer an hourly schedule ('{HOURLY_CRON}') "
    "or a one-off reminder instead."
)
