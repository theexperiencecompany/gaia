"""One Inbox desk per user, however many times Gmail connects, against real Mongo.

The plan and Gmail reads, analytics, ChromaDB embeddings and the VFS projection are patched
seams; the run is enqueued on a fakeredis ArqRedis so no real worker picks it up.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from arq.connections import ArqRedis
from bson import ObjectId
import fakeredis.aioredis
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_DESCRIPTION
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import GAIA_TRACKED_LABEL, INBOX_DESK_RECURRENCE, INBOX_DESK_TITLE
from app.db.mongodb.indexes import TODO_OPEN_EXTERNAL_REF_KEYS, TODO_OPEN_EXTERNAL_REF_OPTIONS
from app.models.todo_models import TodoDocument
from app.services.todos.inbox_desk import INBOX_DESK_REF, provision_inbox_desk
from app.utils.redis_utils import RedisPoolManager

pytestmark = pytest.mark.service


@pytest.fixture(autouse=True)
def _offline_seams() -> Iterator[MagicMock]:
    pool = ArqRedis(pool_or_conn=fakeredis.aioredis.FakeRedis().connection_pool)
    with (
        patch("app.services.todos.inbox_desk.is_paid", AsyncMock(return_value=True)),
        patch(
            "app.services.todos.inbox_desk.get_connected_integration_ids",
            AsyncMock(return_value={GMAIL_INTEGRATION_ID}),
        ),
        patch("app.services.todos.inbox_desk.capture_event") as capture,
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
        patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)),
    ):
        yield capture


@pytest.fixture
async def user_id(mongo_db: AsyncIOMotorDatabase, real_redis: object) -> AsyncIterator[str]:
    await mongo_db["todos"].create_index(
        TODO_OPEN_EXTERNAL_REF_KEYS, **TODO_OPEN_EXTERNAL_REF_OPTIONS
    )
    owner = str(ObjectId())
    yield owner
    await mongo_db["todos"].delete_many({"user_id": owner})
    await mongo_db["projects"].delete_many({"user_id": owner})


async def _desks(mongo_db: AsyncIOMotorDatabase, user_id: str) -> list[TodoDocument]:
    raw = await mongo_db["todos"].find({"user_id": user_id}).to_list(None)
    return [TodoDocument.model_validate({**r, "id": str(r["_id"])}) for r in raw]


async def test_connecting_gmail_twice_at_once_makes_one_armed_desk(
    mongo_db: AsyncIOMotorDatabase, user_id: str, _offline_seams: MagicMock
) -> None:
    before = datetime.now(UTC)

    await asyncio.gather(provision_inbox_desk(user_id), provision_inbox_desk(user_id))

    (desk,) = await _desks(mongo_db, user_id)
    assert desk.title == INBOX_DESK_TITLE
    assert desk.description == INBOX_DESK_DESCRIPTION
    assert desk.external_ref == INBOX_DESK_REF
    assert GAIA_TRACKED_LABEL in desk.labels and desk.notify_on_run
    assert desk.recurrence == INBOX_DESK_RECURRENCE
    assert desk.scheduled_at is not None
    assert before < desk.scheduled_at.replace(tzinfo=UTC) <= before + timedelta(days=1)
    assert desk.trigger_subscriptions == []
    _offline_seams.assert_called_once()


async def test_a_later_reconnect_leaves_the_desk_as_it_is(
    mongo_db: AsyncIOMotorDatabase, user_id: str, _offline_seams: MagicMock
) -> None:
    await provision_inbox_desk(user_id)
    (first,) = await _desks(mongo_db, user_id)

    await provision_inbox_desk(user_id)

    (again,) = await _desks(mongo_db, user_id)
    assert again.id == first.id and again.scheduled_at == first.scheduled_at
    _offline_seams.assert_called_once()
