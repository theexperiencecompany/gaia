"""Unit tests for the LangGraph checkpointer manager (graph_builder package).

TARGET UNIT: app/agents/core/graph_builder/checkpointer_manager.py

This file's quality contract is measured against ``checkpointer_manager.py``.
The ``build_graph.py`` tests further down cover a *sibling* unit and are kept
green but are not the mutation target of this rewrite.

=============================================================================
BEHAVIOR SPEC — checkpointer_manager.py
=============================================================================

UNIT: CheckpointerManager.__init__
EXPECTED: Store the connection string and pool ceiling; leave pool/checkpointer
          unset until setup() runs.
MECHANISM: self.conninfo = conninfo; self.max_pool_size = max_pool_size
           (default 20); self.pool = None; self.checkpointer = None.
MUST-CATCH:
  - conninfo is stored verbatim (not swapped/blanked)
  - max_pool_size defaults to 20 when omitted
  - an explicit max_pool_size overrides the default
  - pool and checkpointer both start as None (get_checkpointer must fail pre-setup)

UNIT: CheckpointerManager.setup
EXPECTED: Open a resilient async Postgres pool, build an AsyncPostgresSaver on
          that pool, run the saver schema setup, then run the store schema
          setup inside an async context manager, and return self.
MECHANISM: build connection_kwargs (autocommit/prepare_threshold/keepalives*);
           AsyncConnectionPool(conninfo, min_size=1, max_size, max_idle=300,
           max_lifetime=1800, kwargs=connection_kwargs,
           check=AsyncConnectionPool.check_connection, open=False, timeout=30);
           await pool.open(wait=True, timeout=30);
           AsyncPostgresSaver(conn=pool); await checkpointer.setup();
           async with AsyncPostgresStore.from_conn_string(conninfo) as store:
               await store.setup(); return self.
MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - the pool is built with the manager's conninfo (not a constant/blank)
  - max_size is wired from max_pool_size (mutating the arg changes the pool)
  - min_size=1, max_idle=300, max_lifetime=1800, open=False, timeout=30 are exact
  - the connection liveness check is AsyncConnectionPool.check_connection (dropping
    it hands out dead sockets)
  - connection_kwargs carry autocommit=True, prepare_threshold=0 and all four
    keepalive knobs with their exact values
  - pool.open is awaited with wait=True, timeout=30 (sync/positional drift caught)
  - the saver is constructed bound to the *same* pool object (conn=self.pool)
  - checkpointer.setup() is awaited (schema migration must run)
  - the store is created from the manager's conninfo and its setup() is awaited
  - the store context manager is exited (__aexit__) so the throwaway connection
    is released
  - setup returns self (chaining contract) and persists pool + checkpointer on self
  - if pool.open raises, setup propagates and the checkpointer is never set
  - if checkpointer.setup raises, setup propagates

UNIT: CheckpointerManager.close
EXPECTED: Close the pool when one exists; do nothing when it does not.
MECHANISM: if self.pool: await self.pool.close().
MUST-CATCH:
  - close() awaits pool.close() when a pool is present
  - close() is a no-op (no crash, no attribute access) when pool is None

UNIT: CheckpointerManager.get_checkpointer
EXPECTED: Return the live checkpointer once setup has run; otherwise raise.
MECHANISM: if not self.checkpointer: raise RuntimeError("...not been
           initialized..."); return self.checkpointer.
MUST-CATCH:
  - raises RuntimeError mentioning initialization before setup
  - returns the exact checkpointer object after it is assigned

UNIT: init_checkpointer_manager (the @lazy_provider factory body)
EXPECTED: Build a CheckpointerManager from settings.POSTGRES_URL, run setup(),
          and return the initialized manager.
MECHANISM: conninfo = settings.POSTGRES_URL; manager =
           CheckpointerManager(conninfo=conninfo); await manager.setup();
           return manager.
MUST-CATCH:
  - the manager is constructed from settings.POSTGRES_URL (not a hardcoded URL)
  - manager.setup() is awaited before the manager is returned
  - the returned object is the manager that was set up (same instance)

UNIT: get_checkpointer_manager
EXPECTED: Resolve the lazily-provided manager; raise if the provider yields None.
MECHANISM: manager = await providers.aget("checkpointer_manager");
           if not manager: raise RuntimeError("...not available"); return manager.
MUST-CATCH:
  - providers.aget is queried with the exact name "checkpointer_manager"
  - the resolved manager is returned unchanged
  - a None result raises RuntimeError mentioning availability

EQUIVALENT MUTANTS (allowed survivors, justified):
  - The two warning/info ``log.*`` strings inside build_graph fallbacks and the
    docstrings carry no behavioural contract for the checkpointer manager.
  - ``init_checkpointer_manager`` default max_pool_size is never overridden by the
    factory, so a mutation of the *factory's* (absent) pool-size arg has nothing
    to flip; covered indirectly by the __init__ default test instead.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.core.graph_builder.checkpointer_manager import (
    CheckpointerManager,
    get_checkpointer_manager,
    init_checkpointer_manager,
)

_MOD = "app.agents.core.graph_builder.build_graph"
_CM_MOD = "app.agents.core.graph_builder.checkpointer_manager"

_TEST_DB_URL = "postgresql://user:pw@db.example:5432/gaia_ckpt"  # pragma: allowlist secret


# ===================================================================
# CheckpointerManager — construction
# ===================================================================


class TestCheckpointerManagerInit:
    """__init__ stores config and leaves the pool/checkpointer unset."""

    def test_stores_conninfo_verbatim(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        assert mgr.conninfo == _TEST_DB_URL

    def test_default_max_pool_size_is_20(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        assert mgr.max_pool_size == 20

    def test_explicit_max_pool_size_overrides_default(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=50)
        assert mgr.max_pool_size == 50

    def test_pool_and_checkpointer_start_none(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        assert mgr.pool is None
        assert mgr.checkpointer is None


# ===================================================================
# CheckpointerManager.setup
# ===================================================================


def _patch_setup_dependencies(stack: ExitStack):
    """Patch the three psycopg/langgraph I/O boundaries used by setup().

    Returns the pool class mock, the constructed pool, the saver class mock,
    the constructed saver, the store class mock, the store context manager
    mock, and the store instance yielded by ``__aenter__``.
    """
    mock_pool = AsyncMock(name="pool")
    mock_pool_cls = MagicMock(name="AsyncConnectionPool")
    mock_pool_cls.return_value = mock_pool

    mock_saver = AsyncMock(name="saver")
    mock_saver_cls = MagicMock(name="AsyncPostgresSaver")
    mock_saver_cls.return_value = mock_saver

    mock_store_instance = AsyncMock(name="store")
    mock_store_ctx = AsyncMock(name="store_ctx")
    mock_store_ctx.__aenter__ = AsyncMock(return_value=mock_store_instance)
    mock_store_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_store_cls = MagicMock(name="AsyncPostgresStore")
    mock_store_cls.from_conn_string.return_value = mock_store_ctx

    stack.enter_context(patch(f"{_CM_MOD}.AsyncConnectionPool", mock_pool_cls))
    stack.enter_context(patch(f"{_CM_MOD}.AsyncPostgresSaver", mock_saver_cls))
    stack.enter_context(patch(f"{_CM_MOD}.AsyncPostgresStore", mock_store_cls))

    return {
        "pool_cls": mock_pool_cls,
        "pool": mock_pool,
        "saver_cls": mock_saver_cls,
        "saver": mock_saver,
        "store_cls": mock_store_cls,
        "store_ctx": mock_store_ctx,
        "store": mock_store_instance,
    }


class TestCheckpointerManagerSetup:
    """setup() opens the pool, builds + migrates the saver and store."""

    async def test_returns_self_and_persists_pool_and_checkpointer(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            result = await mgr.setup()

            assert result is mgr
            assert mgr.pool is deps["pool"]
            assert mgr.checkpointer is deps["saver"]

    async def test_pool_built_from_conninfo_and_max_pool_size(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=7)

            await mgr.setup()

            pool_kwargs = deps["pool_cls"].call_args.kwargs
            assert pool_kwargs["conninfo"] == _TEST_DB_URL
            assert pool_kwargs["max_size"] == 7

    async def test_pool_static_lifecycle_kwargs_are_exact(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            pool_kwargs = deps["pool_cls"].call_args.kwargs
            assert pool_kwargs["min_size"] == 1
            assert pool_kwargs["max_idle"] == 300
            assert pool_kwargs["max_lifetime"] == 1800
            assert pool_kwargs["open"] is False
            assert pool_kwargs["timeout"] == 30

    async def test_pool_uses_check_connection_liveness_probe(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            pool_kwargs = deps["pool_cls"].call_args.kwargs
            # The pool must ping each connection before handing it out using the
            # class' own check_connection; dropping it serves dead sockets.
            assert pool_kwargs["check"] is deps["pool_cls"].check_connection

    async def test_connection_kwargs_carry_keepalives_and_autocommit(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            conn_kwargs = deps["pool_cls"].call_args.kwargs["kwargs"]
            assert conn_kwargs == {
                "autocommit": True,
                "prepare_threshold": 0,
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }

    async def test_pool_opened_with_wait_and_timeout(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            deps["pool"].open.assert_awaited_once_with(wait=True, timeout=30)

    async def test_saver_bound_to_the_opened_pool(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            saver_kwargs = deps["saver_cls"].call_args.kwargs
            assert saver_kwargs["conn"] is deps["pool"]
            deps["saver"].setup.assert_awaited_once()

    async def test_store_created_from_conninfo_and_migrated(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            deps["store_cls"].from_conn_string.assert_called_once_with(_TEST_DB_URL)
            deps["store"].setup.assert_awaited_once()

    async def test_store_context_manager_is_exited(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            await mgr.setup()

            deps["store_ctx"].__aenter__.assert_awaited_once()
            deps["store_ctx"].__aexit__.assert_awaited_once()

    async def test_pool_open_failure_propagates_and_checkpointer_stays_unset(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            deps["pool"].open.side_effect = RuntimeError("pool open failed")
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            with pytest.raises(RuntimeError, match="pool open failed"):
                await mgr.setup()

            assert mgr.checkpointer is None
            deps["saver_cls"].assert_not_called()

    async def test_checkpointer_setup_failure_propagates(self):
        with ExitStack() as stack:
            deps = _patch_setup_dependencies(stack)
            deps["saver"].setup.side_effect = RuntimeError("schema migration failed")
            mgr = CheckpointerManager(conninfo=_TEST_DB_URL, max_pool_size=5)

            with pytest.raises(RuntimeError, match="schema migration failed"):
                await mgr.setup()

            # The store schema must not run if the checkpointer schema failed.
            deps["store_cls"].from_conn_string.assert_not_called()


# ===================================================================
# CheckpointerManager.close
# ===================================================================


class TestCheckpointerManagerClose:
    """close() releases the pool only when one exists."""

    async def test_closes_pool_when_present(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        mock_pool = AsyncMock(name="pool")
        mgr.pool = mock_pool

        await mgr.close()

        mock_pool.close.assert_awaited_once()

    async def test_noop_when_pool_is_none(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        assert mgr.pool is None

        # Must complete without raising / touching a missing pool.
        await mgr.close()


# ===================================================================
# CheckpointerManager.get_checkpointer
# ===================================================================


class TestGetCheckpointer:
    """get_checkpointer() guards against use before setup."""

    def test_raises_before_initialization(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        with pytest.raises(RuntimeError, match="not been initialized"):
            mgr.get_checkpointer()

    def test_returns_checkpointer_once_assigned(self):
        mgr = CheckpointerManager(conninfo=_TEST_DB_URL)
        fake_cp = MagicMock(name="checkpointer")
        mgr.checkpointer = fake_cp

        assert mgr.get_checkpointer() is fake_cp


# ===================================================================
# init_checkpointer_manager (the @lazy_provider factory body)
# ===================================================================


class TestInitCheckpointerManager:
    """The lazy-provider factory builds + sets up a manager from settings."""

    async def test_factory_builds_manager_from_settings_and_runs_setup(self):
        # init_checkpointer_manager is a @lazy_provider registrator; calling it
        # registers the provider and returns the LazyLoader. The raw async
        # factory body is reachable as loader.loader_func.
        with patch.object(CheckpointerManager, "setup", autospec=True) as mock_setup:

            async def _setup(self):
                self.pool = MagicMock(name="pool")
                self.checkpointer = MagicMock(name="checkpointer")
                return self

            mock_setup.side_effect = _setup

            with patch.object(
                __import__(_CM_MOD, fromlist=["settings"]).settings,
                "POSTGRES_URL",
                _TEST_DB_URL,
            ):
                loader = init_checkpointer_manager()
                factory = loader.loader_func

                manager = await factory()

        assert isinstance(manager, CheckpointerManager)
        assert manager.conninfo == _TEST_DB_URL
        # setup ran on the very manager that was returned.
        mock_setup.assert_awaited_once()
        assert mock_setup.await_args.args[0] is manager


# ===================================================================
# get_checkpointer_manager
# ===================================================================


class TestGetCheckpointerManager:
    """get_checkpointer_manager() resolves the provider or raises."""

    async def test_returns_manager_from_provider(self):
        fake_mgr = MagicMock(name="manager")
        with patch(f"{_CM_MOD}.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=fake_mgr)

            result = await get_checkpointer_manager()

        assert result is fake_mgr
        mock_providers.aget.assert_awaited_once_with("checkpointer_manager")

    async def test_raises_when_provider_returns_none(self):
        with patch(f"{_CM_MOD}.providers") as mock_providers:
            mock_providers.aget = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="not available"):
                await get_checkpointer_manager()


# ===================================================================
# build_graph.py — sibling unit (kept green; not the mutation target)
# ===================================================================


def _mock_state_graph():
    """Return a mock StateGraph whose .compile() returns a mock compiled graph."""
    builder = MagicMock(name="StateGraph")
    compiled = MagicMock(name="CompiledGraph")
    builder.compile.return_value = compiled
    return builder, compiled


def _apply_patches(stack: ExitStack, overrides: dict | None = None):
    """Apply all standard patches for build_graph and return useful references."""
    mock_llm = MagicMock()
    mock_llm.model_name = "test-model"

    builder, compiled = _mock_state_graph()

    defaults = {
        f"{_MOD}.init_llm": MagicMock(return_value=mock_llm),
        f"{_MOD}.get_tools_store": AsyncMock(return_value=MagicMock(name="store")),
        f"{_MOD}.get_tool_registry": AsyncMock(
            return_value=MagicMock(get_tool_dict=MagicMock(return_value={"tool_a": MagicMock()})),
        ),
        f"{_MOD}.create_todo_tools": MagicMock(return_value=[MagicMock(name="plan_tasks")]),
        f"{_MOD}.create_todo_pre_model_hook": MagicMock(return_value=MagicMock(name="todo_hook")),
        f"{_MOD}.create_executor_middleware": MagicMock(return_value=[]),
        f"{_MOD}.create_comms_middleware": MagicMock(return_value=[]),
        f"{_MOD}.build_executor_child_tool_runtime_config": MagicMock(return_value={}),
        f"{_MOD}.get_retrieve_tools_function": MagicMock(return_value=AsyncMock()),
        f"{_MOD}.create_agent": MagicMock(return_value=builder),
        f"{_MOD}.get_checkpointer_manager": AsyncMock(return_value=None),
        f"{_MOD}.log": MagicMock(),
    }

    if overrides:
        defaults.update(overrides)

    mocks: dict[str, MagicMock] = {}
    for target, mock_val in defaults.items():
        mocks[target] = stack.enter_context(patch(target, mock_val))

    return {
        "llm": mock_llm,
        "builder": builder,
        "compiled": compiled,
        "mocks": mocks,
    }


class TestBuildCommsGraph:
    """Tests for build_comms_graph context manager."""

    async def test_yields_compiled_graph_in_memory(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=True
            ) as graph:
                assert graph is deps["compiled"]

            deps["builder"].compile.assert_called_once()

    async def test_yields_compiled_graph_postgres(self):
        fake_cp = MagicMock(name="postgres_checkpointer")
        fake_manager = MagicMock()
        fake_manager.get_checkpointer.return_value = fake_cp

        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.get_checkpointer_manager": AsyncMock(return_value=fake_manager)},
            )
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=False
            ) as graph:
                assert graph is deps["compiled"]

            call_kwargs = deps["builder"].compile.call_args.kwargs
            assert call_kwargs["checkpointer"] is fake_cp

    async def test_falls_back_to_in_memory_when_no_manager(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=False
            ) as graph:
                assert graph is deps["compiled"]

            deps["builder"].compile.assert_called_once()

    async def test_uses_init_llm_when_none_provided(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=None, in_memory_checkpointer=True) as graph:
                assert graph is deps["compiled"]

            deps["mocks"][f"{_MOD}.init_llm"].assert_called_once()

    async def test_create_agent_called_with_comms_params(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            mock_ca = deps["mocks"][f"{_MOD}.create_agent"]
            mock_ca.assert_called_once()
            kwargs = mock_ca.call_args.kwargs
            assert kwargs["agent_name"] == "comms_agent"
            assert kwargs["disable_retrieve_tools"] is True
            assert "call_executor" in kwargs["initial_tool_ids"]
            assert "add_memory" in kwargs["initial_tool_ids"]
            assert "search_memory" in kwargs["initial_tool_ids"]

    async def test_comms_graph_has_end_graph_hooks(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            assert "end_graph_hooks" in kwargs
            assert len(kwargs["end_graph_hooks"]) == 1

    async def test_comms_tool_registry_contains_expected_tools(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            tool_registry = kwargs["tool_registry"]
            assert "call_executor" in tool_registry
            assert "add_memory" in tool_registry
            assert "search_memory" in tool_registry

    async def test_comms_pre_model_hooks_structure(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            pre_model_hooks = kwargs["pre_model_hooks"]
            # comms agent: filter_messages_node, manage_system_prompts_node
            assert len(pre_model_hooks) == 2

    async def test_comms_middleware_passed_to_create_agent(self):
        mock_mw = [MagicMock(name="mw1")]
        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.create_comms_middleware": MagicMock(return_value=mock_mw)},
            )
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            assert kwargs["middleware"] is mock_mw


class TestBuildExecutorGraph:
    """Tests for build_executor_graph context manager."""

    async def test_yields_compiled_graph_in_memory(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=True
            ) as graph:
                assert graph is deps["compiled"]

    async def test_yields_compiled_graph_postgres(self):
        fake_cp = MagicMock(name="postgres_checkpointer")
        fake_manager = MagicMock()
        fake_manager.get_checkpointer.return_value = fake_cp

        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.get_checkpointer_manager": AsyncMock(return_value=fake_manager)},
            )
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=False
            ) as graph:
                assert graph is deps["compiled"]

            call_kwargs = deps["builder"].compile.call_args.kwargs
            assert call_kwargs["checkpointer"] is fake_cp

    async def test_falls_back_to_in_memory_when_no_manager(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(
                chat_llm=deps["llm"], in_memory_checkpointer=False
            ) as graph:
                assert graph is deps["compiled"]

    async def test_uses_init_llm_when_none_provided(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=None, in_memory_checkpointer=True) as _:
                pass

            deps["mocks"][f"{_MOD}.init_llm"].assert_called_once()

    async def test_create_agent_called_with_executor_params(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            mock_ca = deps["mocks"][f"{_MOD}.create_agent"]
            mock_ca.assert_called_once()
            kwargs = mock_ca.call_args.kwargs
            assert kwargs["agent_name"] == "executor_agent"
            assert "handoff" in kwargs["initial_tool_ids"]
            assert "plan_tasks" in kwargs["initial_tool_ids"]

    async def test_executor_tool_registry_includes_handoff(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            assert "handoff" in kwargs["tool_registry"]

    async def test_executor_pre_model_hooks_includes_todo_hook(self):
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            pre_model_hooks = kwargs["pre_model_hooks"]
            # executor: filter_messages_node, manage_system_prompts_node, todo_hook
            assert len(pre_model_hooks) == 3

    async def test_subagent_middleware_wired_when_present(self):
        """When SubagentMiddleware is in the stack, set_llm/set_tools/set_store run."""
        from app.agents.middleware.subagent import SubagentMiddleware

        mock_sub_mw = MagicMock(spec=SubagentMiddleware)

        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.create_executor_middleware": MagicMock(return_value=[mock_sub_mw])},
            )
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

        mock_sub_mw.set_llm.assert_called_once_with(deps["llm"])
        mock_sub_mw.set_tools.assert_called_once()
        mock_sub_mw.set_store.assert_called_once()

    async def test_no_subagent_middleware_logs_warning(self):
        """When SubagentMiddleware is not in the stack, a warning is logged."""
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            mock_log = deps["mocks"][f"{_MOD}.log"]
            mock_log.warning.assert_called_once()
            assert "SubagentMiddleware" in mock_log.warning.call_args[0][0]

    async def test_model_name_extracted_from_llm(self):
        """Graph builder extracts model_name from the LLM and passes it to log.set."""
        with ExitStack() as stack:
            deps = _apply_patches(stack)
            deps["llm"].model_name = "gpt-4"
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            mock_log = deps["mocks"][f"{_MOD}.log"]
            mock_log.set.assert_called()
            set_kwargs = mock_log.set.call_args.kwargs
            assert set_kwargs["agent"]["model"] == "gpt-4"

    async def test_model_fallback_to_model_attr(self):
        """When model_name is None, falls back to model attribute."""
        llm_no_model_name = MagicMock(spec=[])
        llm_no_model_name.model = "claude-3-opus"

        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(
                chat_llm=llm_no_model_name, in_memory_checkpointer=True
            ) as _:
                pass

            mock_log = deps["mocks"][f"{_MOD}.log"]
            mock_log.set.assert_called()
            set_kwargs = mock_log.set.call_args.kwargs
            assert set_kwargs["agent"]["model"] == "claude-3-opus"

    async def test_executor_middleware_passed_to_create_agent(self):
        mock_mw = [MagicMock(name="mw1")]
        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.create_executor_middleware": MagicMock(return_value=mock_mw)},
            )
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            assert kwargs["middleware"] is mock_mw

    async def test_executor_retrieve_tools_function_set(self):
        mock_retrieve = AsyncMock()
        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.get_retrieve_tools_function": MagicMock(return_value=mock_retrieve)},
            )
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            kwargs = deps["mocks"][f"{_MOD}.create_agent"].call_args.kwargs
            assert kwargs["retrieve_tools_coroutine"] is mock_retrieve


class TestBuildGraphs:
    """Tests for build_graphs top-level registration function."""

    @patch(f"{_MOD}.log")
    @patch(f"{_MOD}.build_comms_agent")
    @patch(f"{_MOD}.build_executor_agent")
    @patch(f"{_MOD}.register_subagent_providers")
    def test_registers_both_agents(
        self,
        mock_register_subagent,
        mock_build_executor,
        mock_build_comms,
        mock_log,
    ):
        from app.agents.core.graph_builder.build_graph import build_graphs

        build_graphs()

        mock_register_subagent.assert_called_once()
        mock_build_executor.assert_called_once()
        mock_build_comms.assert_called_once()

    @patch(f"{_MOD}.log")
    @patch(f"{_MOD}.build_comms_agent")
    @patch(f"{_MOD}.build_executor_agent")
    @patch(f"{_MOD}.register_subagent_providers")
    def test_calls_in_correct_order(
        self,
        mock_register_subagent,
        mock_build_executor,
        mock_build_comms,
        mock_log,
    ):
        from app.agents.core.graph_builder.build_graph import build_graphs

        call_order: list[str] = []
        mock_register_subagent.side_effect = lambda: call_order.append("register")
        mock_build_executor.side_effect = lambda: call_order.append("executor")
        mock_build_comms.side_effect = lambda: call_order.append("comms")

        build_graphs()

        assert call_order == ["register", "executor", "comms"]

    @patch(f"{_MOD}.log")
    @patch(f"{_MOD}.build_comms_agent")
    @patch(f"{_MOD}.build_executor_agent")
    @patch(f"{_MOD}.register_subagent_providers")
    def test_logs_start_and_completion(
        self,
        mock_register_subagent,
        mock_build_executor,
        mock_build_comms,
        mock_log,
    ):
        from app.agents.core.graph_builder.build_graph import build_graphs

        build_graphs()

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("Building" in msg for msg in info_calls)
        assert any("successfully" in msg for msg in info_calls)


class TestBuildCommsAgent:
    """Tests for the lazy_provider-decorated build_comms_agent."""

    def test_build_comms_agent_is_callable_registrator(self):
        """build_comms_agent is a register_provider callable (from @lazy_provider)."""
        from app.agents.core.graph_builder.build_graph import build_comms_agent

        assert callable(build_comms_agent)

    @patch(f"{_MOD}.build_comms_graph")
    @patch(f"{_MOD}.log")
    async def test_build_comms_graph_yields_compiled(self, mock_log, mock_build_comms_graph):
        compiled = MagicMock(name="compiled")

        acm = AsyncMock()
        acm.__aenter__ = AsyncMock(return_value=compiled)
        acm.__aexit__ = AsyncMock(return_value=False)
        mock_build_comms_graph.return_value = acm

        from app.agents.core.graph_builder import build_graph

        async with build_graph.build_comms_graph() as graph:
            assert graph is compiled


class TestBuildExecutorAgent:
    """Tests for the lazy_provider-decorated build_executor_agent."""

    def test_build_executor_agent_is_callable_registrator(self):
        """build_executor_agent is a register_provider callable (from @lazy_provider)."""
        from app.agents.core.graph_builder.build_graph import build_executor_agent

        assert callable(build_executor_agent)

    @patch(f"{_MOD}.build_executor_graph")
    @patch(f"{_MOD}.log")
    async def test_build_executor_graph_yields_compiled(self, mock_log, mock_build_executor_graph):
        compiled = MagicMock(name="compiled")

        acm = AsyncMock()
        acm.__aenter__ = AsyncMock(return_value=compiled)
        acm.__aexit__ = AsyncMock(return_value=False)
        mock_build_executor_graph.return_value = acm

        from app.agents.core.graph_builder import build_graph

        async with build_graph.build_executor_graph() as graph:
            assert graph is compiled


class TestCompileKwargs:
    """Verify compile() is called with checkpointer and store."""

    async def test_comms_compile_receives_store(self):
        mock_store = MagicMock(name="tools_store")
        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.get_tools_store": AsyncMock(return_value=mock_store)},
            )
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            call_kwargs = deps["builder"].compile.call_args.kwargs
            assert call_kwargs["store"] is mock_store

    async def test_executor_compile_receives_store(self):
        mock_store = MagicMock(name="tools_store")
        with ExitStack() as stack:
            deps = _apply_patches(
                stack,
                {f"{_MOD}.get_tools_store": AsyncMock(return_value=mock_store)},
            )
            from app.agents.core.graph_builder.build_graph import build_executor_graph

            async with build_executor_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            call_kwargs = deps["builder"].compile.call_args.kwargs
            assert call_kwargs["store"] is mock_store

    async def test_in_memory_checkpointer_is_inmemory_saver(self):
        """When in_memory_checkpointer=True, compile receives an InMemorySaver."""
        from langgraph.checkpoint.memory import InMemorySaver

        with ExitStack() as stack:
            deps = _apply_patches(stack)
            from app.agents.core.graph_builder.build_graph import build_comms_graph

            async with build_comms_graph(chat_llm=deps["llm"], in_memory_checkpointer=True) as _:
                pass

            call_kwargs = deps["builder"].compile.call_args.kwargs
            assert isinstance(call_kwargs["checkpointer"], InMemorySaver)
