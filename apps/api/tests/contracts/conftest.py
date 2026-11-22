"""Real-service fixtures for the repository contract suite.

The contract suite runs against real Mongo + real Redis (never mocks) — that is
what makes it a backend-agnostic certificate: the same contract classes will one
day run against a Postgres repository and green-on-both proves equivalence.

Isolation, so the default -n 4 xdist run is safe:
- Mongo: a fresh Motor client per test on a uniquely-named collection in
  gaia_test, wired into the repository accessor and dropped on teardown.
- Redis: the app's redis_cache singleton is repointed at a per-worker Redis
  DB and flushed per test.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine, Iterator
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import time
from typing import Any
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import pytest
from redis.asyncio import Redis

from app.constants.chat import (
    CONVERSATION_ARCHIVED_MESSAGES_COLLECTION,
    CONVERSATION_ENTRIES_COLLECTION,
    CONVERSATION_MIGRATION_FAILURES_COLLECTION,
)
from app.db.mongodb.indexes import CONVERSATION_ENTRY_INDEXES
from app.db.repositories import conversations as conversations_module
from app.db.repositories.conversation_log import ConversationLogRepository
from app.db.repositories.conversations import ConversationRepository
from app.models.conversation_models import ConversationDocument
from app.services.conversation.mongo_log import MongoConversationLog
from shared.py.wide_events import _spawned_tasks
from tests.helpers import worker_mongo_db_name, worker_redis_url
from tests.real_services import mark_real_services
from tests.unit.services.conversation.runtime_doubles import FakeClock
from tests.unit.services.conversation.test_conversation_log_contract import UID


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    dir_root = Path(__file__).resolve().parent
    mark_real_services(item for item in items if item.path.is_relative_to(dir_root))


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    # The URL the app itself connects with, so contracts hit the same Mongo.
    return os.environ.get("MONGO_DB", "mongodb://localhost:27017/gaia_test")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def fixture_sibling(coll: AsyncIOMotorCollection, name: str) -> AsyncIOMotorCollection:
    """Return the collection standing in for name beside the fixture collection coll."""
    return coll.database[f"{coll.name}_{name}"]


@pytest.fixture
async def raw_collection(
    mongodb_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncIOMotorCollection]:
    """Return a fresh, uniquely-named Motor collection wired into the repository accessor.

    Fresh client per test avoids event-loop cross-contamination; the unique name
    keeps parallel xdist workers from colliding. Every repository under test
    resolves its handle through the patched accessor, so it reads/writes here.
    Tests also use this handle to mutate Mongo behind a repository's back.
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        mongodb_url, tz_aware=True, tzinfo=UTC, serverSelectionTimeoutMS=5000
    )
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    # Namespaced like every other test database (worker_mongo_db_name) so a
    # lane sharing one mongod owns — and can drop — everything it creates.
    coll = client[worker_mongo_db_name()][f"contract_fixture_{worker}_{uuid.uuid4().hex}"]
    # The collections the conversation repository writes beside its own (its entry
    # log, and the entries migration's records), kept apart so heads never mix with them.
    siblings = {
        name: fixture_sibling(coll, name)
        for name in (
            CONVERSATION_ENTRIES_COLLECTION,
            CONVERSATION_MIGRATION_FAILURES_COLLECTION,
            CONVERSATION_ARCHIVED_MESSAGES_COLLECTION,
        )
    }

    # Both modules that hold the accessor: the base owns every standard path,
    # and notifications binds its own for the one bulk update_many the base
    # has no seam for. Missing either sends that repository at real Mongo.
    def accessor(name: str) -> AsyncIOMotorCollection:
        # pymongo refuses a non-str name, so a repository that lost its name fails here too.
        if not isinstance(name, str):
            raise TypeError("name must be an instance of str")
        return siblings.get(name, coll)

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", accessor)
    monkeypatch.setattr("app.db.repositories.notifications.get_async_collection", accessor)

    yield coll

    # A flush still in flight would recreate the collections after the drop.
    await asyncio.gather(*_spawned_tasks, return_exceptions=True)
    await coll.drop()
    for sibling in siblings.values():
        await sibling.drop()
    client.close()


