"""Real-service fixtures for the repository contract suite.

The contract suite runs against real Mongo + real Redis (never mocks) — that is
what makes it a backend-agnostic certificate: the same contract classes will one
day run against a Postgres repository and green-on-both proves equivalence.

Isolation, so the default ``-n 4`` xdist run is safe:
- Mongo: a fresh Motor client per test on a uniquely-named collection in
  ``gaia_test``, wired into the repository accessor and dropped on teardown.
- Redis: the app's ``redis_cache`` singleton is repointed at a per-worker Redis
  DB and flushed per test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC
import os
import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
import pytest
from redis.asyncio import Redis

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
    """A fresh, uniquely-named Motor collection wired into the repository accessor.

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

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda _name: coll)

    yield coll

    await coll.drop()
    client.close()


@pytest.fixture(autouse=True)
async def redis(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    """Real Redis repointed into ``redis_cache`` and flushed per test.

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
