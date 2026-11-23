"""An API-call action: the request it sends names the notification, the action and what it is about."""

from datetime import UTC, datetime
import json

import httpx
import pytest
import respx

from app.constants.notifications import NotificationKind
from app.models.notification.details_models import NotificationDetails, TodoNotification
from app.models.notification.notification_models import (
    ActionConfig,
    ActionStyle,
    ActionType,
    ApiCallConfig,
    NotificationAction,
    NotificationContent,
    NotificationRecord,
    NotificationRequest,
    NotificationSourceEnum,
    NotificationType,
)
from app.utils.notification.actions import ApiCallActionHandler

ENDPOINT = "https://hooks.example/act"
USER_ID = "user-1"


def _action() -> NotificationAction:
    return NotificationAction(
        id="action-1",
        type=ActionType.API_CALL,
        label="Do it",
        style=ActionStyle.PRIMARY,
        config=ActionConfig(
            api_call=ApiCallConfig(endpoint=ENDPOINT, method="POST", payload={"extra": 1})
        ),
    )


def _record(details: NotificationDetails | None) -> NotificationRecord:
    return NotificationRecord(
        id="notif-1",
        user_id=USER_ID,
        created_at=datetime.now(UTC),
        original_request=NotificationRequest(
            id="notif-1",
            user_id=USER_ID,
            source=NotificationSourceEnum.AI_TODO_ADDED,
            type=NotificationType.INFO,
            content=NotificationContent(title="Title", body="Body"),
            details=details,
        ),
    )


async def _sent_request(details: NotificationDetails | None) -> httpx.Request:
    with respx.mock:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json={}))
        result = await ApiCallActionHandler().execute(_action(), _record(details), USER_ID, None)
    assert result.success is True
    return route.calls.last.request


@pytest.mark.unit
async def test_the_request_carries_the_notification_and_what_it_is_about() -> None:
    request = await _sent_request(TodoNotification(kind=NotificationKind.TODO, todo_id="todo-1"))

    assert request.headers["X-User-ID"] == USER_ID
    assert request.headers["X-Notification-ID"] == "notif-1"
    assert json.loads(request.content) == {
        "extra": 1,
        "user_id": USER_ID,
        "notification_id": "notif-1",
        "action_id": "action-1",
        "details": {"kind": "todo", "todo_id": "todo-1"},
    }


@pytest.mark.unit
async def test_a_notification_about_nothing_sends_no_details() -> None:
    request = await _sent_request(None)

    assert json.loads(request.content)["details"] is None
