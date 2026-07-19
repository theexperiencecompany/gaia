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

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
import sys
from unittest.mock import patch

from bson import ObjectId
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
import uvicorn

from tests.helpers import HeaderDrivenAuthMiddleware, pick_free_port, worker_redis_url

# ---------------------------------------------------------------------------
# Session-scoped connections (one per test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    return os.environ.get(
        "MONGODB_URL",
        "mongodb://gaia:gaia@localhost:27017/gaia_test?authSource=admin",  # pragma: allowlist secret
    )


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
async def mongo_db(mongodb_url: str):
    """
    Real MongoDB database handle for tests that need arbitrary collections.

    Creates a fresh Motor client per test to avoid event-loop cross-
    contamination. Use this when you need to work with collections other
    than 'conversations' (e.g., 'todos', 'reminders').
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
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
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
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

    Each xdist worker uses its own Redis DB so parallel tests cannot wipe
    each other's keys during ``flushdb()`` teardown.
    """
    from app.db.redis import redis_cache

    client = Redis.from_url(worker_redis_url(redis_url), decode_responses=True)
    await client.ping()

    monkeypatch.setattr(redis_cache, "redis", client)

    yield client

    await client.flushdb()
    await client.aclose()  # type: ignore[attr-defined]


@pytest.fixture
async def real_integration_collections(
    mongodb_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Rebind the integration Mongo collections to a fresh per-test Motor client.

    ``integrations_collection`` / ``user_integrations_collection`` are process-
    global Motor collections cached in ``app.db.mongodb.collections`` and pulled
    into ~a dozen modules via ``from ... import`` (early binding). Under real-
    services runs the global mongo mock is skipped, so those references stay
    bound to whichever earlier test's now-closed function-scoped event loop first
    created the client — and the device register path (insert_one, then
    get_integration_details -> resolve -> find_one, then add_user_integration)
    raises ``RuntimeError: Event loop is closed`` on the first Mongo call.

    Mirror the conversations_collection fixture, but repoint EVERY importer at
    once: a fresh client on THIS test's loop (DB "GAIA", matching ``init_mongodb``
    so it agrees with the sync client and any un-repointed reference), swapped
    into every module that early-bound either name. Targeting a hand-picked
    subset is fragile — the register path alone spans device_service,
    integration_resolver and user_integrations.

    The sweep only reaches modules already in ``sys.modules``, which is why every
    ``app.*`` import in this file is deliberately deferred into its function.
    Hoisting them to module scope imports oauth_service / endpoints.integrations
    (both early-bind ``integrations_collection``) before this fixture runs, so the
    sweep repoints them at this test's client too and the device E2E test then
    fails Mongo auth. Keep them function-local.
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
    db = client["GAIA"]
    fresh = {
        "integrations_collection": db["integrations"],
        "user_integrations_collection": db["user_integrations"],
    }

    for module in list(sys.modules.values()):
        module_dict = getattr(module, "__dict__", None)
        if not module_dict:
            continue
        for name, coll in fresh.items():
            if name in module_dict:
                monkeypatch.setattr(module, name, coll)

    yield

    client.close()


@asynccontextmanager
async def _device_bridge_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Real device-bridge listener startup, skipping the rest of unified_startup.

    A black-box device-bridge E2E test needs start_up_listener/start_revoke_listener
    running for real (that's the cross-pod Redis routing under test) but has no need
    for the full eager-service stack (LLM providers, ChromaDB, RabbitMQ, reminders)
    that unified_startup also brings up — those are unrelated to this feature and
    would only make the fixture slower and more environment-dependent.

    Shutdown disposes and resets only the postgresql_engine provider — never the
    full unified_shutdown. Each test function gets its own fresh asyncio event
    loop (asyncio_default_fixture_loop_scope = "function"), and the lazy-provider
    registry is a process-wide singleton shared with every other test file in
    the run: calling unified_shutdown here previously tore down the reminder
    scheduler, workflow scheduler, and websocket consumer out from under
    unrelated tests elsewhere in the same pytest session. postgresql_engine is
    the one provider this fixture actually forces into existence (any device
    route that touches Postgres), and it must be disposed AND reset — disposing
    alone would still hand the next test's aget() call a closed engine bound to
    this test's now-dead event loop (see ProviderRegistry.reset, "for testing
    only").
    """
    # Deferred, not hoisted — see real_integration_collections.
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
        providers.reset("postgresql_engine")


def _cors_only_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _create_live_app() -> FastAPI:
    """Build the real GAIA FastAPI app, swapping only what a test can't drive for real:
    the full startup stack (see _device_bridge_lifespan) and WorkOS SSO (see
    HeaderDrivenAuthMiddleware). Every route, dependency, and service function
    underneath is the real production code.
    """
    with (
        patch("app.core.app_factory.lifespan", _device_bridge_lifespan),
        patch("app.core.app_factory.configure_middleware", _cors_only_middleware),
    ):
        # Deferred, not hoisted — see real_integration_collections.
        from app.core.app_factory import create_app

        app = create_app()
    app.add_middleware(HeaderDrivenAuthMiddleware)
    return app


class LiveApiServer:
    """A real uvicorn server bound to a real localhost port, running the real
    GAIA app in-process (background asyncio task) so an external process — the
    real ``gaia bridge`` daemon — can dial into it over an actual WebSocket.
    """

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
    real_redis: Redis, real_integration_collections: None
) -> AsyncIterator[LiveApiServer]:
    """A live, real GAIA API bound to a real localhost port.

    Depends on real_redis so redis_cache.redis is already patched to the
    per-worker test Redis, and on real_integration_collections so the device
    path's Mongo collections are bound to this test's event loop — both before
    the app (and its listeners) start.
    """
    app = _create_live_app()
    server = LiveApiServer(pick_free_port(), app)
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
async def clean_bridge_tables(live_api_server: LiveApiServer) -> AsyncIterator[None]:
    """Truncate the device-bridge Postgres tables after each test.

    Device-bridge E2E tests assert exact device counts/lists for a given user;
    without this, rows a previous run committed for the same test-user id would
    silently accumulate across runs and corrupt those assertions. Runs in
    teardown only (before live_api_server disposes the engine, since fixture
    teardown order is the reverse of setup order).
    """
    from app.core.lazy_loader import providers

    yield

    engine = await providers.aget("postgresql_engine")
    if engine is None:
        return
    try:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE bridge_device_mcp_servers, bridge_devices CASCADE"))
    except ProgrammingError:
        # First-ever run against a fresh DB where no device-bridge test has
        # created the tables yet — nothing to clean up.
        pass


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
            "createdAt": datetime.now(UTC),
            "updatedAt": datetime.now(UTC),
            **overrides,
        }
        await conversations_collection.insert_one(doc)
        return conv_id

    return _make
