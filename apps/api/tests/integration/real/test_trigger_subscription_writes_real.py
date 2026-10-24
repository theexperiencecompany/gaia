"""Concurrent writes to one todo's watches, against real Mongo and the real Redis entity cache.

Composio registration, analytics, embeddings and the VFS projection are patched seams; the todo, its cache entry and the
activity timeline are real.
"""

import asyncio
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from app.constants.triggers import GMAIL_NEW_MESSAGE_TRIGGER_NAME
from app.db.repositories.todos import todo_repository
from app.models.todo_models import TodoDocument
from app.models.trigger_subscription_models import SubscriptionAction, TriggerSubscription
from app.services.triggers.subscription_service import register_subscription
from app.services.workflow.trigger_service import TriggerService

pytestmark = pytest.mark.service

# Ample for a few local round trips; a hung interleave fails instead of stalling the suite.
RACE_TIMEOUT_SECONDS = 10


@pytest.fixture(autouse=True)
def _offline_seams() -> Iterator[None]:
    with (
        patch.object(TriggerService, "register_triggers", AsyncMock(return_value=[])),
        patch("app.services.triggers.subscription_service.capture"),
        patch("app.services.todo_canvas_storage.update_canvas_embedding", new_callable=AsyncMock),
        patch("app.services.todo_canvas_storage.schedule_gaia_tasks_sync"),
    ):
        yield


async def _watch(todo_id: str, user_id: str, cooldown_seconds: int) -> TriggerSubscription:
    subscription, _outcome, created = await register_subscription(
        todo_id=todo_id,
        user_id=user_id,
        trigger_name=GMAIL_NEW_MESSAGE_TRIGGER_NAME,
        conditions=[],
        action=SubscriptionAction.EXECUTE,
        cooldown_seconds=cooldown_seconds,
    )
    assert created
    return subscription


async def test_two_watches_added_at_once_are_both_stored_while_the_cache_lags(
    mongo_db: AsyncIOMotorDatabase, user_id: str
) -> None:
    todo = await todo_repository.create(TodoDocument(user_id=user_id, title="Busy todo"))
    other_finished = asyncio.Event()
    held: list[bool] = []
    cache_store = todo_repository._cache_store

    async def store_late_once(scope: str, doc: TodoDocument) -> None:
        # The first writer's cache refresh lands only after the other writer is done.
        if doc.trigger_subscriptions and not held:
            held.append(True)
            await other_finished.wait()
        await cache_store(scope, doc)

    def finish(_task: asyncio.Task[TriggerSubscription]) -> None:
        if held:
            other_finished.set()

    with patch.object(todo_repository, "_cache_store", store_late_once):
        tasks = [
            asyncio.create_task(_watch(todo.id, user_id, cooldown)) for cooldown in (900, 1800)
        ]
        for task in tasks:
            task.add_done_callback(finish)
        stored = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), RACE_TIMEOUT_SECONDS
        )

    assert [repr(result) for result in stored if isinstance(result, BaseException)] == []
    raw = await mongo_db["todos"].find_one({"_id": todo_repository._id_value(todo.id)})
    assert raw is not None
    assert sorted(sub["cooldown_seconds"] for sub in raw["trigger_subscriptions"]) == [900, 1800]
