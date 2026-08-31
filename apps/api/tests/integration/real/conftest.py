"""
Fixtures for service integration tests with real databases.

The approach: patch the app's singletons to point at real test containers,
then call production functions directly. No rewriting production logic.

Root conftest.py globally patches _get_mongodb_instance to MagicMock. We work
around that through one seam: ``app.db.repositories.base.get_async_collection``,
which every repository resolves on each call — patching it (see ``mongo_db``)
points the whole repository layer at a real per-test Motor client. Redis gets a
real connection patched into redis_cache the same way.

The shared DB connection fixtures (``mongodb_url``, ``redis_url``,
``postgres_url``, ``mongo_db``, ``real_redis``, ``hil_approvals_collection``)
live in ``tests/integration/real/db_fixtures.py`` — the e2e suite's
real-infra tests (``tests/e2e/test_hil_*_e2e.py``) import the same fixtures.
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

from tests.helpers import (
    HeaderDrivenAuthMiddleware,
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
    ``db_fixtures.py``; this suite applies it to all tests.
    """


# ---------------------------------------------------------------------------
# Per-test isolation: clean collections + patch app singletons
# ---------------------------------------------------------------------------


@pytest.fixture
async def conversations_collection(mongo_db):
    """The real ``conversations`` collection production code will read, emptied
    around each test so seeded documents can be asserted on exactly."""
    coll = mongo_db["conversations"]
    await coll.delete_many({})

    yield coll

    await coll.delete_many({})


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
    real_redis: Redis, mongo_db, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[LiveApiServer]:
    """A live, real GAIA API bound to a real localhost port.

    Depends on real_redis so redis_cache.redis is already patched to the
    per-worker test Redis, and on mongo_db so the repository layer resolves its
    collections through a Motor client created on THIS test's event loop — both
    before the app (and its listeners) start.

    The mongo_db dependency is load-bearing, not decoration: the client cached in
    ``app.db.mongodb.collections`` is process-global and latches onto the first
    event loop it is used from, so without the rebind the device register path
    (create integration -> resolve -> add_user_integration) hits an earlier
    test's closed loop and raises ``RuntimeError: Event loop is closed``.
    """
    from app.services.device import device_service

    # The daemon sleeps for the server's `interval` hint BEFORE each poll, so
    # approval is never seen in under PAIRING_POLL_INTERVAL_SECONDS (5s), paid once
    # per pairing. The wire contract (daemon obeys the server hint) is still
    # exercised for real; only the cadence is faster here.
    monkeypatch.setattr(device_service, "PAIRING_POLL_INTERVAL_SECONDS", 1)
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
    """Factory to seed a conversation document in real MongoDB.

    Writes the legacy camelCase timestamp pair exactly as production does —
    ``createdAt`` an ISO string, ``updatedAt`` a BSON date (see
    ``ConversationDocument``). Callers may pass a ``datetime`` for ``createdAt``
    so they can do date arithmetic; it is normalized here. Seeding a raw
    ``datetime`` would make the repository's read-boundary validation reject the
    row, which is not a shape any production writer can produce.
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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Real-infra tier: skip at collection when real services are unavailable.

    A bare local run (no USE_REAL_SERVICES=1, no Docker) must skip this whole
    directory in milliseconds — never hang on dead ports or fail with
    connection errors after a slow boot. pytest calls this hook with EVERY
    collected item, so scope the skip to this conftest's own directory.
    """

    dir_root = Path(__file__).resolve().parent
    skip_items_without_real_services([item for item in items if item.path.is_relative_to(dir_root)])
