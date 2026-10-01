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
