"""
SERVICE: app/agents/core/graph_builder/checkpointer_manager.py
         :: CheckpointerManager.setup / .close / .get_checkpointer,
            init_checkpointer_manager (the @lazy_provider factory body),
            get_checkpointer_manager

This is the LangGraph checkpointer that backs conversation thread state /
agent memory in PostgreSQL. If it silently misconfigures the pool or the
saver, chat history is dropped or served from dead sockets — and the system
falls back to an in-memory saver, losing every user's persisted memory.
gate = 100% (P0 critical path: persistence).

EXPECTED
  - setup() builds ONE AsyncConnectionPool against `conninfo` with an exact,
    load-bearing set of kwargs (sizing + idle/lifetime recycling + libpq TCP
    keepalives via `kwargs=connection_kwargs` + `check` ping + open=False +
    timeout=30), then opens it (wait=True, timeout=30), binds an
    AsyncPostgresSaver to that very pool, awaits saver.setup(), sets up the
    AsyncPostgresStore schema, and returns `self`.
  - close() closes the pool iff one exists (idempotent before setup()).
  - get_checkpointer() returns the saver after setup(), else raises RuntimeError.
  - init_checkpointer_manager() (factory body) reads settings.POSTGRES_URL,
    constructs a CheckpointerManager with it, runs setup(), returns the manager.
  - get_checkpointer_manager() resolves the "checkpointer_manager" provider and
    raises RuntimeError if the registry yields a falsy value.

MECHANISM (setup): AsyncConnectionPool(conninfo, min_size=1, max_size=max_pool_size,
  max_idle=300, max_lifetime=1800, kwargs={autocommit,prepare_threshold=0,
  keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5},
  check=AsyncConnectionPool.check_connection, open=False, timeout=30);
  await pool.open(wait=True, timeout=30); AsyncPostgresSaver(conn=pool);
  await checkpointer.setup(); async with AsyncPostgresStore.from_conn_string(conninfo)
  as store: await store.setup(); return self.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - real round-trip: a checkpoint written via aput is returned by aget_tuple   [persistence]
  - thread isolation: thread_1's checkpoint never appears under thread_2        [cross-user safety]
  - missing thread -> aget_tuple returns None (no crash)
  - get_checkpointer() before setup() raises RuntimeError mentioning "setup"
  - pool constructed with conninfo, min_size=1, max_size=max_pool_size(=20),
    max_idle=300, max_lifetime=1800, open=False, timeout=30                     [pool sizing/recycle]
  - connection_kwargs EXACT: autocommit True, prepare_threshold 0, keepalives 1,
    keepalives_idle 30, keepalives_interval 10, keepalives_count 5              [VXLAN keepalive defence]
  - check kwarg is AsyncConnectionPool.check_connection (dead-socket ping)
  - pool.open awaited with wait=True, timeout=30
  - saver bound to the SAME pool object (conn=pool), stored on .checkpointer
  - saver.setup() awaited; store schema setup() awaited via from_conn_string(conninfo)
  - setup() returns self (so `await mgr.setup()` is the manager)
  - pool.open raising propagates; saver.setup raising propagates (no swallow)
  - close() closes the pool; close() before setup() is a no-op (pool is None)
  - factory: init_checkpointer_manager builds a manager with settings.POSTGRES_URL
    and returns it (not None)
  - get_checkpointer_manager resolves "checkpointer_manager"; falsy -> RuntimeError

EQUIVALENT MUTANTS (allowed survivors, justified): none expected.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langgraph.checkpoint.base import empty_checkpoint
from psycopg_pool import AsyncConnectionPool
import pytest

import app.agents.core.graph_builder.checkpointer_manager as cm
from app.agents.core.graph_builder.checkpointer_manager import (
    CheckpointerManager,
    get_checkpointer_manager,
    init_checkpointer_manager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def manager(postgres_url: str) -> CheckpointerManager:  # type: ignore[misc]
    """Function-scoped CheckpointerManager bound to REAL Postgres."""
    mgr = CheckpointerManager(conninfo=postgres_url)
    await mgr.setup()
    yield mgr  # type: ignore[misc]
    await mgr.close()


@pytest.fixture
def mocked_pg_boundary():
    """Mock only the psycopg/langgraph I/O boundary.

    Replaces AsyncConnectionPool, AsyncPostgresSaver and AsyncPostgresStore in
    the module under test so setup() runs its full real logic (kwargs assembly,
    open call, saver binding, schema setup) without touching a database. Yields
    handles to assert exactly what setup() passed to each boundary call.
    """
    pool_instance = MagicMock(name="pool_instance")
    pool_instance.open = AsyncMock()
    pool_instance.close = AsyncMock()
    pool_cls = MagicMock(name="AsyncConnectionPool", return_value=pool_instance)
    # The production code passes AsyncConnectionPool.check_connection as `check`.
    # Keep the real bound attribute so an identity assertion is meaningful.
    pool_cls.check_connection = AsyncConnectionPool.check_connection

    saver_instance = MagicMock(name="saver_instance")
    saver_instance.setup = AsyncMock()
    saver_cls = MagicMock(name="AsyncPostgresSaver", return_value=saver_instance)

    store_instance = MagicMock(name="store_instance")
    store_instance.setup = AsyncMock()
    store_ctx = MagicMock(name="store_ctx")
    store_ctx.__aenter__ = AsyncMock(return_value=store_instance)
    store_ctx.__aexit__ = AsyncMock(return_value=False)
    store_cls = MagicMock(name="AsyncPostgresStore")
    store_cls.from_conn_string = MagicMock(return_value=store_ctx)

    with (
        patch.object(cm, "AsyncConnectionPool", pool_cls),
        patch.object(cm, "AsyncPostgresSaver", saver_cls),
        patch.object(cm, "AsyncPostgresStore", store_cls),
    ):
        yield {
            "pool_cls": pool_cls,
            "pool_instance": pool_instance,
            "saver_cls": saver_cls,
            "saver_instance": saver_instance,
            "store_cls": store_cls,
            "store_instance": store_instance,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


_META: dict = {"source": "input", "step": 0, "writes": None, "parents": {}}


# ===========================================================================
# 1) REAL Postgres: persistence behaviour the users actually depend on
# ===========================================================================


@pytest.mark.service
class TestRealPersistence:
    """Checkpoints written via aput must be retrievable and thread-isolated."""

    async def test_setup_returns_manager_and_exposes_live_checkpointer(
        self, postgres_url: str
    ) -> None:
        """setup() must return the manager itself and get_checkpointer() be non-None."""
        mgr = CheckpointerManager(conninfo=postgres_url)
        returned = await mgr.setup()
        try:
            # setup() returns self — callers rely on `mgr = await CheckpointerManager(...).setup()`
            assert returned is mgr
            assert mgr.get_checkpointer() is mgr.checkpointer
            assert mgr.checkpointer is not None
        finally:
            await mgr.close()

    async def test_checkpoint_round_trip(self, manager: CheckpointerManager) -> None:
        """A checkpoint written with aput must be returned by aget_tuple."""
        checkpointer = manager.get_checkpointer()
        config = _thread_config(str(uuid4()))
        checkpoint = empty_checkpoint()

        saved_config = await checkpointer.aput(config, checkpoint, _META, {})
        assert saved_config is not None

        result = await checkpointer.aget_tuple(config)
        assert result is not None
        assert result.checkpoint["id"] == checkpoint["id"]

    async def test_missing_thread_returns_none(self, manager: CheckpointerManager) -> None:
        """aget_tuple for an unknown thread_id returns None (no crash)."""
        result = await manager.get_checkpointer().aget_tuple(
            _thread_config(f"nonexistent-{uuid4()}")
        )
        assert result is None

    async def test_threads_are_isolated(self, manager: CheckpointerManager) -> None:
        """thread_1's checkpoint must never surface when querying thread_2.

        Guards against a misconfigured pool / schema bug that would serve one
        user another user's conversation history.
        """
        checkpointer = manager.get_checkpointer()
        thread_1, thread_2 = str(uuid4()), str(uuid4())
        cp_1, cp_2 = empty_checkpoint(), empty_checkpoint()

        await checkpointer.aput(_thread_config(thread_1), cp_1, _META, {})
        await checkpointer.aput(_thread_config(thread_2), cp_2, _META, {})

        r1 = await checkpointer.aget_tuple(_thread_config(thread_1))
        r2 = await checkpointer.aget_tuple(_thread_config(thread_2))
        assert r1 is not None and r2 is not None
        assert r1.checkpoint["id"] == cp_1["id"]
        assert r2.checkpoint["id"] == cp_2["id"]

        ids_in_thread_2 = [
            t.checkpoint["id"] async for t in checkpointer.alist(_thread_config(thread_2))
        ]
        assert cp_1["id"] not in ids_in_thread_2, (
            f"thread_1 checkpoint leaked into thread_2 listing: {ids_in_thread_2}"
        )

    async def test_get_checkpointer_before_setup_raises(self, postgres_url: str) -> None:
        """get_checkpointer() before setup() raises RuntimeError mentioning setup."""
        mgr = CheckpointerManager(conninfo=postgres_url)
        with pytest.raises(RuntimeError, match="setup"):
            mgr.get_checkpointer()


# ===========================================================================
# 2) Pool / saver / store WIRING — mock only the psycopg-langgraph boundary
#    and assert the exact kwargs the production code passes.
# ===========================================================================


@pytest.mark.service
class TestPoolConfiguration:
    """setup() must build the pool with the exact sizing + resilience kwargs."""

    async def test_pool_built_with_exact_sizing_kwargs(self, mocked_pg_boundary) -> None:
        """conninfo, min_size, max_size(=max_pool_size), max_idle, max_lifetime,
        open, timeout are all load-bearing — a wrong value silently degrades
        pool behaviour (too few/too many conns, stale sockets, blocking opens)."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y", max_pool_size=20)
        await mgr.setup()

        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["conninfo"] == "postgresql://x/y"
        assert kwargs["min_size"] == 1
        assert kwargs["max_size"] == 20  # bound to max_pool_size
        assert kwargs["max_idle"] == 300
        assert kwargs["max_lifetime"] == 1800
        assert kwargs["open"] is False
        assert kwargs["timeout"] == 30

    async def test_default_max_pool_size_is_20(self, mocked_pg_boundary) -> None:
        """When max_pool_size is not supplied, the default (20) must reach max_size.

        Locks the default pool ceiling: a smaller default would throttle
        concurrent chat threads; a larger one would over-subscribe Postgres.
        """
        mgr = CheckpointerManager(conninfo="postgresql://x/y")  # no max_pool_size
        await mgr.setup()
        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["max_size"] == 20

    async def test_max_size_tracks_max_pool_size_argument(self, mocked_pg_boundary) -> None:
        """max_size must be the constructor's max_pool_size, not a hardcoded 20."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y", max_pool_size=7)
        await mgr.setup()
        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["max_size"] == 7

    async def test_connection_kwargs_are_exact(self, mocked_pg_boundary) -> None:
        """The libpq keepalive + autocommit + prepare_threshold block is the
        VXLAN dead-socket defence. Each value must reach psycopg verbatim."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()

        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["kwargs"] == {
            "autocommit": True,
            "prepare_threshold": 0,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }

    async def test_pool_check_is_check_connection(self, mocked_pg_boundary) -> None:
        """`check` must be AsyncConnectionPool.check_connection so each handed-out
        connection is pinged (dead sockets are recycled, not served)."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()

        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["check"] is AsyncConnectionPool.check_connection

    async def test_pool_opened_with_wait_and_timeout(self, mocked_pg_boundary) -> None:
        """pool.open must be awaited with wait=True, timeout=30 (block until
        the pool is actually usable before the saver touches it)."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()

        pool_open = mocked_pg_boundary["pool_instance"].open
        pool_open.assert_awaited_once()
        _, open_kwargs = pool_open.call_args
        assert open_kwargs["wait"] is True
        assert open_kwargs["timeout"] == 30


