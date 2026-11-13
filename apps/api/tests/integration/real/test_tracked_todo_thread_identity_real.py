"""One open tracked todo per Gmail thread, watched both ways, against real Mongo + Redis.

Composio is not reached: both Gmail triggers are account-level, so registering a
watch stores it on the todo and calls nothing upstream. The ChromaDB embeddings
and the VFS projection are the patched seams.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.constants.todos import GAIA_TRACKED_LABEL, NoReplyPlan, WaitingOn
from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.todos import todo_repository
from app.models.todo_models import (
    BulkUpdateRequest,
    ExternalRef,
    ExternalRefSource,
    TodoDocument,
    TodoModel,
    TodoResponse,
    TodoUpdate,
    TodoUpdateRequest,
    TrackedTodoCreation,
)
from app.models.trigger_subscription_models import ConditionOperator, SubscriptionAction
from app.models.workflow_models import TriggerConfig
from app.services.todo_canvas_storage import build_vfs_label
from app.services.todos.errors import ExternalRefReopenedTwiceError, ExternalRefTakenError
from app.services.todos.todo_service import TodoService
from app.services.tracked_todo_service import TrackedTodoService
from app.services.triggers.subscription_service import SubscriptionError
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError

pytestmark = pytest.mark.service

_THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f0a9b7d4e611")


@pytest.fixture(autouse=True)
def canvas_reopened() -> Iterator[AsyncMock]:
    """Patch the offline seams, yielding the search-index flag a reopen clears."""
    with (
        patch(
            "app.services.todos.todo_service.set_canvas_completed", new_callable=AsyncMock
        ) as flag,
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.update_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.update_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.set_canvas_completed", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
        patch("app.services.todos.todo_service.schedule_gaia_tasks_sync"),
    ):
        yield flag


async def _stored(mongo_db: AsyncIOMotorDatabase, user_id: str) -> list[TodoDocument]:
    raw = await mongo_db["todos"].find({"user_id": user_id}).to_list(None)
    return [TodoDocument.model_validate({**r, "id": str(r["_id"])}) for r in raw]


async def _create(user_id: str) -> TodoResponse:
    created = await TrackedTodoService.create_tracked_todo(
        user_id,
        "Reply to Sam about the lease",
        external_ref=_THREAD,
        schedule=TodoUpdate(
            waiting_on=WaitingOn.EVENT, scheduled_at=datetime.now(UTC) + timedelta(days=2)
        ),
    )
    return created.todo


async def test_concurrent_creates_for_one_thread_make_one_watched_todo(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    outcomes = await asyncio.gather(_create(user_id), _create(user_id), return_exceptions=True)

    created = [o for o in outcomes if isinstance(o, TodoResponse)]
    taken = [o for o in outcomes if isinstance(o, ExternalRefTakenError)]
    assert len(created) == 1 and len(taken) == 1, outcomes
    assert taken[0].existing.id == created[0].id

    (todo,) = await _stored(mongo_db, user_id)
    assert todo.external_ref == _THREAD
    assert sorted(s.trigger_name for s in todo.trigger_subscriptions) == sorted(
        [GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME]
    )
    for sub in todo.trigger_subscriptions:
        assert sub.action is SubscriptionAction.EXECUTE
        assert [(c.field_name, c.operator, c.value) for c in sub.conditions] == [
            ("thread_id", ConditionOperator.EQUALS, _THREAD.id)
        ]
    assert todo.activity_content is not None
    assert todo.activity_content.count("[watch_added]") == 2


async def test_a_create_for_a_thread_whose_todo_is_completed_reopens_that_todo(
    mongo_db: AsyncIOMotorDatabase, user_id: str, canvas_reopened: AsyncMock
) -> None:
    await _create(user_id)
    (first,) = await _stored(mongo_db, user_id)
    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")

    again = await TrackedTodoService.create_tracked_todo(
        user_id,
        "Sam wrote back about the lease",
        labels=["needs-reply"],
        external_ref=_THREAD,
        schedule=TodoUpdate(
            waiting_on=WaitingOn.TIME, scheduled_at=datetime.now(UTC) + timedelta(days=1)
        ),
        done_when=["Sam has the signed lease"],
    )

    (todo,) = await _stored(mongo_db, user_id)
    assert todo.id == first.id
    assert again.reopened and again.todo.id == first.id
    assert not todo.completed and todo.completed_at is None
    assert todo.title == "Sam wrote back about the lease"
    assert set(todo.labels) == {"needs-reply", GAIA_TRACKED_LABEL}
    assert todo.waiting_on is WaitingOn.TIME
    assert todo.vfs_path == build_vfs_label(todo.id)
    assert len(todo.trigger_subscriptions) == 2
    assert todo.canvas_content is not None and todo.activity_content is not None
    assert "# Reply to Sam about the lease" in todo.canvas_content
    assert "Sam has the signed lease" in todo.canvas_content
    assert todo.activity_content.index("Sam replied") < todo.activity_content.index("[reopened]")
    canvas_reopened.assert_awaited_once_with(todo.id, completed=False)


async def test_a_reopened_todo_starts_with_its_retry_and_re_ask_budgets_back(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)
    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")
    await todo_repository.update(
        first.id,
        user_id=user_id,
        update=TodoUpdate(gaia_retry_count=2, reasks_used=1, hold_checks=3),
    )

    await TrackedTodoService.create_tracked_todo(
        user_id,
        "Ask Sam about the deposit",
        external_ref=_THREAD,
        schedule=TodoUpdate(
            waiting_on=WaitingOn.USER,
            question="Should I chase Sam about the deposit?",
            if_no_reply=NoReplyPlan.ASK_AGAIN,
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
        ),
    )

    (todo,) = await _stored(mongo_db, user_id)
    assert todo.id == first.id and not todo.completed
    assert (todo.gaia_retry_count, todo.reasks_used, todo.hold_checks) == (0, 0, 0)
    assert todo.if_no_reply is NoReplyPlan.ASK_AGAIN


async def test_concurrent_creates_for_a_completed_thread_todo_reopen_it_once(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)
    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")

    async def create_again(done_when: str) -> TrackedTodoCreation:
        return await TrackedTodoService.create_tracked_todo(
            user_id,
            "Sam wrote back",
            external_ref=_THREAD,
            schedule=TodoUpdate(
                waiting_on=WaitingOn.EVENT, scheduled_at=datetime.now(UTC) + timedelta(days=2)
            ),
            done_when=[done_when],
        )

    outcomes = await asyncio.gather(
        create_again("Sam has the lease"),
        create_again("Sam paid the deposit"),
        return_exceptions=True,
    )

    reopened = [o for o in outcomes if isinstance(o, TrackedTodoCreation)]
    taken = [o for o in outcomes if isinstance(o, ExternalRefTakenError)]
    assert len(reopened) == 1 and len(taken) == 1, outcomes
    assert reopened[0].reopened and reopened[0].todo.id == first.id
    assert taken[0].existing.id == first.id
    (todo,) = await _stored(mongo_db, user_id)
    assert not todo.completed and todo.canvas_content is not None
    # Only the winning create's done-when is on the canvas: the loser wrote nothing.
    assert ("Sam has the lease" in todo.canvas_content) != (
        "Sam paid the deposit" in todo.canvas_content
    )


async def test_a_reopen_write_lands_only_on_a_todo_still_completed(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)
    reopen = TodoUpdate(completed=False, completed_at=None)

    assert await todo_repository.update_if_completed(first.id, user_id, update=reopen) is None

    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")
    written = await todo_repository.update_if_completed(first.id, user_id, update=reopen)

    assert written is not None and written.id == first.id and not written.completed
    (todo,) = await _stored(mongo_db, user_id)
    assert not todo.completed


async def test_a_create_for_a_thread_whose_todo_is_open_is_still_refused(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)

    with pytest.raises(ExternalRefTakenError) as taken:
        await _create(user_id)

    assert taken.value.existing.id == first.id
    assert len(await _stored(mongo_db, user_id)) == 1


async def test_a_reopen_whose_watch_fails_leaves_the_todo_completed_and_unwatched(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)
    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")
    register = TriggerService.register_triggers

    async def sent_mail_unavailable(
        user_id: str,
        owner_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
        raise_on_failure: bool = False,
    ) -> list[str]:
        if trigger_name == GMAIL_EMAIL_SENT_TRIGGER_NAME:
            raise TriggerRegistrationError("composio unavailable", trigger_name)
        return await register(user_id, owner_id, trigger_name, trigger_config, raise_on_failure)

    with (
        patch.object(TriggerService, "register_triggers", side_effect=sent_mail_unavailable),
        pytest.raises(SubscriptionError),
    ):
        await _create(user_id)

    (todo,) = await _stored(mongo_db, user_id)
    assert todo.completed and todo.trigger_subscriptions == []


async def test_a_watch_that_fails_leaves_no_todo_holding_the_thread(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    register = TriggerService.register_triggers

    async def sent_mail_unavailable(
        user_id: str,
        owner_id: str,
        trigger_name: str,
        trigger_config: TriggerConfig,
        raise_on_failure: bool = False,
    ) -> list[str]:
        if trigger_name == GMAIL_EMAIL_SENT_TRIGGER_NAME:
            raise TriggerRegistrationError("composio unavailable", trigger_name)
        return await register(user_id, owner_id, trigger_name, trigger_config, raise_on_failure)

    with (
        patch.object(TriggerService, "register_triggers", side_effect=sent_mail_unavailable),
        pytest.raises(SubscriptionError),
    ):
        await _create(user_id)

    assert await _stored(mongo_db, user_id) == []
    retried = await _create(user_id)
    holder = await todo_repository.find_open_by_external_ref(user_id, _THREAD)
    assert holder is not None and holder.id == retried.id


async def _completed_and_newer_thread_todos(user_id: str) -> tuple[str, str]:
    """Return a completed thread todo and an open one for the same thread inserted after it.

    A create reopens the completed todo, so the newer one is inserted the way todos were
    before reopening existed, which left threads with several todos.
    """
    done = await _create(user_id)
    await TrackedTodoService.complete_tracked_todo(done.id, user_id, summary="Sam replied")
    current = await TodoService.create_todo(
        TodoModel(title="Reply to Sam about the lease", labels=[GAIA_TRACKED_LABEL]),
        user_id,
        external_ref=_THREAD,
    )
    return done.id, current.id


async def test_reopening_a_thread_todo_whose_thread_is_taken_is_a_conflict(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    done_id, current_id = await _completed_and_newer_thread_todos(user_id)

    with pytest.raises(ExternalRefTakenError) as taken:
        await TodoService.update_todo(done_id, TodoUpdateRequest(completed=False), user_id)

    assert taken.value.status_code == 409
    assert current_id in taken.value.message
    assert "Reply to Sam about the lease" in taken.value.message
    by_id = {t.id: t for t in await _stored(mongo_db, user_id)}
    assert by_id[done_id].completed and not by_id[current_id].completed


async def test_a_bulk_reopen_with_one_taken_thread_reopens_nothing(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    done_id, current_id = await _completed_and_newer_thread_todos(user_id)
    plain = await TodoService.create_todo(TodoModel(title="Buy milk"), user_id)
    await TodoService.update_todo(plain.id, TodoUpdateRequest(completed=True), user_id)

    with pytest.raises(ExternalRefTakenError) as taken:
        await TodoService.bulk_update_todos(
            BulkUpdateRequest(
                todo_ids=[plain.id, done_id], updates=TodoUpdateRequest(completed=False)
            ),
            user_id,
        )

    assert current_id in taken.value.message
    by_id = {t.id: t for t in await _stored(mongo_db, user_id)}
    assert by_id[plain.id].completed and by_id[done_id].completed


async def test_reopening_a_thread_todo_on_a_free_thread_watches_it_both_ways_again(
    mongo_db: AsyncIOMotorDatabase, user_id: str, canvas_reopened: AsyncMock
) -> None:
    first = await _create(user_id)
    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")

    await TodoService.update_todo(first.id, TodoUpdateRequest(completed=False), user_id)

    (todo,) = await _stored(mongo_db, user_id)
    assert not todo.completed
    assert todo.vfs_path == build_vfs_label(todo.id)
    assert todo.activity_content is not None and "[reopened]" in todo.activity_content
    canvas_reopened.assert_awaited_once_with(todo.id, completed=False)
    assert sorted(s.trigger_name for s in todo.trigger_subscriptions) == sorted(
        [GMAIL_NEW_MESSAGE_TRIGGER_NAME, GMAIL_EMAIL_SENT_TRIGGER_NAME]
    )
    holder = await todo_repository.find_open_by_external_ref(user_id, _THREAD)
    assert holder is not None and holder.id == first.id


async def test_a_bulk_reopen_of_two_todos_for_one_thread_reopens_neither(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    done_id, current_id = await _completed_and_newer_thread_todos(user_id)
    await TrackedTodoService.complete_tracked_todo(current_id, user_id, summary="Sam replied again")

    with pytest.raises(ExternalRefReopenedTwiceError) as refused:
        await TodoService.bulk_update_todos(
            BulkUpdateRequest(
                todo_ids=[done_id, current_id], updates=TodoUpdateRequest(completed=False)
            ),
            user_id,
        )

    assert refused.value.status_code == 409
    stored = await _stored(mongo_db, user_id)
    assert all(t.completed and t.trigger_subscriptions == [] for t in stored)
