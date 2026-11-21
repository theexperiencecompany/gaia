"""Fixtures for the task journeys: one signed-in user on real Mongo and Redis, and their driver."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from bson import ObjectId
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorDatabase
import pytest

from tests.conftest import FAKE_USER
from tests.e2e._harness.tasks_driver import TasksDriver
from tests.helpers import skip_items_without_real_services

OWNED_COLLECTIONS = (
    "todos",
    "projects",
    "workflows",
    "workflow_executions",
    "playbooks",
    "conversations",
    "notifications",
    "approval_ledger",
    "waits",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip every journey at collection without real Mongo and Redis."""
    here = Path(__file__).resolve().parent
    skip_items_without_real_services(
        [item for item in items if item.path.is_relative_to(here)],
        reason="journeys need USE_REAL_SERVICES=1 (real Mongo/Redis)",
    )


@pytest.fixture
async def tasks(
    mongo_db: AsyncIOMotorDatabase, real_redis: object, client: AsyncClient
) -> AsyncIterator[TasksDriver]:
    """Yield the signed-in user's driver, with nothing of theirs left from an earlier run."""
    user_id = FAKE_USER.user_id
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})
    await mongo_db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"email": FAKE_USER.email, "name": FAKE_USER.name, "timezone": "UTC"}},
        upsert=True,
    )
    yield TasksDriver(client)
    for collection in OWNED_COLLECTIONS:
        await mongo_db[collection].delete_many({"user_id": user_id})
