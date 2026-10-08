"""Domain errors raised by the todo services."""

from http import HTTPStatus

from app.utils.errors import AppError
from app.utils.schedule import InvalidScheduleError


class TrackedTodoWorkflowError(AppError):
    """Raised (409) when a workflow would be linked to a tracked todo."""

    def __init__(self) -> None:
        super().__init__(
            message="Tracked todos run on the agent from their canvas and never link a workflow",
            status_code=HTTPStatus.CONFLICT,
        )


class TrackedLabelChangeError(AppError):
    """Raised (400) when a label edit would add or remove the tracked label: GAIA owns tracked status."""

    def __init__(self) -> None:
        super().__init__(
            message="A label change cannot add or remove the tracked label",
            status_code=HTTPStatus.BAD_REQUEST,
        )


class TrackedTodoScheduleError(AppError):
    """Raised (422) when a tracked todo's new recurrence breaks the recurring-schedule rule."""

    def __init__(self, error: InvalidScheduleError) -> None:
        super().__init__(message=str(error), status_code=HTTPStatus.UNPROCESSABLE_ENTITY)
