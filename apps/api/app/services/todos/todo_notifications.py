"""Deep-link notification actions for todos.

Extracted from the maintenance-sweep worker once trigger dispatch needed the same
link: a service importing a worker task module is an import cycle waiting to
happen, and the redirect shape has to stay identical or the two surfaces drift
into two different "View todo" behaviours.
"""

from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    NotificationAction,
    RedirectConfig,
)


def todo_redirect_action(label: str, todo_id: str | None) -> NotificationAction:
    """A primary REDIRECT action to the todos page.

    Deep-links the specific todo via ``?todoId`` when one is given (single-item
    notifications), otherwise lands on the todos list (multi-item digest).
    """
    url = f"/todos?todoId={todo_id}" if todo_id else "/todos"
    return NotificationAction(
        type=ActionType.REDIRECT,
        label=label,
        style=ActionStyle.PRIMARY,
        config=ActionConfig(
            redirect=RedirectConfig(url=url, open_in_new_tab=False, close_notification=True)
        ),
    )
