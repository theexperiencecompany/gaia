"""The todos deep-link action, shared by the maintenance sweep and trigger dispatch.

Both surfaces render "View todo", so the URL shape has to stay one thing — two
copies would drift into two different behaviours behind the same label.
"""

import pytest

from app.models.notification.notification_models import ActionStyle, ActionType
from app.services.todos.todo_notifications import todo_redirect_action

pytestmark = pytest.mark.unit


class TestTodoRedirectAction:
    def test_single_todo_deep_links(self) -> None:
        action = todo_redirect_action("View todo", "todo-9")

        assert action.label == "View todo"
        # A primary REDIRECT — the model defaults style to SECONDARY, so this must
        # be set explicitly or the action renders as a non-primary button.
        assert action.type is ActionType.REDIRECT
        assert action.style is ActionStyle.PRIMARY
        assert action.config.redirect is not None
        assert action.config.redirect.url == "/todos?todoId=todo-9"
        assert action.config.redirect.close_notification is True

    def test_digest_lands_on_the_todos_list(self) -> None:
        action = todo_redirect_action("Review todos", None)

        assert action.config.redirect is not None
        assert action.config.redirect.url == "/todos"

    def test_it_never_opens_a_new_tab(self) -> None:
        # An in-app deep link that opens a tab loses the notification context.
        action = todo_redirect_action("View todo", "todo-9")

        assert action.config.redirect is not None
        assert action.config.redirect.open_in_new_tab is False
