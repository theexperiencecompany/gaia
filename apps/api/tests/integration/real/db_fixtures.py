"""Shared real-infra fixtures for the real-database suites.

Canonical home for the connection fixtures used by tests/integration/real/ and tests/e2e/test_hil_*_e2e.py. Import them into a conftest to register for a directory; they are plain functions so each suite controls its own scope/autouse policy.

The approach: patch the app's singletons to point at real test containers,
then call production functions directly. No rewriting production logic.

Root conftest.py globally patches _get_mongodb_instance to MagicMock. We
work around that through one seam: app.db.repositories.base.get_async_collection,
which every repository resolves on each call — patching it (see mongo_db)
points the whole repository layer at a real per-test Motor client. Redis gets a
real connection patched into redis_cache the same way.
"""

from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient
import pytest
from redis.asyncio import Redis

from tests.helpers import worker_mongo_db_name, worker_redis_url

# ---------------------------------------------------------------------------
# Session-scoped connections (one per test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    # The URL the app itself connects with, so service tests hit the same Mongo
    # (mirrors tests/contracts/conftest.py). Falls back to a no-auth localhost
    # dev Mongo; CI exports MONGO_DB with its containerized credentials.
    return os.environ.get("MONGO_DB", "mongodb://localhost:27017/gaia_test")


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def postgres_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://gaia:gaia@localhost:5432/gaia_test",  # pragma: allowlist secret
    )


# ---------------------------------------------------------------------------
# Per-test isolation: clean collections + patch app singletons
# ---------------------------------------------------------------------------


@pytest.fixture
async def mongo_db(mongodb_url: str, monkeypatch):
    """Return a real MongoDB handle, with the repository layer pointed at it via get_async_collection (same seam as tests/contracts/conftest.py).

    Creates a fresh per-test Motor client, since a session-scoped client can't be reused across function-scoped async fixtures on a "function"-scoped event loop; the database is per-xdist-worker (worker_mongo_db_name) so parallel workers don't collide.
    """
    # Pin server selection to 5s (mirrors tests/contracts/conftest.py) so the
    # root conftest's 100ms MONGO_DB default — meant for the mocked unit tests —
    # cannot make a real connection here flake against a cold local Mongo.
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url, serverSelectionTimeoutMS=5000)
    db = client[worker_mongo_db_name()]

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda name: db[name])

    yield db

    client.close()


@pytest.fixture
async def hil_approvals_collection(mongo_db):
    """Real hil_approvals collection, emptied around each test.

    Not autouse here — suites that stream chat on every turn (see the
    tests/integration/real conftest) re-register it autouse so approval
    records can be asserted on exactly; suites that only read it once opt in
    explicitly (see tests/e2e/conftest.py).
    """
    coll = mongo_db["hil_approvals"]
    await coll.delete_many({})

    yield coll

    await coll.delete_many({})


@pytest.fixture
async def real_redis(redis_url: str, monkeypatch):
    """Real Redis connection, patched into the app's redis_cache singleton so StreamManager uses real Redis.

    Each xdist worker uses its own Redis DB so parallel tests don't wipe each other's keys during flushdb() teardown.
    """
    from app.db.redis import redis_cache

    client = Redis.from_url(worker_redis_url(redis_url), decode_responses=True)
    await client.ping()

    monkeypatch.setattr(redis_cache, "redis", client)

    yield client

    await client.flushdb()
    await client.aclose()
