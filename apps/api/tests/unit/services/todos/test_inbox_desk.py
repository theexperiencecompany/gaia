"""Provisioning the Inbox desk: one scheduled tracked todo per paying user, never one they stopped."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE, INBOX_DESK_DESCRIPTION
from app.constants.todos import (
    INBOX_DESK_RECURRENCE,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
)
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
from app.services.todos.inbox_desk import (
    provision_inbox_desk,
    queue_inbox_desk_provision,
    reconcile_inbox_desks,
)
from app.services.tracked_todo_service import TrackedTodoService, starting_canvas
from tests.helpers import captured_wide_event

MODULE = "app.services.todos.inbox_desk"
USER_ID = "507f1f77bcf86cd799439011"
DESK_ID = "66f838cc8829054e5f10e401"
KOLKATA = ZoneInfo("Asia/Kolkata")
DESK_REF = ExternalRef(source=ExternalRefSource.INBOX_DESK, id="gmail")
TOMORROW_8 = datetime.now(UTC) + timedelta(hours=12)
PROVISIONED_BY = "GAIA, setting up the Inbox desk"


def _desk(**overrides: object) -> TodoDocument:
    fields: dict[str, object] = {
        "id": DESK_ID,
        "user_id": USER_ID,
        "title": INBOX_DESK_TITLE,
        "external_ref": DESK_REF,
    }
    fields.update(overrides)
    return TodoDocument.model_validate(fields)


def _at_8_in_kolkata(moment: datetime) -> bool:
    local = moment.astimezone(KOLKATA)
    return (local.hour, local.minute) == (8, 0)


async def _provision() -> dict[str, object]:
    """Provision the desk inside a real wide-event boundary; return its inbox_desk namespace."""
    async with captured_wide_event() as event:
        await provision_inbox_desk(USER_ID)
    return event["inbox_desk"]


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
        patch(
            f"{MODULE}.get_connected_integration_ids", AsyncMock(return_value={"gmail"})
        ) as connected,
        patch(f"{MODULE}.todo_repository", repo),
        # Only the provisioned user lives in Kolkata; any other lookup falls back to UTC.
        patch(
            "app.services.user_service.get_user_by_id",
            AsyncMock(
                side_effect=lambda user_id: (
                    UserDocument(timezone="Asia/Kolkata") if user_id == USER_ID else None
                )
            ),
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
            connected=connected,
            repo=repo,
            stored=stored,
            create=create,
            schedule=schedule,
            timeline=timeline,
            capture=capture,
        )


async def test_a_paying_user_gets_a_desk_scheduled_with_its_insert(seams: SimpleNamespace) -> None:
    before = datetime.now(UTC)

    event = await _provision()

    seams.repo.find_latest_by_external_ref.assert_awaited_once_with(USER_ID, DESK_REF)
    assert seams.create.await_args.args == (USER_ID, INBOX_DESK_TITLE)
    kwargs = seams.create.await_args.kwargs
    assert kwargs["description"] == INBOX_DESK_DESCRIPTION
    assert kwargs["external_ref"] == DESK_REF
    assert kwargs["notify_on_run"] is True
    assert kwargs["initial_canvas"] == starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE])
    first = kwargs["schedule"].scheduled_at
    assert kwargs["schedule"].recurrence == INBOX_DESK_RECURRENCE
    assert _at_8_in_kolkata(first)
    assert before < first <= before + timedelta(days=1)
    seams.repo.get.assert_awaited_once_with(DESK_ID, user_id=USER_ID)
    seams.schedule.assert_awaited_once_with(DESK_ID, first)
    seams.capture.assert_called_once_with(USER_ID, AnalyticsEvents.INBOX_DESK_PROVISIONED)
    assert event == {
        "operation": "provision",
        "user_id": USER_ID,
        "outcome": "armed",
        "todo_id": DESK_ID,
        "next_run": first.isoformat(),
    }


async def test_a_desk_the_user_stopped_is_never_revived(seams: SimpleNamespace) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk(completed=True)

    event = await _provision()

    seams.create.assert_not_awaited()
    seams.schedule.assert_not_awaited()
    assert event == {
        "operation": "provision",
        "user_id": USER_ID,
        "outcome": "stopped_by_user",
        "todo_id": DESK_ID,
    }


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
    assert _at_8_in_kolkata(rearmed.scheduled_at)
    schedule = TodoUpdate(recurrence=INBOX_DESK_RECURRENCE, scheduled_at=rearmed.scheduled_at)
    seams.repo.update.assert_awaited_once_with(DESK_ID, user_id=USER_ID, update=schedule)
    seams.timeline.assert_awaited_once_with(DESK_ID, USER_ID, schedule, by=PROVISIONED_BY)
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

    event = await _provision()

    seams.paid.assert_awaited_once_with(USER_ID)
    seams.create.assert_not_awaited()
    assert event == {"operation": "provision", "user_id": USER_ID, "outcome": "skipped_unpaid"}


async def test_a_desk_that_cannot_be_queued_fails_loud(seams: SimpleNamespace) -> None:
    seams.schedule.side_effect = ConnectionError("redis down")

    with pytest.raises(ConnectionError):
        await provision_inbox_desk(USER_ID)


async def test_a_user_without_gmail_gets_no_desk(seams: SimpleNamespace) -> None:
    seams.connected.return_value = set()

    event = await _provision()

    seams.connected.assert_awaited_once_with(USER_ID)
    seams.create.assert_not_awaited()
    seams.schedule.assert_not_awaited()
    assert event == {"operation": "provision", "user_id": USER_ID, "outcome": "skipped_no_gmail"}


async def test_a_desk_gone_right_after_its_insert_fails_loud(seams: SimpleNamespace) -> None:
    seams.repo.get.side_effect = None
    seams.repo.get.return_value = None

    with pytest.raises(LookupError) as caught:
        await provision_inbox_desk(USER_ID)

    assert str(caught.value) == f"Inbox desk {DESK_ID} vanished right after it was created"
    seams.schedule.assert_not_awaited()


async def test_a_desk_gone_while_it_is_rearmed_fails_loud(seams: SimpleNamespace) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk()
    seams.repo.update.side_effect = None
    seams.repo.update.return_value = None

    with pytest.raises(LookupError) as caught:
        await provision_inbox_desk(USER_ID)

    assert str(caught.value) == f"Inbox desk {DESK_ID} vanished while it was being re-armed"
    seams.timeline.assert_not_awaited()
    seams.schedule.assert_not_awaited()


async def test_a_rearm_that_did_not_store_the_schedule_fails_loud(seams: SimpleNamespace) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk()
    seams.repo.update.side_effect = None
    seams.repo.update.return_value = _desk()

    with pytest.raises(LookupError) as caught:
        await provision_inbox_desk(USER_ID)

    assert str(caught.value) == f"Inbox desk {DESK_ID} has no next run after it was armed"
    seams.schedule.assert_not_awaited()


async def test_queueing_hands_the_user_to_the_provisioning_job() -> None:
    pool = MagicMock()
    with (
        patch(f"{MODULE}.RedisPoolManager.get_pool", AsyncMock(return_value=pool)),
        patch(f"{MODULE}.enqueue_worker_job", AsyncMock()) as enqueue,
    ):
        await queue_inbox_desk_provision(USER_ID)

    enqueue.assert_awaited_once_with(pool, PROVISION_INBOX_DESK_TASK, USER_ID)


async def test_the_daily_reconcile_provisions_each_paying_gmail_user_past_a_failure() -> None:
    gmail = AsyncMock(return_value=["u2", "u3", "u9"])
    paying = AsyncMock(return_value=["u1", "u2", "u3"])
    provision = AsyncMock(side_effect=[ConnectionError("mongo down"), None])
    with (
        patch(f"{MODULE}.user_integration_repository.user_ids_with_integration", gmail),
        patch(f"{MODULE}.subscription_repository.active_user_ids", paying),
        patch(f"{MODULE}.provision_inbox_desk", provision),
    ):
        result = await reconcile_inbox_desks()

    gmail.assert_awaited_once_with("gmail")
    assert [c.args[0] for c in provision.await_args_list] == ["u2", "u3"]
    assert (result.users, result.failures) == (2, 1)
