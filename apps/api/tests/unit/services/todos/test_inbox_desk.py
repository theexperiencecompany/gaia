"""Provisioning the Inbox desk: one scheduled tracked todo per paying user, never one they stopped."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE, INBOX_DESK_DESCRIPTION
from app.constants.todos import INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.todos.errors import ExternalRefTakenError
from app.services.todos.inbox_desk import provision_inbox_desk, provision_inbox_desk_for_gmail_user
from app.services.tracked_todo_service import TrackedTodoService

MODULE = "app.services.todos.inbox_desk"
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
KOLKATA = ZoneInfo("Asia/Kolkata")
DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
TOMORROW_8 = datetime.now(UTC) + timedelta(hours=12)


def _desk(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {
        "id": DESK_ID,
        "user_id": USER_ID,
        "title": INBOX_DESK_TITLE,
        "external_ref": DESK_REF,
    }
    fields.update(overrides)
    return TodoDocument.model_validate(fields)


def _response() -> TodoResponse:
    now = datetime.now(UTC)
    return TodoResponse(
        id=DESK_ID, user_id=USER_ID, title=INBOX_DESK_TITLE, created_at=now, updated_at=now
    )


@pytest.fixture
def seams() -> Iterator[SimpleNamespace]:
    """Every call the provisioner makes; the repository holds whatever desk a test puts in it."""
    stored: dict[str, TodoDocument] = {}

    async def _create(*_args: object, **kwargs: object) -> TodoResponse:
        schedule = kwargs["schedule"]
        assert isinstance(schedule, TodoUpdate)
        stored[DESK_ID] = _desk(scheduled_at=schedule.scheduled_at, recurrence=schedule.recurrence)
        return _response()

    async def _update(todo_id: str, *, user_id: str, update: TodoUpdate) -> TodoDocument:
        stored[todo_id] = stored[todo_id].model_copy(update=update.model_dump(exclude_unset=True))
        return stored[todo_id]

    repo = MagicMock()
    repo.find_latest_by_external_ref = AsyncMock(return_value=None)
    repo.get = AsyncMock(side_effect=lambda todo_id, user_id: stored.get(todo_id))
    repo.update = AsyncMock(side_effect=_update)
    with (
        patch(f"{MODULE}.is_paid", AsyncMock(return_value=True)) as paid,
        patch(f"{MODULE}.todo_repository", repo),
        patch(
            "app.services.user_service.get_user_by_id",
            AsyncMock(return_value=UserDocument(timezone="Asia/Kolkata")),
        ),
        patch.object(
            TrackedTodoService, "create_tracked_todo", AsyncMock(side_effect=_create)
        ) as create,
        patch.object(
            TrackedTodoService, "schedule_execution", AsyncMock(return_value=True)
        ) as schedule,
        patch(f"{MODULE}.record_field_changes", AsyncMock()) as timeline,
        patch(f"{MODULE}.capture_event", MagicMock()) as capture,
    ):
        yield SimpleNamespace(
            paid=paid,
            repo=repo,
            stored=stored,
            create=create,
            schedule=schedule,
            timeline=timeline,
            capture=capture,
        )


async def test_a_paying_user_gets_a_desk_scheduled_with_its_insert(seams: SimpleNamespace) -> None:
    before = datetime.now(UTC)

    await provision_inbox_desk(USER_ID)

    assert seams.create.await_args.args == (USER_ID, INBOX_DESK_TITLE)
    kwargs = seams.create.await_args.kwargs
    assert kwargs["description"] == INBOX_DESK_DESCRIPTION
    assert kwargs["external_ref"] == DESK_REF
    assert kwargs["notify_on_run"] is True
    assert f"- {INBOX_DESK_DELIVERY_RULE}\n" in kwargs["initial_canvas"]
    first = kwargs["schedule"].scheduled_at
    assert kwargs["schedule"].recurrence == INBOX_DESK_RECURRENCE
    assert (first.astimezone(KOLKATA).hour, first.astimezone(KOLKATA).minute) == (8, 0)
    assert before < first <= before + timedelta(days=1)
    seams.schedule.assert_awaited_once_with(DESK_ID, first)
    seams.capture.assert_called_once_with(USER_ID, AnalyticsEvents.INBOX_DESK_PROVISIONED)


async def test_a_desk_the_user_stopped_is_never_revived(seams: SimpleNamespace) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk(completed=True)

    await provision_inbox_desk(USER_ID)

    seams.create.assert_not_awaited()
    seams.schedule.assert_not_awaited()


async def test_an_open_desk_without_a_schedule_is_rearmed_on_its_timeline(
    seams: SimpleNamespace,
) -> None:
    seams.stored[DESK_ID] = _desk()
    seams.repo.find_latest_by_external_ref.return_value = seams.stored[DESK_ID]

    await provision_inbox_desk(USER_ID)

    seams.create.assert_not_awaited()
    rearmed = seams.stored[DESK_ID]
    assert rearmed.recurrence == INBOX_DESK_RECURRENCE
    assert rearmed.scheduled_at is not None
    seams.timeline.assert_awaited_once()
    seams.schedule.assert_awaited_once_with(DESK_ID, rearmed.scheduled_at)
    seams.capture.assert_not_called()


async def test_a_scheduled_desk_only_has_its_next_run_queued_again(
    seams: SimpleNamespace,
) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk(
        scheduled_at=TOMORROW_8, recurrence=INBOX_DESK_RECURRENCE
    )

    await provision_inbox_desk(USER_ID)

    seams.create.assert_not_awaited()
    seams.repo.update.assert_not_awaited()
    seams.schedule.assert_awaited_once_with(DESK_ID, TOMORROW_8)


async def test_a_concurrent_create_uses_the_desk_that_won(seams: SimpleNamespace) -> None:
    winner = _desk(scheduled_at=TOMORROW_8, recurrence=INBOX_DESK_RECURRENCE)
    seams.create.side_effect = ExternalRefTakenError(winner)

    await provision_inbox_desk(USER_ID)

    seams.schedule.assert_awaited_once_with(DESK_ID, TOMORROW_8)
    seams.capture.assert_not_called()


async def test_a_user_without_a_plan_gets_no_desk(seams: SimpleNamespace) -> None:
    seams.paid.return_value = False

    await provision_inbox_desk(USER_ID)

    seams.paid.assert_awaited_once_with(USER_ID)
    seams.create.assert_not_awaited()


async def test_a_desk_that_cannot_be_queued_fails_loud(seams: SimpleNamespace) -> None:
    seams.schedule.side_effect = ConnectionError("redis down")

    with pytest.raises(ConnectionError):
        await provision_inbox_desk(USER_ID)


@pytest.mark.parametrize(("connected", "provisioned"), [({"gmail"}, True), (set(), False)])
async def test_a_new_plan_opens_the_desk_only_for_a_gmail_user(
    seams: SimpleNamespace, connected: set[str], provisioned: bool
) -> None:
    with patch(f"{MODULE}.get_connected_integration_ids", AsyncMock(return_value=connected)):
        await provision_inbox_desk_for_gmail_user(USER_ID)

    assert seams.create.await_count == (1 if provisioned else 0)