@pytest.mark.service
class TestSaverAndStoreWiring:
    """The saver must bind to the opened pool; the saver+store schema must be set up."""

    async def test_saver_bound_to_the_opened_pool(self, mocked_pg_boundary) -> None:
        """AsyncPostgresSaver must receive the SAME pool instance (conn=pool) and
        be stored as .checkpointer — binding a different/fresh conn would mean
        the saver never uses the configured, keepalive-protected pool."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()

        _, saver_kwargs = mocked_pg_boundary["saver_cls"].call_args
        assert saver_kwargs["conn"] is mocked_pg_boundary["pool_instance"]
        assert mgr.checkpointer is mocked_pg_boundary["saver_instance"]

    async def test_saver_setup_awaited(self, mocked_pg_boundary) -> None:
        """checkpointer.setup() must be awaited (creates the checkpoint tables)."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()
        mocked_pg_boundary["saver_instance"].setup.assert_awaited_once()

    async def test_store_schema_setup_via_conninfo(self, mocked_pg_boundary) -> None:
        """The store schema must be set up from the SAME conninfo, and its
        setup() awaited inside the async-with block."""
        mgr = CheckpointerManager(conninfo="postgresql://store/here")
        await mgr.setup()

        mocked_pg_boundary["store_cls"].from_conn_string.assert_called_once_with(
            "postgresql://store/here"
        )
        mocked_pg_boundary["store_instance"].setup.assert_awaited_once()

    async def test_setup_returns_self(self, mocked_pg_boundary) -> None:
        """setup() must return the manager instance for fluent use."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        assert await mgr.setup() is mgr


@pytest.mark.service
class TestSetupErrorPaths:
    """Initialisation failures must propagate so the lazy provider can fall back
    (to InMemorySaver) loudly — never silently swallow them."""

    async def test_pool_open_failure_propagates(self, mocked_pg_boundary) -> None:
        """If pool.open raises, setup() must raise — not return a half-built manager."""
        mocked_pg_boundary["pool_instance"].open.side_effect = ConnectionError("no route")
        mgr = CheckpointerManager(conninfo="postgresql://x/y")

        with pytest.raises(ConnectionError, match="no route"):
            await mgr.setup()
        # saver must NOT have been bound after a failed open
        assert mgr.checkpointer is None

    async def test_saver_setup_failure_propagates(self, mocked_pg_boundary) -> None:
        """If checkpointer.setup() raises, setup() must raise (no silent success)."""
        mocked_pg_boundary["saver_instance"].setup.side_effect = RuntimeError("schema fail")
        mgr = CheckpointerManager(conninfo="postgresql://x/y")

        with pytest.raises(RuntimeError, match="schema fail"):
            await mgr.setup()


@pytest.mark.service
class TestClose:
    """close() must release the pool, and tolerate being called before setup()."""

    async def test_close_closes_the_pool(self, mocked_pg_boundary) -> None:
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        await mgr.setup()
        await mgr.close()
        mocked_pg_boundary["pool_instance"].close.assert_awaited_once()

    async def test_close_before_setup_is_noop(self) -> None:
        """close() with no pool yet must not raise (pool is None)."""
        mgr = CheckpointerManager(conninfo="postgresql://x/y")
        assert mgr.pool is None
        await mgr.close()  # must not raise


# ===========================================================================
# 3) Factory + accessor (the @lazy_provider plumbing)
# ===========================================================================


@pytest.mark.service
class TestFactory:
    """init_checkpointer_manager() must build a manager from settings.POSTGRES_URL."""

    async def test_factory_builds_manager_from_settings_url(
        self, mocked_pg_boundary, monkeypatch
    ) -> None:
        """The factory body reads settings.POSTGRES_URL, constructs the manager
        with it, runs setup(), and returns the manager (not None)."""
        monkeypatch.setattr(cm.settings, "POSTGRES_URL", "postgresql://from/settings")

        # init_checkpointer_manager is the @lazy_provider registration callable;
        # its underlying coroutine is the real factory body.
        loader = init_checkpointer_manager()
        manager = await loader.loader_func()

        assert isinstance(manager, CheckpointerManager)
        assert manager.conninfo == "postgresql://from/settings"
        # setup() ran: pool was built from the settings URL and the saver bound
        _, kwargs = mocked_pg_boundary["pool_cls"].call_args
        assert kwargs["conninfo"] == "postgresql://from/settings"
        assert manager.checkpointer is mocked_pg_boundary["saver_instance"]


@pytest.mark.service
class TestGetCheckpointerManager:
    """get_checkpointer_manager() resolves the provider; falsy -> RuntimeError."""

    async def test_returns_resolved_provider(self) -> None:
        """A non-None provider instance is returned as-is."""
        sentinel = CheckpointerManager(conninfo="postgresql://x/y")
        with patch.object(cm.providers, "aget", new=AsyncMock(return_value=sentinel)) as aget:
            result = await get_checkpointer_manager()
        assert result is sentinel
        aget.assert_awaited_once_with("checkpointer_manager")

    async def test_missing_provider_raises(self) -> None:
        """If the registry yields a falsy value, raise RuntimeError 'not available'
        rather than handing back None (which would crash callers downstream)."""
        with patch.object(cm.providers, "aget", new=AsyncMock(return_value=None)):
            with pytest.raises(RuntimeError, match="not available"):
                await get_checkpointer_manager()
