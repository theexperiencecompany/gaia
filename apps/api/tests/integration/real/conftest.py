"""
Fixtures for service integration tests with real databases.

The approach: patch the app's singletons to point at real test containers,
then call production functions directly. No rewriting production logic.

Root conftest.py globally patches _get_mongodb_instance to MagicMock. We work
around that through one seam: app.db.repositories.base.get_async_collection,
which every repository resolves on each call — patching it (see mongo_db)
points the whole repository layer at a real per-test Motor client. Redis gets a
real connection patched into redis_cache the same way.

The shared DB connection fixtures (mongodb_url, redis_url,
postgres_url, mongo_db, real_redis, hil_approvals_collection)
live in tests/integration/real/db_fixtures.py — the e2e suite's
real-infra tests (tests/e2e/test_hil_*_e2e.py) import the same fixtures.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import uvicorn

from app.constants.cache import SUBSCRIPTION_PLAN_CACHE_PREFIX, SUBSCRIPTION_PLAN_CACHE_TTL
from app.db.redis import redis_cache
from app.models.payment_models import PlanType
from tests.helpers import (
    HeaderDrivenAuthMiddleware,
    pg_advisory_lock,
    pick_free_port,
    skip_items_without_real_services,
)
from tests.integration.real.db_fixtures import (
    hil_approvals_collection,
    mongo_db,
    mongodb_url,
    postgres_url,
    real_redis,
    redis_url,
)

__all__ = [
    "hil_approvals_collection",
    "mongo_db",
    "mongodb_url",
    "postgres_url",
    "real_redis",
    "redis_url",
]


@pytest.fixture(autouse=True)
async def _autouse_hil_approvals_collection(hil_approvals_collection) -> None:
    """Every real-infra test gets a clean approvals collection.

    The chat stream reads it on *every* turn — it checks whether the user's
    message answers a pending approval before running the agent — so any test
    that streams a message touches it. The shared fixture stays opt-in in
    db_fixtures.py; this suite applies it to all tests.
    """


# ---------------------------------------------------------------------------
# Per-test isolation: clean collections + patch app singletons
# ---------------------------------------------------------------------------


@pytest.fixture
async def conversations_collection(mongo_db):
    """Return the real conversations collection production code reads, emptied around each test."""
    coll = mongo_db["conversations"]
    await coll.delete_many({})

    yield coll

    await coll.delete_many({})


@asynccontextmanager
async def _device_bridge_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run only the device-bridge listener startup, skipping the rest of unified_startup.

    Needs start_up_listener/start_revoke_listener for real (cross-pod Redis routing) without the eager stack (LLM providers, ChromaDB, RabbitMQ, reminders) unified_startup also brings up. Shutdown disposes and resets only postgresql_engine — a full unified_shutdown would tear down the process-wide scheduler/consumer singletons shared with unrelated tests, and dispose alone would leave the next test's aget() a closed engine bound to this test's dead event loop.
    """
    # Function-local so importing this conftest never drags the app's device-bridge
    # stack into every service test run — only the tests that build the live app.
    from app.core.lazy_loader import providers
    from app.core.provider_registration import register_lazy_providers
    from app.db.postgresql import close_postgresql_db
    from app.services.device.revoke_listener import start_revoke_listener, stop_revoke_listener
    from app.services.device.up_listener import start_up_listener, stop_up_listener

    register_lazy_providers("main_app")
    start_revoke_listener()
    start_up_listener()
    try:
        yield
    finally:
        await stop_up_listener()
        await stop_revoke_listener()
        await close_postgresql_db()
        # This teardown runs inside the app's own loop, where the sync reset()
        # refuses to run — it cannot take the async lock and could be undone by
        # an in-flight initialization.
        await providers.areset("postgresql_engine")


def _cors_only_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _create_live_app() -> FastAPI:
    """Build the real GAIA FastAPI app, swapping only the startup stack (see _device_bridge_lifespan) and WorkOS SSO (see HeaderDrivenAuthMiddleware); every other route, dependency, and service function is the real production code."""
    with (
        patch("app.core.app_factory.lifespan", _device_bridge_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only_middleware),
    ):
        # Function-local so importing this conftest never builds the app factory's
        # import graph for service tests that never spin up a live server.
        from app.core.app_factory import create_app

        app = create_app()
    app.add_middleware(HeaderDrivenAuthMiddleware)
    return app


class LiveApiServer:
    """A real uvicorn server bound to a real localhost port, running the GAIA app in-process so the real gaia bridge daemon can dial into it over an actual WebSocket."""

    def __init__(self, port: int, app: FastAPI) -> None:
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server.config.load()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(100):
            if self._server.started:
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("Live GAIA API server did not start in 5s")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task


