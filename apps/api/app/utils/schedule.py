"""The one rule every recurring schedule must pass, wherever a schedule is accepted.

Stored rows are read without it: a legacy row that breaks the rule must still
load so the user can see it, fix it, or resume it once fixed.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated

from croniter import CroniterBadDateError, CroniterError, croniter
from pydantic import AfterValidator

from app.constants.scheduling import (
    CRON_FIELD_COUNT,
    SCHEDULE_REJECTION_MESSAGES,
    SCHEDULE_REJECTION_SUGGESTION,
    ScheduleRejection,
)

INVALID_SCHEDULE_ERROR_CODE = "invalid_schedule"


class InvalidScheduleError(ValueError):
    """A recurring schedule the product refuses, with the machine-readable reason."""

    def __init__(self, reason: ScheduleRejection) -> None:
        super().__init__(SCHEDULE_REJECTION_MESSAGES[reason])
        self.reason = reason

    def as_tool_error(self) -> dict[str, str]:
        """Render this as the structured error an agent tool returns, so the agent can explain it."""
        return {
            "error": str(self),
            "error_code": INVALID_SCHEDULE_ERROR_CODE,
            "reason": self.reason.value,
            "suggestion": SCHEDULE_REJECTION_SUGGESTION,
        }


def schedule_rejection(expression: str) -> ScheduleRejection | None:
    """Return why expression is not an acceptable recurring schedule, or None when it is."""
    if len(expression.split()) != CRON_FIELD_COUNT:
        return ScheduleRejection.WRONG_FIELD_COUNT
    try:
        cron = croniter(expression)
    except CroniterError:
        return ScheduleRejection.UNPARSEABLE
    # The stub says list[str]; at runtime a field expands to ints, or ['*'] for every value,
    # a one-element list, so the int check is load-bearing.
    minutes: Sequence[int | str] = cron.expanded[0]
    if len(minutes) != 1 or not isinstance(minutes[0], int):
        return ScheduleRejection.TOO_FREQUENT
    try:
        cron.get_next(datetime)
    except CroniterBadDateError:
        return ScheduleRejection.NEVER_FIRES
    return None


def validate_recurring_schedule(expression: str) -> str:
    """Return expression unchanged, or raise InvalidScheduleError naming the broken rule."""
    rejection = schedule_rejection(expression)
    if rejection is not None:
        raise InvalidScheduleError(rejection)
    return expression


RecurringSchedule = Annotated[str, AfterValidator(validate_recurring_schedule)]
