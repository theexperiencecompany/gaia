"""
Fixtures for service integration tests with real databases.

The approach: patch the app's singletons to point at real test containers,
then call production functions directly. No rewriting production logic.

Mongo goes through one seam: ``app.db.repositories.base.get_async_collection``,
which every repository resolves on each call. Patching it points the whole
repository layer at a real per-test Motor client. Redis gets a real connection
patched into redis_cache the same way.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
import os
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

from tests.helpers import (
    HeaderDrivenAuthMiddleware,
    pick_free_port,
    worker_mongo_db_name,
    worker_redis_url,
)

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
    db = client[worker_mongo_db_name()]
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
    coll = client[worker_mongo_db_name()]["conversations"]
    await coll.delete_many({})

    import app.services.conversation_service as conv_svc

    monkeypatch.setattr(conv_svc, "conversations_collection", coll)

    yield coll

    await coll.delete_many({})
    client.close()


@pytest.fixture(autouse=True)
async def hil_approvals_collection(mongodb_url: str, monkeypatch):
    """Real MongoDB hil_approvals collection, patched into the app singleton.

    Autouse because the chat stream reads it on *every* turn — it checks whether the
    user's message answers a pending approval before running the agent. Any service test
    that streams a message touches it, so without the rebind it stays bound to the
    session loop and raises "Event loop is closed" (see ``conversations_collection``).
    """
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongodb_url)
    coll = client[worker_mongo_db_name()]["hil_approvals"]
    await coll.delete_many({})

    from app.services.hil import approvals_store

    monkeypatch.setattr(approvals_store, "hil_approvals_collection", coll)

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
async def real_mongo_repositories(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Bind the repository layer to a fresh Motor client on THIS test's loop.

    ``app.db.mongodb.collections`` caches one process-global Motor client, and a
    Motor client pins itself to the event loop that runs its first operation and
    caches that loop forever (``motor.core``'s ``io_loop``). Under real-services
    runs the global mongo mock is skipped, so that client belongs to whichever
    earlier test's now-closed function-scoped loop first touched Mongo — and the
    device register path (create the server integration, resolve it, then
    add_user_integration) dies with ``RuntimeError: Event loop is closed`` on its
    first Mongo call.

    Every repository resolves its handle through
    ``app.db.repositories.base.get_async_collection`` on *every* call, so patching
    that one symbol repoints the whole repository layer regardless of which
    modules are already imported — the same seam ``mongo_db`` and the repository
    contract suite use.

    The client is built from the app's own ``settings.MONGO_DB`` (DB "GAIA",
    matching ``init_mongodb``), not from the ``mongodb_url`` fixture: the server
    under test is the real app, so it has to read and write the very database it
    is configured for. The two agree in CI but not on a dev machine, where
    borrowing ``mongodb_url`` would point the app at a database its credentials
    do not open.
    """
    from app.config.settings import settings

    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.MONGO_DB)
    db = client["GAIA"]

    monkeypatch.setattr("app.db.repositories.base.get_async_collection", lambda name: db[name])

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
        # Function-local so importing this conftest never builds the app factory's
        # import graph for service tests that never spin up a live server.
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
    real_redis: Redis, real_mongo_repositories: None
) -> AsyncIterator[LiveApiServer]:
    """A live, real GAIA API bound to a real localhost port.

    Depends on real_redis so redis_cache.redis is already patched to the
    per-worker test Redis, and on real_mongo_repositories so the repository layer
    is bound to this test's event loop — both before the app (and its listeners)
    start.
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
