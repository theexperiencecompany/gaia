"""Unit tests for app/agents/core/graph_builder/checkpointer_manager.py.

UNIT: CheckpointerManager, init_checkpointer_manager, get_checkpointer_manager

EXPECTED:
  CheckpointerManager owns the Postgres connection pool + AsyncPostgresSaver
  that backs LangGraph thread persistence. It is created lazily, set up once,
  reused, and torn down on shutdown.

MECHANISM:
  __init__(conninfo, max_pool_size=20): stores conninfo, max_pool_size; pool
    and checkpointer start as None.
  setup(): builds an AsyncConnectionPool (min_size=1, max_size=max_pool_size,
    max_idle=300, max_lifetime=1800, timeout=30, open=False, check=connection
    check) with libpq keepalive kwargs (autocommit=True, prepare_threshold=0,
    keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5);
    awaits pool.open(wait=True, timeout=30); builds AsyncPostgresSaver(conn=pool)
    and awaits .setup(); runs AsyncPostgresStore.from_conn_string(conninfo) and
    awaits store.setup() inside an async-with; returns self.
  close(): if pool exists, await pool.close(); otherwise no-op.
  get_checkpointer(): return the checkpointer, or raise RuntimeError if setup()
    was never run.
  init_checkpointer_manager() [wrapped by @lazy_provider]: build a
    CheckpointerManager(conninfo=settings.POSTGRES_URL), await setup(), return it.
  get_checkpointer_manager(): await providers.aget("checkpointer_manager");
    raise RuntimeError if the provider returns None.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - __init__ stores conninfo, max_pool_size and leaves pool/checkpointer None
    [default max_pool_size is exactly 20]
  - setup() returns self (callers chain on it) and assigns pool + checkpointer
  - setup() opens the pool with wait=True, timeout=30 (dead-socket defence)
  - setup() passes the exact pool sizing/recycling kwargs (max_size from arg,
    min_size=1, max_idle=300, max_lifetime=1800, timeout=30, open=False)
  - setup() passes the exact libpq keepalive connection kwargs (the whole point
    of this module — Swarm VXLAN drops idle TCP otherwise)
  - setup() builds the saver from the SAME pool, awaits saver.setup() AND
    store.setup() (both schemas must be created)
  - get_checkpointer() returns the real checkpointer once present
  - get_checkpointer() raises RuntimeError before setup (no silent None)
  - close() closes the pool when present, and is a no-op (no raise) when absent
  - init_checkpointer_manager builds the manager from settings.POSTGRES_URL
    (not a constant) and awaits setup() before returning it
  - get_checkpointer_manager resolves the provider by the exact name
    "checkpointer_manager" and returns it
  - get_checkpointer_manager raises RuntimeError when the provider is None

EQUIVALENT MUTANTS (allowed survivors, proven behaviour-preserving):
  The mutation harness's const_str operator rewrites every string Constant —
  including each function/class docstring — to ''. A docstring is the first
  Expr statement of its body and has no runtime behaviour (only __doc__, which
  no production code reads), so docstring->'' is unkillable without asserting
  __doc__ text (a banned anti-pattern). Survivors at the docstring lines of
  CheckpointerManager, setup, close, get_checkpointer, init_checkpointer_manager
  and get_checkpointer_manager are equivalent. Every non-docstring mutant
  (comparisons, the RuntimeError messages, pool/keepalive kwargs, the
  "checkpointer_manager" provider name, return values) is killed.

  Note on scope: build_graph.py (build_comms_graph / build_executor_graph /
  build_graphs) is a separate unit covered by tests/integration/agents/* and
  tests/e2e/test_retry_policy.py; its retry policy moved to
  app/agents/llm/retry_policies.py. The previous colocated build_graph unit
  tests (including a RED block importing the deleted _AGENT_RETRY_POLICY) were
  removed so this file targets only its named unit.
"""