@pytest.fixture
async def live_api_server(
    real_redis: Redis, mongo_db, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LiveApiServer]:
    """Start a live, real GAIA API bound to a real localhost port.

    Depends on real_redis and mongo_db so redis_cache.redis and the repository layer's Motor client are rebound to this test's event loop before the app starts — otherwise the device register path hits an earlier test's closed loop and raises RuntimeError: Event loop is closed.
    """
    from app.services.device import device_service

    # PAIRING_POLL_INTERVAL_SECONDS is normally 5s; sped up to 1s here, the wire contract itself still runs for real.
    monkeypatch.setattr(device_service, "PAIRING_POLL_INTERVAL_SECONDS", 1)
    app = _create_live_app()
    server = LiveApiServer(pick_free_port(), app)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


# Held for a whole bridge-table test: the teardown TRUNCATE is table-wide, and on
# another xdist worker it deleted a device between a test's seed and its insert.
BRIDGE_TABLES_LOCK_ID = 743_001_995


@pytest.fixture
async def clean_bridge_tables(
    live_api_server: LiveApiServer, postgres_url: str
) -> AsyncIterator[None]:
    """Run the test alone on the device-bridge tables, then truncate them.

    Without this, rows a previous run committed for the same test-user id accumulate across runs and corrupt assert-exact-count tests. Runs in teardown only, before live_api_server disposes the engine (teardown order is the reverse of setup order).
    """
    from app.core.lazy_loader import providers

    async with pg_advisory_lock(postgres_url, BRIDGE_TABLES_LOCK_ID):
        yield

        engine = await providers.aget("postgresql_engine")
        if engine is None:
            return
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text("TRUNCATE bridge_device_mcp_servers, bridge_devices CASCADE")
                )
        except ProgrammingError:
            # First-ever run against a fresh DB where no device-bridge test has
            # created the tables yet — nothing to clean up.
            pass


@pytest.fixture
def make_conversation(conversations_collection):
    """Seed a conversation document in real MongoDB.

    Writes the legacy timestamp pair as production does: createdAt an ISO string, updatedAt a BSON date. A datetime passed for createdAt is normalized to ISO here — seeding it raw would fail the repository's read-boundary validation.
    """

    async def _make(user_id: str, conv_id: str | None = None, **overrides):
        conv_id = conv_id or f"conv_{ObjectId()}"
        created_at = overrides.pop("createdAt", datetime.now(UTC))
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()
        doc = {
            "user_id": user_id,
            "conversation_id": conv_id,
            "messages": [],
            "description": "Test conversation",
            "createdAt": created_at,
            "updatedAt": datetime.now(UTC),
            **overrides,
        }
        await conversations_collection.insert_one(doc)
        return conv_id

    return _make


@pytest.fixture
async def make_pro_subscription(mongo_db, real_redis: Redis):
    """Make a user PRO for the paid-only gate, in real storage.

    Writes both halves of PRO state: the subscriptions row (what production reads) and the Redis plan-cache entry get_cached_plan_type checks first — required because the root conftest.py patches payment_service.get_user_subscription_status to a FREE stub session-wide, which is what a cache miss falls through to. Both are removed afterward so a later test can't inherit a stale PRO.
    """
    seeded: list[tuple[str, object]] = []

    async def _make(user_id: str) -> None:
        now = datetime.now(UTC)
        result = await mongo_db["subscriptions"].insert_one(
            {
                "dodo_subscription_id": f"sub_test_{ObjectId()}",
                "user_id": user_id,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
        )
        seeded.append((user_id, result.inserted_id))
        await redis_cache.set(
            f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}",
            {"plan_type": PlanType.PRO.value},
            ttl=SUBSCRIPTION_PLAN_CACHE_TTL,
        )

    yield _make

    for user_id, inserted_id in seeded:
        await mongo_db["subscriptions"].delete_one({"_id": inserted_id})
        await real_redis.delete(f"{SUBSCRIPTION_PLAN_CACHE_PREFIX}{user_id}")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Real-infra tier: skip at collection when real services are unavailable.

    A bare local run (no USE_REAL_SERVICES=1, no Docker) must skip this whole
    directory in milliseconds — never hang on dead ports or fail with
    connection errors after a slow boot. pytest calls this hook with EVERY
    collected item, so scope the skip to this conftest's own directory.
    """

    dir_root = Path(__file__).resolve().parent
    skip_items_without_real_services([item for item in items if item.path.is_relative_to(dir_root)])
