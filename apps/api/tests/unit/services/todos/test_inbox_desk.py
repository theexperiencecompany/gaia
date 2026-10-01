"""Provisioning the Inbox desk: one tracked todo per paying user, armed for 08:00 in their timezone."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_DESCRIPTION
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument, TodoResponse
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.todos.errors import ExternalRefTakenError
from app.services.todos.inbox_desk import provision_inbox_desk
from app.services.tracked_todo_service import TrackedTodoService

MODULE = "app.services.todos.inbox_desk"
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
KOLKATA = ZoneInfo("Asia/Kolkata")
DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")


def _desk() -> TodoResponse:
    now = datetime.now(UTC)
    return TodoResponse(
        id=DESK_ID, user_id=USER_ID, title=INBOX_DESK_TITLE, created_at=now, updated_at=now
    )


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    """Every call the provisioner makes, recorded in one order list."""
    order: list[str] = []
    with (
        patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)) as paid,
        patch(
            "app.services.user_service.get_user_by_id",
            AsyncMock(return_value=UserDocument(timezone="Asia/Kolkata")),
        ),
        patch.object(
            TrackedTodoService,
            "create_tracked_todo",
            AsyncMock(side_effect=lambda *a, **k: order.append("create") or _desk()),
        ) as create,
        patch.object(
            TrackedTodoService,
            "set_creation_fields",
            AsyncMock(side_effect=lambda *a, **k: order.append("fields")),
        ) as fields,
        patch.object(
            TrackedTodoService,
            "schedule_execution",
            AsyncMock(side_effect=lambda *a, **k: order.append("schedule") or True),
        ) as schedule,
        patch(
            f"{MODULE}.capture_event", MagicMock(side_effect=lambda *a, **k: order.append("event"))
        ) as capture,
    ):
        yield SimpleNamespace(
            paid=paid,
            create=create,
            fields=fields,
            schedule=schedule,
            capture=capture,
            order=order,
        )


async def test_a_paying_user_gets_one_desk_running_the_desk_prompt(seams: SimpleNamespace) -> None:
    await provision_inbox_desk(USER_ID)

    seams.create.assert_awaited_once()
    assert seams.create.await_args.args == (USER_ID, INBOX_DESK_TITLE)
    assert seams.create.await_args.kwargs == {
        "description": INBOX_DESK_DESCRIPTION,
        "external_ref": DESK_REF,
        "notify_on_run": True,
    }


async def test_the_desk_recurs_daily_and_first_fires_at_eight_in_the_profile_timezone(
    seams: SimpleNamespace,
) -> None:
    before = datetime.now(UTC)

    await provision_inbox_desk(USER_ID)

    todo_id, user_id, update = seams.fields.await_args.args
    assert (todo_id, user_id) == (DESK_ID, USER_ID)
    assert update.recurrence == INBOX_DESK_RECURRENCE
    first = update.scheduled_at
    assert (first.astimezone(KOLKATA).hour, first.astimezone(KOLKATA).minute) == (8, 0)
    assert before < first <= before + timedelta(days=1)
    seams.schedule.assert_awaited_once_with(DESK_ID, first)


async def test_the_desk_is_counted_for_its_user_only_once_armed(seams: SimpleNamespace) -> None:
    await provision_inbox_desk(USER_ID)

    seams.capture.assert_called_once_with(USER_ID, AnalyticsEvents.INBOX_DESK_PROVISIONED)
    assert seams.order == ["create", "fields", "schedule", "event"]


async def test_a_second_connect_leaves_the_existing_desk_alone(seams: SimpleNamespace) -> None:
    existing = TodoDocument(id=DESK_ID, user_id=USER_ID, title=INBOX_DESK_TITLE)
    seams.create.side_effect = ExternalRefTakenError(existing)

    await provision_inbox_desk(USER_ID)

    seams.fields.assert_not_awaited()
    seams.schedule.assert_not_awaited()
    seams.capture.assert_not_called()


async def test_a_user_without_a_plan_gets_no_desk(seams: SimpleNamespace) -> None:
    seams.paid.return_value = False

    await provision_inbox_desk(USER_ID)

    seams.paid.assert_awaited_once_with(USER_ID)
    seams.create.assert_not_awaited()
    seams.capture.assert_not_called()


async def test_a_desk_that_cannot_be_armed_fails_loud_and_is_not_counted(
    seams: SimpleNamespace,
) -> None:
    seams.schedule.side_effect = ConnectionError("redis down")

    with pytest.raises(ConnectionError):
        await provision_inbox_desk(USER_ID)

    seams.capture.assert_not_called()