from contextlib import ExitStack
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_CM_MOD = "app.agents.core.graph_builder.checkpointer_manager"
_TEST_DB_URL = "postgresql://localhost/test"


def _make_manager(conninfo: str = _TEST_DB_URL, max_pool_size: int = 5):
    from app.agents.core.graph_builder.checkpointer_manager import (
        CheckpointerManager,
    )

    return CheckpointerManager(conninfo=conninfo, max_pool_size=max_pool_size)


def _patch_setup_collaborators(stack: ExitStack):
    """Patch the three external constructors setup() reaches for.

    Returns the patched classes plus the live mock pool / saver / store-instance
    so tests can assert real wiring instead of just call counts.
    """
    from app.agents.core.graph_builder import checkpointer_manager as cm

    pool = AsyncMock(name="pool")
    saver = AsyncMock(name="saver")
    store_instance = AsyncMock(name="store_instance")

    pool_cls = stack.enter_context(patch.object(cm, "AsyncConnectionPool"))
    pool_cls.return_value = pool
    # check= references the classmethod on the patched class; give it a sentinel
    pool_cls.check_connection = MagicMock(name="check_connection")

    saver_cls = stack.enter_context(patch.object(cm, "AsyncPostgresSaver"))
    saver_cls.return_value = saver

    store_cls = stack.enter_context(patch.object(cm, "AsyncPostgresStore"))
    store_ctx = AsyncMock()
    store_ctx.__aenter__ = AsyncMock(return_value=store_instance)
    store_ctx.__aexit__ = AsyncMock(return_value=False)
    store_cls.from_conn_string.return_value = store_ctx

    return pool_cls, pool, saver_cls, saver, store_cls, store_instance


class TestCheckpointerManagerInit:
    def test_stores_conninfo_and_leaves_resources_uninitialized(self):
        mgr = _make_manager(conninfo="postgresql://h/db", max_pool_size=7)
        assert mgr.conninfo == "postgresql://h/db"
        assert mgr.max_pool_size == 7
        assert mgr.pool is None
        assert mgr.checkpointer is None

    def test_default_pool_size_is_twenty(self):
        from app.agents.core.graph_builder.checkpointer_manager import (
            CheckpointerManager,
        )

        mgr = CheckpointerManager(conninfo="postgres://x")
        assert mgr.max_pool_size == 20


class TestCheckpointerManagerSetup:
    async def test_returns_self_and_assigns_pool_and_checkpointer(self):
        with ExitStack() as stack:
            _, pool, _, saver, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager()

            result = await mgr.setup()

            assert result is mgr
            assert mgr.pool is pool
            assert mgr.checkpointer is saver

    async def test_opens_pool_with_wait_and_timeout(self):
        with ExitStack() as stack:
            _, pool, _, _, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager()

            await mgr.setup()

            pool.open.assert_awaited_once_with(wait=True, timeout=30)

    async def test_pool_sizing_and_recycling_kwargs(self):
        with ExitStack() as stack:
            pool_cls, _, _, _, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager(max_pool_size=5)

            await mgr.setup()

            kwargs = pool_cls.call_args.kwargs
            assert kwargs["conninfo"] == _TEST_DB_URL
            assert kwargs["min_size"] == 1
            assert kwargs["max_size"] == 5  # comes from max_pool_size, not a constant
            assert kwargs["max_idle"] == 300
            assert kwargs["max_lifetime"] == 1800
            assert kwargs["timeout"] == 30
            assert kwargs["open"] is False

    async def test_max_size_tracks_constructor_arg(self):
        """max_size must reflect the manager's max_pool_size, not a literal."""
        with ExitStack() as stack:
            pool_cls, _, _, _, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager(max_pool_size=11)

            await mgr.setup()

            assert pool_cls.call_args.kwargs["max_size"] == 11

    async def test_libpq_keepalive_connection_kwargs(self):
        """The keepalive kwargs are the entire reason this module exists."""
        with ExitStack() as stack:
            pool_cls, _, _, _, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager()

            await mgr.setup()

            conn_kwargs = pool_cls.call_args.kwargs["kwargs"]
            assert conn_kwargs == {
                "autocommit": True,
                "prepare_threshold": 0,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }

    async def test_saver_built_from_pool_and_set_up(self):
        with ExitStack() as stack:
            _, pool, saver_cls, saver, _, _ = _patch_setup_collaborators(stack)
            mgr = _make_manager()

            await mgr.setup()

            saver_cls.assert_called_once_with(conn=pool)
            saver.setup.assert_awaited_once()

    async def test_store_schema_initialized_from_conninfo(self):
        with ExitStack() as stack:
            _, _, _, _, store_cls, store_instance = _patch_setup_collaborators(stack)
            mgr = _make_manager(conninfo="postgresql://h/store_db")

            await mgr.setup()

            store_cls.from_conn_string.assert_called_once_with("postgresql://h/store_db")
            store_instance.setup.assert_awaited_once()


