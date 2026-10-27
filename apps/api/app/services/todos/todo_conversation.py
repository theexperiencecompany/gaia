"""A tracked todo's own chat, as the todo's "Open chat" reaches it."""

from http import HTTPStatus

from app.constants.todos import GAIA_TRACKED_LABEL
from app.db.repositories.todos import todo_repository
from app.services.analytics_service import capture
from app.services.conversation_service import get_or_create_todo_conversation
from app.services.todos.errors import UntrackedTodoChatError
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.todos import TodosChatOpened


async def open_todo_conversation(todo_id: str, user_id: str) -> str:
    """Return the id of the user's tracked todo's chat, creating it when no run has yet.

    404 for a todo the user does not own, 409 for one GAIA does not track.
    """
    todo = await todo_repository.get(todo_id, user_id=user_id)
    if todo is None:
        raise AppError(
            message="Todo not found", status_code=HTTPStatus.NOT_FOUND, code="todo_not_found"
        )
    if GAIA_TRACKED_LABEL not in todo.labels:
        raise UntrackedTodoChatError()
    conversation_id = await get_or_create_todo_conversation(user_id, todo.id, todo.title)
    capture(UserId(user_id), TodosChatOpened(todo_id=todo.id))
    return conversation_id
