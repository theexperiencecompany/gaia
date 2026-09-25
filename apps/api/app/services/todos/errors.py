"""Domain errors raised by the todo services."""

from http import HTTPStatus

from app.utils.errors import AppError


class TrackedTodoWorkflowError(AppError):
    """Raised (409) when a workflow would be linked to a tracked todo."""

    def __init__(self) -> None:
        super().__init__(
            message="Tracked todos run on the agent from their canvas and never link a workflow",
            status_code=HTTPStatus.CONFLICT,
        )