class TestCheckpointerManagerGetCheckpointer:
    def test_raises_runtime_error_before_setup(self):
        mgr = _make_manager()
        with pytest.raises(RuntimeError, match="not been initialized"):
            mgr.get_checkpointer()

    def test_returns_checkpointer_once_present(self):
        mgr = _make_manager()
        sentinel = MagicMock(name="checkpointer")
        mgr.checkpointer = sentinel
        assert mgr.get_checkpointer() is sentinel


class TestCheckpointerManagerClose:
    async def test_closes_pool_when_present(self):
        mgr = _make_manager()
        pool = AsyncMock()
        mgr.pool = pool

        await mgr.close()

        pool.close.assert_awaited_once()

    async def test_noop_when_no_pool(self):
        mgr = _make_manager()
        # No pool assigned -> must not attempt to close anything, must not raise.
        await mgr.close()
        assert mgr.pool is None


def _wrapped_init_coro():
    """Extract the raw `init_checkpointer_manager` coroutine.

    @lazy_provider replaces the module attribute with a `register_provider`
    callable; the original coroutine is captured in its closure. We test the
    real coroutine, not the registration wrapper.
    """
    from app.agents.core.graph_builder import checkpointer_manager as cm

    for cell in cm.init_checkpointer_manager.__closure__ or []:
        candidate = cell.cell_contents
        if (
            inspect.iscoroutinefunction(candidate)
            and candidate.__name__ == "init_checkpointer_manager"
        ):
            return candidate
    raise AssertionError("wrapped init_checkpointer_manager coroutine not found")


class TestInitCheckpointerManager:
    async def test_builds_manager_from_settings_url_and_sets_up(self):
        coro = _wrapped_init_coro()
        fake_mgr = MagicMock(name="manager")
        fake_mgr.setup = AsyncMock(return_value=fake_mgr)

        with (
            patch(f"{_CM_MOD}.CheckpointerManager", return_value=fake_mgr) as mock_cls,
            patch(f"{_CM_MOD}.settings") as mock_settings,
        ):
            mock_settings.POSTGRES_URL = "postgresql://prod/main"
            result = await coro()

        assert result is fake_mgr
        mock_cls.assert_called_once_with(conninfo="postgresql://prod/main")
        fake_mgr.setup.assert_awaited_once()


class TestGetCheckpointerManager:
    async def test_returns_manager_resolved_from_provider(self):
        from app.agents.core.graph_builder.checkpointer_manager import (
            get_checkpointer_manager,
        )

        fake_mgr = MagicMock(name="manager")
        with patch(f"{_CM_MOD}.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=fake_mgr)
            result = await get_checkpointer_manager()

        assert result is fake_mgr
        mock_providers.aget.assert_awaited_once_with("checkpointer_manager")

    async def test_raises_when_provider_returns_none(self):
        from app.agents.core.graph_builder.checkpointer_manager import (
            get_checkpointer_manager,
        )

        with patch(f"{_CM_MOD}.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="not available"):
                await get_checkpointer_manager()
