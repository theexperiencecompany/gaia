"""
Fixtures for service integration tests with real databases.

The approach: patch the app's singletons to point at real test containers,
then call production functions directly. No rewriting production logic.

Root conftest.py globally patches _get_mongodb_instance to MagicMock.
We work around that by patching the actual collection module attributes
to point at real Motor collections, and by giving redis_cache a real
Redis connection.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from redis.asyncio import Redis


# ---------------------------------------------------------------------------
# Session-scoped connections (one per test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    return os.environ.get(
        "MONGODB_URL",
        "mongodb://gaia:gaia@localhost:27017/gaia_test?authSource=admin",
    )


@pytest.fixture(scope="session")
def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def postgres_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://gaia:gaia@localhost:5432/gaia_test",
    )


# ---------------------------------------------------------------------------
# Per-test isolation: clean collections + patch app singletons
# ---------------------------------------------------------------------------


@pytest.fixture
async def mongo_db(mongodb_url: str):
    """
    Real MongoDB database handle for tests that need arbitrary collections.

    Creates a fresh Motor client per test to avoid event-loop cross-
    contamination. Use this when you need to work with collections other
    than 'conversations' (e.g., 'todos', 'reminders').
    """
    client = AsyncIOMotorClient(mongodb_url)
    db = client["gaia_test"]
    yield db
    client.close()


@pytest.fixture
async def conversations_collection(mongodb_url: str, monkeypatch):
    """
    Real MongoDB conversations collection, patched into the app singleton.

    Creates a fresh Motor client per test to avoid event-loop cross-
    contamination (session-scoped Motor clients are bound to the session
    loop and cannot be reused by function-scoped async fixtures whose
    asyncio_default_fixture_loop_scope is "function").
    """
    client = AsyncIOMotorClient(mongodb_url)
    coll = client["gaia_test"]["conversations"]
    await coll.delete_many({})

    import app.services.conversation_service as conv_svc

    monkeypatch.setattr(conv_svc, "conversations_collection", coll)

    yield coll

    await coll.delete_many({})
    client.close()


@pytest.fixture
async def real_redis(redis_url: str, monkeypatch):
    """
    Real Redis connection, patched into the app's redis_cache singleton.

    After this fixture, StreamManager methods (publish_chunk, subscribe_stream,
    start_stream, etc.) use real Redis — no mock.
    """
    from app.db.redis import redis_cache

    client = Redis.from_url(redis_url, decode_responses=True)
    await client.ping()

    monkeypatch.setattr(redis_cache, "redis", client)

    yield client

    await client.flushdb()
    await client.aclose()


@pytest.fixture
def make_conversation(conversations_collection):
    """Factory to seed a conversation document in real MongoDB."""

    async def _make(user_id: str, conv_id: str | None = None, **overrides):
        conv_id = conv_id or f"conv_{ObjectId()}"
        doc = {
            "user_id": user_id,
            "conversation_id": conv_id,
            "messages": [],
            "description": "Test conversation",
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            **overrides,
        }
        await conversations_collection.insert_one(doc)
        return conv_id

    return _make
