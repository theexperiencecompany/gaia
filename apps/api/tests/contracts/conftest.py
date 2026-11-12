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
from collections.abc import AsyncIterator, Coroutine, Iterator
from datetime import UTC
import os
from typing import Any
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import pytest
from redis.asyncio import Redis

from app.constants.chat import CONVERSATION_ENTRIES_COLLECTION
from app.db.mongodb.indexes import CONVERSATION_ENTRY_INDEXES
from app.db.repositories import conversations as conversations_module
from shared.py.wide_events import _spawned_tasks
from tests.helpers import worker_mongo_db_name, worker_redis_url

_USE_REAL_SERVICES = os.environ.get("USE_REAL_SERVICES", "0") == "1"


@pytest.fixture(autouse=True)
def _require_real_services() -> None:
    if not _USE_REAL_SERVICES:
        pytest.skip(
            "repository contract tests require real Mongo + Redis. Set "
            "USE_REAL_SERVICES=1 and run both on localhost — "
            "these tests never mock the database."
        )


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    # The URL the app itself connects with, so contracts hit the same Mongo.
    return os.environ.get("MONGO_DB", "mongodb://localhost:27017/gaia_test")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


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
    # The one collection a repository writes beside its own: the conversation
    # repository's entry log, kept apart so heads and entries never mix.
    entries = coll.database[f"{coll.name}_{CONVERSATION_ENTRIES_COLLECTION}"]

    # Both modules that hold the accessor: the base owns every standard path,
    # and notifications binds its own for the one bulk update_many the base
    # has no seam for. Missing either sends that repository at real Mongo.
    def accessor(name: str) -> AsyncIOMotorCollection:
        # pymongo refuses a non-str name, so a repository that lost its name fails here too.
        if not isinstance(name, str):
            raise TypeError("name must be an instance of str")
        return entries if name == CONVERSATION_ENTRIES_COLLECTION else coll

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", accessor)
    monkeypatch.setattr("app.db.repositories.notifications.get_async_collection", accessor)

    yield coll

    # A flush still in flight would recreate the collections after the drop.
    await asyncio.gather(*_spawned_tasks, return_exceptions=True)
    await coll.drop()
    await entries.drop()
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


class HeldFlushes:
    """Stands in for the flush spawner: keeps each flush coroutine until the test runs or drops it."""

    def __init__(self) -> None:
        self.held: list[Coroutine[Any, Any, Any]] = []

    def __call__(self, operation: str, coro: Coroutine[Any, Any, Any], **_: object) -> None:
        self.held.append(coro)

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
