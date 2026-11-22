"""Domain errors raised by the task services."""

from http import HTTPStatus

from app.utils.errors import AppError
from app.utils.schedule import InvalidScheduleError


class TaskNotFoundError(AppError):
    """Raised (404) when the user has no task with the id."""

    def __init__(self, task_id: str) -> None:
        super().__init__(
            message=f"Task {task_id} not found",
            status_code=HTTPStatus.NOT_FOUND,
            code="task_not_found",
        )


class SubtaskNotFoundError(AppError):
    """Raised (404) when the task's checklist has no item with the id."""

    def __init__(self, task_id: str, subtask_id: str) -> None:
        super().__init__(
            message=f"Task {task_id} has no checklist item {subtask_id}",
            status_code=HTTPStatus.NOT_FOUND,
            code="subtask_not_found",
        )


class RepeatRuleError(AppError):
    """Raised (422) when a repeat rule breaks the recurring-schedule rule."""

    def __init__(self, error: InvalidScheduleError) -> None:
        super().__init__(
            message=str(error),
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="invalid_schedule",
            public={"reason": error.reason.value},
        )


class NoChatError(AppError):
    """Raised (409) when the user opens the chat of a to-do: only GAIA's tasks have one."""

    def __init__(self, task_id: str) -> None:
        super().__init__(
            message=f"Task {task_id} is a to-do; only GAIA's tasks have a chat",
            status_code=HTTPStatus.CONFLICT,
            code="task_has_no_chat",
        )


class SubtaskParentError(AppError):
    """Raised (409) when a task cannot be filed, moved or reopened under the parent it names."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=HTTPStatus.CONFLICT, code="invalid_parent")
