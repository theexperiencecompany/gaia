"""Provisioning the Inbox desk: one scheduled tracked todo per paying user, never one they stopped."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import time_machine

from app.agents.prompts import todo_prompts
from app.agents.prompts.todo_prompts import INBOX_DESK_DELIVERY_RULE, INBOX_DESK_DESCRIPTION
from app.constants.todos import (
    CANVAS_SECTIONS,
    INBOX_DESK_RECURRENCE,
    INBOX_DESK_TITLE,
    PROVISION_INBOX_DESK_TASK,
)
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    ExternalRef,
    ExternalRefSource,
    TodoDocument,
    TodoResponse,
    TodoUpdate,
)
from app.models.user_models import UserDocument
from app.services.analytics_service import AnalyticsEvents
from app.services.canvas_markdown import canvas_problems, normalize_canvas
from app.services.todos import inbox_desk
from app.services.todos.errors import ExternalRefTakenError
from app.services.todos.inbox_desk import (
    provision_inbox_desk,
    queue_inbox_desk_provision,
)
from app.services.tracked_todo_service import TrackedTodoService, starting_canvas
from tests.helpers import captured_wide_event, local_timezone

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
        patch(f"{MODULE}.watch_external_ref", AsyncMock(return_value=[])) as watch,
    ):
        yield SimpleNamespace(
            watch=watch,
            paid=paid,
            connected=connected,
            repo=repo,
            stored=stored,
            create=create,
            schedule=schedule,
            timeline=timeline,
            capture=capture,
        )


async def test_the_desks_canvas_keeps_no_observations_of_its_own(
    seams: SimpleNamespace,
) -> None:
    """One source of truth: the desk's observations live in observations.md alone."""
    await _provision()

    canvas = seams.create.await_args.kwargs["initial_canvas"]
    assert re.findall(r"^## (.+)$", canvas, re.MULTILINE) == list(CANVAS_SECTIONS)
    assert canvas_problems(canvas) == []
    assert normalize_canvas(canvas) == (canvas, None)


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


async def test_every_provision_makes_sure_the_desk_watches_new_mail(
    seams: SimpleNamespace,
) -> None:
    """A desk opened before it had a watch gets one on its next provision, never a second."""
    desk = _desk(scheduled_at=TOMORROW_8, recurrence=INBOX_DESK_RECURRENCE)
    seams.repo.find_latest_by_external_ref.return_value = desk

    await provision_inbox_desk(USER_ID)

    seams.watch.assert_awaited_once_with(DESK_ID, USER_ID, DESK_REF, desk.trigger_subscriptions)


async def test_a_desk_the_user_stopped_gets_no_watch(seams: SimpleNamespace) -> None:
    seams.repo.find_latest_by_external_ref.return_value = _desk(completed=True)

    await provision_inbox_desk(USER_ID)

    seams.watch.assert_not_awaited()


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


STAMP = datetime(2026, 9, 1, tzinfo=UTC)
OLD_DESK_CANVAS = starting_canvas(INBOX_DESK_TITLE, [INBOX_DESK_DELIVERY_RULE])


@pytest.fixture
def stored() -> Iterator[dict[str, TodoDocument]]:
    """Stand in for the todos collection: a compare-and-set note write, updated_at kept on request."""
    docs: dict[str, TodoDocument] = {}

    async def _replace(
        todo_id: str,
        user_id: str,
        *,
        update: TodoUpdate,
        expected_updated_at: datetime | None,
        touch: bool = True,
    ) -> TodoDocument | None:
        current = docs[todo_id]
        if expected_updated_at is not None and current.updated_at != expected_updated_at:
            return None
        stamp = {"updated_at": datetime.now(UTC)} if touch else {}
        docs[todo_id] = current.model_copy(update=update.model_dump(exclude_unset=True) | stamp)
        return docs[todo_id]

    with (
        patch.object(todo_repository, "replace_note_fields", AsyncMock(side_effect=_replace)),
        patch.object(
            todo_repository,
            "get",
            AsyncMock(side_effect=lambda todo_id, user_id: docs.get(todo_id)),
        ),
        patch("app.services.todo_canvas_storage.schedule_gaia_tasks_sync", MagicMock()),
    ):
        yield docs


CANVAS_OBSERVATIONS = (
    "## Observations\n<!-- patterns the desk learned -->\n### Senders\n<!-- <sender>: <volume> -->\n"
    "- notifications@github.com: GitHub notifications, ~224/day, low priority\n"
    "### Recurring\n### People\n- Sarah Lee <sarah@example.com>: replies within the hour\n\n"
)


async def test_a_desk_without_observations_md_is_seeded_once_before_its_run(
    stored: dict[str, TodoDocument],
) -> None:
    stored[DESK_ID] = _desk(canvas_content=OLD_DESK_CANVAS, updated_at=STAMP)

    ready = await inbox_desk.with_desk_notes(stored[DESK_ID])
    again = await inbox_desk.with_desk_notes(ready)

    assert ready.observations_content == todo_prompts.INBOX_DESK_OBSERVATIONS_FILE
    assert ready.canvas_content == OLD_DESK_CANVAS
    assert again == ready == stored[DESK_ID]
    assert ready.updated_at == STAMP
    assert todo_repository.replace_note_fields.await_count == 1


