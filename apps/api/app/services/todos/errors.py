"""Domain errors raised by the todo services."""

from http import HTTPStatus

from app.models.todo_models import TodoDocument
from app.utils.errors import AppError


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


class ExternalRefTakenError(AppError):
    """Raised (409) when an open todo already tracks the same outside object; carries that todo."""

    def __init__(self, existing: TodoDocument) -> None:
        super().__init__(
            message=f'The open todo "{existing.title}" ({existing.id}) already tracks this',
            status_code=HTTPStatus.CONFLICT,
            code="external_ref_taken",
            public={"todo_id": existing.id},
        )
        self.existing = existing


class SubTodoParentError(AppError):
    """Raised (400) when a todo cannot go under the named parent; the message says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            message=reason,
            status_code=HTTPStatus.BAD_REQUEST,
            code="sub_todo_parent_invalid",
        )


class ExternalRefReopenedTwiceError(AppError):
    """Raised (409) when one reopen names two completed todos about the same outside object."""

    def __init__(self, todo_ids: list[str]) -> None:
        super().__init__(
            message="Two of the selected todos track the same thing; only one can be reopened",
            status_code=HTTPStatus.CONFLICT,
            code="external_ref_reopened_twice",
            public={"todo_ids": todo_ids},
        )


class CanvasShapeError(AppError):
    """Raised (400) when a new todo's canvas breaks a rule that normalizing cannot repair."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(
            message=f"initial_canvas breaks the canvas shape: {'; '.join(problems)}.",
            status_code=HTTPStatus.BAD_REQUEST,
            code="canvas_shape_invalid",
        )


class UnwatchedTodoKeptError(AppError):
    """Raised (500) when a new todo's watch failed and removing the todo failed too; carries its id."""

    def __init__(self, todo_id: str, watch_error: Exception) -> None:
        super().__init__(
            message=(
                f"Todo {todo_id} could not watch its thread ({watch_error}) and could not be "
                "removed, so it is kept without its watch."
            ),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="unwatched_todo_kept",
            public={"todo_id": todo_id},
        )
        self.todo_id = todo_id