@pytest.fixture
async def entries_collection(raw_collection: AsyncIOMotorCollection) -> AsyncIOMotorCollection:
    """Return the per-test conversation_entries collection beside raw_collection, with its real indexes."""
    entries = raw_collection.database[f"{raw_collection.name}_{CONVERSATION_ENTRIES_COLLECTION}"]
    for keys, options in CONVERSATION_ENTRY_INDEXES:
        await entries.create_index(keys, **options)
    return entries


@pytest.fixture(autouse=True)
async def redis(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    """Real Redis repointed into redis_cache and flushed per test.

    Autouse so no contract test can accidentally hit the developer's default
    Redis DB and leak cache state into the next test.
    """
    from app.db.redis import redis_cache

    client: Redis = Redis.from_url(worker_redis_url(redis_url), decode_responses=True)
    await client.ping()
    monkeypatch.setattr(redis_cache, "redis", client)

    yield client

    await client.flushdb()
    await client.aclose()


@pytest.fixture
def local_time_offset_from_utc(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Move the process's local timezone off UTC for the test.

    The suite pins TZ=UTC, which makes a naive datetime.now() numerically
    identical to an aware UTC one — so a timestamp that forgot its timezone
    would look correct here and be hours wrong in production.
    """
    monkeypatch.setenv("TZ", "Asia/Kolkata")  # UTC+5:30
    time.tzset()
    try:
        yield
    finally:
        monkeypatch.undo()
        time.tzset()


#: Runs one repository read and returns the plan summary of every operation it sent.
QueryPlans = Callable[[Awaitable[object]], Awaitable[list[str]]]


@pytest.fixture
def query_plans(raw_collection: AsyncIOMotorCollection) -> QueryPlans:
    """Return a runner that profiles one read on the fixture collection and its siblings, reporting their plans.

    The profiler is the server's own record of what ran, so a plan read here is the plan
    production gets for that exact filter and sort, not a hand-copied explain.
    """
    database = raw_collection.database
    # the siblings are named after the fixture collection, so one prefix covers them all
    namespaces = {"$regex": f"^{re.escape(f'{database.name}.{raw_collection.name}')}"}

    async def run(read: Awaitable[object]) -> list[str]:
        await database.command("profile", 2, filter={"ns": namespaces})
        try:
            await read
        finally:
            await database.command("profile", 0)
        profile = database["system.profile"].find(
            {"ns": namespaces, "planSummary": {"$exists": True}}
        )
        return [str(entry["planSummary"]) async for entry in profile]

    return run


class HeldFlushes:
    """Stands in for the flush spawner: keeps each flush coroutine until the test runs or drops it."""

    def __init__(self) -> None:
        self.held: list[Coroutine[Any, Any, Any]] = []
        self.spawned: list[tuple[str, dict[str, object]]] = []

    def __call__(self, operation: str, coro: Coroutine[Any, Any, Any], **context: object) -> None:
        self.held.append(coro)
        self.spawned.append((operation, context))

    async def run_all(self) -> None:
        held, self.held = self.held, []
        for coro in held:
            await coro

    def drop_all(self) -> None:
        held, self.held = self.held, []
        for coro in held:
            coro.close()


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> Iterator[HeldFlushes]:
    """Hold every conversation flush until the test runs or drops it."""
    flushes = HeldFlushes()
    monkeypatch.setattr(conversations_module, "spawn_logged_task", flushes)
    yield flushes
    flushes.drop_all()


async def create_conversation_head(conversation_id: str, user_id: str) -> None:
    """Create the conversations head a log writes to, with no state and no runner yet."""
    await ConversationRepository().create(
        ConversationDocument.model_validate(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "source": "web",
                "createdAt": datetime.now(UTC).isoformat(),
            }
        )
    )


@pytest.fixture
async def conversation(raw_collection: AsyncIOMotorCollection) -> str:
    """Return the id of a fresh conversation head owned by UID."""
    conversation_id = f"c-{uuid.uuid4().hex}"
    await create_conversation_head(conversation_id, UID)
    return conversation_id


@pytest.fixture
def log() -> MongoConversationLog:
    """Return the Mongo conversation log on a fake clock."""
    return MongoConversationLog(ConversationLogRepository(), FakeClock())
