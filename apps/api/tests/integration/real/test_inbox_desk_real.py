"""One Inbox desk per user, however many times Gmail connects, against real Mongo.

The plan and Gmail reads, analytics, ChromaDB embeddings and the VFS projection are patched
seams; the run is enqueued on a fakeredis ArqRedis so no real worker picks it up.
"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from arq.connections import ArqRedis
import fakeredis.aioredis
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.agents.prompts.todo_prompts import INBOX_DESK_DESCRIPTION
from app.constants.integrations import GMAIL_INTEGRATION_ID
from app.constants.todos import (
    GAIA_TRACKED_LABEL,
    INBOX_DESK_RECURRENCE,
    INBOX_DESK_TITLE,
    INBOX_DESK_WATCH_WINDOW_SECONDS,
)
from app.constants.trigger_gates import SystemGatePreset
from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.models.todo_models import TodoDocument
from app.models.trigger_gate_models import SystemGate
from app.services.todos.inbox_desk import INBOX_DESK_REF, provision_inbox_desk
from app.utils.redis_utils import RedisPoolManager

pytestmark = pytest.mark.service

DESK_GATE = SystemGate(preset=SystemGatePreset.INBOX_DESK)


@pytest.fixture(autouse=True)
def _offline_seams() -> Iterator[MagicMock]:
    pool = ArqRedis(pool_or_conn=fakeredis.aioredis.FakeRedis().connection_pool)
    with (
        patch("app.services.todos.inbox_desk.is_paid", AsyncMock(return_value=True)),
        patch(
            "app.services.todos.inbox_desk.get_connected_integration_ids",
            AsyncMock(return_value={GMAIL_INTEGRATION_ID}),
        ),
        patch("app.services.todos.inbox_desk.capture") as capture,
        patch("app.services.todos.todo_service.store_todo_embedding", new_callable=AsyncMock),
        patch("app.services.todos.todo_service.schedule_user_todos_sync"),
        patch("app.services.tracked_todo_service.store_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.tracked_todo_service.schedule_gaia_tasks_sync"),
        patch.object(RedisPoolManager, "get_pool", AsyncMock(return_value=pool)),
    ):
        yield capture


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
    # The desk also watches the mailbox: one hourly mail-wake subscription, not two.
    assert len(desk.trigger_subscriptions) == 1
    (watch,) = desk.trigger_subscriptions
    assert watch.trigger_name == GMAIL_NEW_MESSAGE_TRIGGER_NAME
    assert watch.cooldown_seconds == INBOX_DESK_WATCH_WINDOW_SECONDS
    assert watch.gate == DESK_GATE
    _offline_seams.assert_called_once()


async def test_a_later_reconnect_leaves_the_desk_as_it_is(
    mongo_db: AsyncIOMotorDatabase, user_id: str, _offline_seams: MagicMock
) -> None:
    await provision_inbox_desk(user_id)
    (first,) = await _desks(mongo_db, user_id)

    await provision_inbox_desk(user_id)

    (again,) = await _desks(mongo_db, user_id)
    assert again.id == first.id and again.scheduled_at == first.scheduled_at
    assert again.trigger_subscriptions == first.trigger_subscriptions
    _offline_seams.assert_called_once()


async def _set_desk_watch_gate(
    mongo_db: AsyncIOMotorDatabase, user_id: str, gate: dict[str, object] | None
) -> None:
    """Store the desk's watch as an older release left it, or as the user switched it."""
    update: dict[str, dict[str, object]] = (
        {"$unset": {"trigger_subscriptions.$[].gate": ""}}
        if gate is None
        else {"$set": {"trigger_subscriptions.$[].gate": gate}}
    )
    await mongo_db["todos"].update_one({"user_id": user_id}, update)


async def test_a_desk_armed_before_the_gate_gets_it_once_on_reconnect(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    await provision_inbox_desk(user_id)
    await _set_desk_watch_gate(mongo_db, user_id, None)
    (before,) = await _desks(mongo_db, user_id)
    assert [w.gate for w in before.trigger_subscriptions] == [None]

    await provision_inbox_desk(user_id)
    await provision_inbox_desk(user_id)

    (desk,) = await _desks(mongo_db, user_id)
    (watch,) = desk.trigger_subscriptions
    assert watch.id == before.trigger_subscriptions[0].id
    assert watch.gate == DESK_GATE


async def test_a_gate_the_user_turned_off_stays_off_on_reconnect(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    turned_off = SystemGate(preset=SystemGatePreset.INBOX_DESK, enabled=False)
    await provision_inbox_desk(user_id)
    await _set_desk_watch_gate(mongo_db, user_id, turned_off.model_dump())

    await provision_inbox_desk(user_id)

    (desk,) = await _desks(mongo_db, user_id)
    assert [w.gate for w in desk.trigger_subscriptions] == [turned_off]
