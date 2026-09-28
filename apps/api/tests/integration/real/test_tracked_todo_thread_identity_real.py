"""One open tracked todo per Gmail thread, watched both ways, against real Mongo + Redis.

Composio is not reached: both Gmail triggers are account-level, so registering a
watch stores it on the todo and calls nothing upstream. The ChromaDB embeddings
and the VFS projection are the patched seams.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.constants.triggers import GMAIL_EMAIL_SENT_TRIGGER_NAME, GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.mongodb.indexes import TODO_OPEN_EXTERNAL_REF_KEYS, TODO_OPEN_EXTERNAL_REF_OPTIONS
from app.db.repositories.todos import todo_repository
from app.models.todo_models import ExternalRef, ExternalRefSource, TodoDocument, TodoResponse
from app.models.trigger_subscription_models import ConditionOperator, SubscriptionAction
from app.models.workflow_models import TriggerConfig
from app.services.todos.errors import ExternalRefTakenError
from app.services.tracked_todo_service import TrackedTodoService
from app.services.triggers.subscription_service import SubscriptionError
from app.services.workflow.trigger_service import TriggerService
from app.utils.exceptions import TriggerRegistrationError

pytestmark = pytest.mark.service

_THREAD = ExternalRef(source=ExternalRefSource.GMAIL_THREAD, id="18c2f0a9b7d4e611")


@pytest.fixture(autouse=True)
def _offline_seams() -> Iterator[None]:
    with (
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.delete_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.mark_canvas_completed", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
    ):
        yield


@pytest.fixture
async def user_id(mongo_db: AsyncIOMotorDatabase, real_redis: object) -> AsyncIterator[str]:
    await mongo_db["todos"].create_index(
        TODO_OPEN_EXTERNAL_REF_KEYS, **TODO_OPEN_EXTERNAL_REF_OPTIONS
    )
    owner = str(ObjectId())
    yield owner
    await mongo_db["todos"].delete_many({"user_id": owner})
    await mongo_db["projects"].delete_many({"user_id": owner})


async def _stored(mongo_db: AsyncIOMotorDatabase, user_id: str) -> list[TodoDocument]:
    raw = await mongo_db["todos"].find({"user_id": user_id}).to_list(None)
    return [TodoDocument.model_validate({**r, "id": str(r["_id"])}) for r in raw]


async def _create(user_id: str) -> TodoResponse:
    return await TrackedTodoService.create_tracked_todo(
        user_id, "Reply to Sam about the lease", external_ref=_THREAD
    )


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


async def test_a_completed_thread_todo_frees_the_thread(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    first = await _create(user_id)
    with pytest.raises(ExternalRefTakenError):
        await _create(user_id)

    await TrackedTodoService.complete_tracked_todo(first.id, user_id, summary="Sam replied")
    second = await _create(user_id)

    assert second.id != first.id
    by_id = {t.id: t for t in await _stored(mongo_db, user_id)}
    assert by_id[first.id].completed and by_id[first.id].trigger_subscriptions == []
    assert len(by_id[second.id].trigger_subscriptions) == 2


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