@time_machine.travel(datetime(2026, 10, 3, 19, 30, tzinfo=UTC), tick=False)
async def test_the_canvas_observations_move_into_observations_md_once(
    stored: dict[str, TodoDocument],
) -> None:
    """Regression: observations lived in a capped canvas section, one line each, losing their evidence."""
    canvas = OLD_DESK_CANVAS.replace("## Key Details", CANVAS_OBSERVATIONS + "## Key Details")
    stored[DESK_ID] = _desk(canvas_content=canvas, updated_at=STAMP)

    ready = await inbox_desk.with_desk_notes(stored[DESK_ID])
    again = await inbox_desk.with_desk_notes(ready)

    seed = todo_prompts.INBOX_DESK_OBSERVATIONS_FILE
    assert ready.canvas_content == OLD_DESK_CANVAS
    assert ready.observations_content == seed.replace(
        "\n\n## Recurring",
        "\n\n### notifications@github.com\n"
        "- conclusion: GitHub notifications, ~224/day, low priority\n"
        "- confidence: low\n- first seen: before 2026-10-03\n\n## Recurring",
    ).replace(
        "engages with them -->\n",
        "engages with them -->\n\n### Sarah Lee <sarah@example.com>\n"
        "- conclusion: replies within the hour\n"
        "- confidence: low\n- first seen: before 2026-10-03\n",
    )
    assert again == ready == stored[DESK_ID]
    assert ready.updated_at == STAMP
    assert todo_repository.replace_note_fields.await_count == 1


async def test_a_desk_with_no_canvas_at_all_is_seeded_from_the_seed_alone(
    stored: dict[str, TodoDocument],
) -> None:
    """A desk written before the canvas existed gets observations.md and nothing else."""
    stored[DESK_ID] = _desk(canvas_content=None, updated_at=STAMP)

    ready = await inbox_desk.with_desk_notes(stored[DESK_ID])

    assert ready.observations_content == todo_prompts.INBOX_DESK_OBSERVATIONS_FILE
    assert ready.canvas_content is None


async def test_a_desk_that_keeps_observations_md_is_not_written(
    stored: dict[str, TodoDocument],
) -> None:
    desk = _desk(canvas_content=OLD_DESK_CANVAS, observations_content="# mine\n", updated_at=STAMP)
    stored[DESK_ID] = desk

    assert await inbox_desk.with_desk_notes(desk) is desk
    todo_repository.replace_note_fields.assert_not_awaited()


@time_machine.travel(datetime(2026, 10, 3, 19, 30, tzinfo=UTC), tick=False)
async def test_carried_lines_are_stamped_with_the_utc_day_they_moved(
    stored: dict[str, TodoDocument],
) -> None:
    """Stamp the carried patterns with the UTC day, the zone the todo's own timestamps use."""
    canvas = OLD_DESK_CANVAS.replace("## Key Details", CANVAS_OBSERVATIONS + "## Key Details")
    stored[DESK_ID] = _desk(canvas_content=canvas, updated_at=STAMP)

    with local_timezone("Asia/Kolkata"):
        ready = await inbox_desk.with_desk_notes(stored[DESK_ID])

    assert "first seen: before 2026-10-03" in ready.observations_content


async def test_a_desk_whose_notes_moved_since_it_was_read_fails_its_run(
    stored: dict[str, TodoDocument],
) -> None:
    stored[DESK_ID] = _desk(canvas_content=OLD_DESK_CANVAS, updated_at=STAMP + timedelta(days=1))

    with pytest.raises(LookupError, match="changed or vanished"):
        await inbox_desk.with_desk_notes(_desk(canvas_content=OLD_DESK_CANVAS, updated_at=STAMP))


async def test_a_repair_writes_this_desks_own_notes_under_its_own_user(
    stored: dict[str, TodoDocument],
) -> None:
    """The repair is scoped to the todo being read, not to whoever the caller's session says."""
    stored[DESK_ID] = _desk(canvas_content=OLD_DESK_CANVAS, updated_at=STAMP)

    await inbox_desk.with_desk_notes(stored[DESK_ID])

    assert todo_repository.replace_note_fields.await_args.args[:2] == (DESK_ID, USER_ID)


@pytest.mark.parametrize(
    "external_ref",
    [None, ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f0a9b7d4e611")],
    ids=["no-ref", "thread"],
)
async def test_a_todo_that_is_not_the_desk_gets_no_observations(
    stored: dict[str, TodoDocument], external_ref: ExternalRef | None
) -> None:
    canvas = OLD_DESK_CANVAS.replace("## Key Details", CANVAS_OBSERVATIONS + "## Key Details")
    todo = _desk(canvas_content=canvas, external_ref=external_ref, updated_at=STAMP)
    stored[DESK_ID] = todo

    assert await inbox_desk.with_desk_notes(todo) is todo
    todo_repository.replace_note_fields.assert_not_awaited()


@pytest.mark.parametrize(
    ("hour", "minute", "quiet"),
    [(21, 59, False), (22, 0, True), (23, 8, True), (0, 30, True), (7, 59, True), (8, 0, False)],
)
def test_quiet_hours_span_midnight(hour: int, minute: int, quiet: bool) -> None:
    assert inbox_desk.in_quiet_hours(datetime(2026, 10, 3, hour, minute, tzinfo=KOLKATA)) is quiet
