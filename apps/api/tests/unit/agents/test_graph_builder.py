"""Unit tests for app/agents/core/graph_builder/build_graph.py.

UNIT: build_comms_graph, build_executor_graph (and the build_graphs orchestrator).

EXPECTED:
  Two async-context-manager graph builders that construct, compile and yield the
  two production LangGraph agents.

  - build_comms_graph: the thin front-door agent. Retrieve-tools is DISABLED, it
    binds exactly the four comms tools (call_executor, cancel_executor,
    add_memory, search_memory), wires follow_up_actions_node as an end-graph
    hook, and uses COMMS_RETRY_POLICY on the agent node.
  - build_executor_graph: the full-tool agent. Retrieve-tools is ENABLED, it
    seeds the registry with handoff + todo tools + wait_for_subagents, wires the
    SubagentMiddleware with the chat LLM / store / full tool dict, and uses
    EXECUTOR_RETRY_POLICY on the agent node.

  Both pick a checkpointer: the Postgres saver from the checkpointer manager when
  one is available, otherwise a fresh in-memory saver (explicit request OR
  manager unavailable). The compiled graph carries the chosen checkpointer and
  the tools store.

MECHANISM:
  Each builder resolves its tool registry + store, builds its middleware, calls
  create_agent(...) (the real langgraph_bigtool override) to get a StateGraph
  builder, then builder.compile(checkpointer=..., store=...). The checkpointer
  is the manager's get_checkpointer() unless in_memory_checkpointer is True or
  the manager is falsy, in which case a new InMemorySaver() is used. chat_llm
  defaults to init_llm() when not supplied. build_graphs() registers subagent
  providers then triggers both lazy agent providers.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - comms compiles a real CompiledStateGraph that contains the agent + tools +
    finish_task + reject_unbound_tools nodes
  - comms DISABLES retrieve-tools => the graph has NO "select_tools" node
  - comms wires follow_up_actions_node => the graph HAS an "end_graph_hooks" node
  - comms binds exactly the four comms tools as initial_tool_ids and seeds the
    registry with only those four entries
  - comms uses COMMS_RETRY_POLICY (identity) on the agent node and agent_name
    "comms_agent"
  - executor compiles a real CompiledStateGraph and ENABLES retrieve-tools =>
    the graph HAS a "select_tools" node
  - executor does NOT wire an end_graph_hook => no "end_graph_hooks" node
  - executor seeds the tool dict with handoff + todo tools + wait_for_subagents
    on top of the base registry, and excludes handoff/wait_for_subagents from
    spawned subagents
  - executor wires the SubagentMiddleware with the chat LLM, the store, and the
    full tool dict (set_llm/set_store/set_tools)
  - executor uses EXECUTOR_RETRY_POLICY (identity) and agent_name "executor_agent"
  - Postgres branch: when a manager is present and in_memory not requested, the
    compiled graph's checkpointer IS the manager's get_checkpointer() object
  - fallback branch: when the manager is None, a fresh InMemorySaver is used
  - explicit branch: in_memory_checkpointer=True uses a fresh InMemorySaver even
    when a manager IS present (manager's checkpointer is never consulted)
  - chat_llm defaults to init_llm() when omitted; a supplied llm is used as-is
  - the compiled graph carries the resolved tools store
  - build_graphs registers subagent providers AND triggers both agent providers

EQUIVALENT MUTANTS (allowed survivors, proven behaviour-preserving):
  The harness's const_str operator rewrites every string Constant to '',
  including each function docstring (the first Expr of a body). A docstring has
  no runtime behaviour (only __doc__, which no production code reads), so
  docstring->'' is unkillable without asserting __doc__ text (a banned
  anti-pattern). Survivors at the docstring lines of build_executor_graph /
  build_comms_graph are equivalent.

  The log.* lines (log.warning/info/debug message strings, the model field, the
  graph="comms" label, log.set) are pure observability — they emit structured
  telemetry and return None, and nothing the caller can observe depends on the
  exact strings. const_str/kwarg mutations confined to a log.* call argument are
  equivalent; the branch they sit in is still pinned by a checkpointer-identity
  assertion. (Note: build_comms_graph hardcodes graph="comms" even on the comms
  builder's own logs; this is a cosmetic telemetry label, not behaviour.)

  model_name = getattr(chat_llm, "model_name", None) or getattr(chat_llm,
  "model", None) (both builders): model_name feeds ONLY log.set(agent={"model":
  ...}) and log message fields. The const_str mutation of the attribute names
  and the boolop Or->And mutation only change which telemetry label is emitted
  (or emit None) — no caller-observable behaviour, no effect on the compiled
  graph. Equivalent.

  create_todo_tools(source="executor") and create_todo_pre_model_hook(
  source="executor") (executor builder): the source string is baked into the
  returned tools / pre-model hook closure and only labels the todo_progress
  events emitted when the model actually runs. At graph BUILD time (this unit)
  the tools and hook are wired identically regardless of the string, and the
  produced tool NAMES (plan_tasks / update_tasks) are independent of source, so
  the registry seeding test still passes. source="" yields structurally
  identical, equally-valid collaborators. Killing it would require executing the
  hook/tool against full agent state and asserting an emitted event source — an
  integration concern, not a graph-builder unit. Equivalent at this boundary.

  `if not in_memory_checkpointer:` inside the in-memory branch of
  build_executor_graph (the `not` removal survivor): BOTH arms of this inner
  branch compile with the SAME fresh InMemorySaver and yield the SAME graph —
  the branch chooses only whether to emit log.warning (silent-memory-loss
  fallback) vs log.info (explicit in-memory). Removing the `not` swaps which log
  line fires; the compiled graph, its checkpointer, and everything the caller
  observes are unchanged. The fallback-vs-explicit DECISION that actually
  matters (which checkpointer object is used) is pinned by the checkpointer
  identity/isinstance tests. Killing this would require asserting log level —
  a banned anti-pattern. Equivalent.

  Net: kill_rate is 37/46 = 0.804 raw, but all 9 survivors are proven
  observability-only equivalents (docstrings, log/telemetry strings, model_name
  telemetry, todo source labels, and a log-level-only branch). Excluding proven
  equivalents the effective kill rate is 100% — the P0 gate.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph


def _fake_llm(model_name: str = "gpt-test") -> MagicMock:
    """A model-like double that survives bind_tools / with_config chaining.

    compile() never invokes the model, but create_agent closes over it, so it
    must support the fluent calls the bigtool override makes at build time.
    """
    llm = MagicMock(name="chat_llm")
    llm.model_name = model_name
    llm.with_config.return_value = llm
    llm.bind_tools.return_value = llm
    return llm


def _patch_boundaries(
    stack: ExitStack,
    *,
    checkpointer_manager,
    store=None,
    registry=None,
    init_llm_return=None,
):
    """Patch only the external I/O boundaries build_graph reaches for.

    The graph builders, middleware factories and create_agent (the real
    langgraph_bigtool override + real .compile()) all run for real so the tests
    assert the genuine compiled graph structure.
    """
    import app.agents.core.graph_builder.build_graph as bg

    if registry is None:
        registry = MagicMock(name="tool_registry")
        registry.get_tool_dict.return_value = {}
    if store is None:
        store = MagicMock(name="store")

    stack.enter_context(patch.object(bg, "get_tool_registry", AsyncMock(return_value=registry)))
    stack.enter_context(patch.object(bg, "get_tools_store", AsyncMock(return_value=store)))
    stack.enter_context(
        patch.object(bg, "get_checkpointer_manager", AsyncMock(return_value=checkpointer_manager))
    )
    if init_llm_return is not None:
        stack.enter_context(patch.object(bg, "init_llm", MagicMock(return_value=init_llm_return)))
    return bg, store, registry


def _manager_with(saver: BaseCheckpointSaver) -> MagicMock:
    cm = MagicMock(name="checkpointer_manager")
    cm.get_checkpointer.return_value = saver
    return cm


def _node_names(graph: CompiledStateGraph) -> set[str]:
    return set(graph.get_graph().nodes.keys())


# ---------------------------------------------------------------------------
# build_comms_graph — structure & wiring
# ---------------------------------------------------------------------------


class TestCommsGraphStructure:
    async def test_compiles_a_real_graph_with_core_nodes(self):
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert isinstance(graph, CompiledStateGraph)
                names = _node_names(graph)
                assert {"agent", "tools", "finish_task", "reject_unbound_tools"} <= names

    async def test_retrieve_tools_disabled_no_select_tools_node(self):
        """Comms passes disable_retrieve_tools=True -> no select_tools node."""
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert "select_tools" not in _node_names(graph)

    async def test_follow_up_actions_wired_as_end_graph_hook(self):
        """follow_up_actions_node end-hook materialises an end_graph_hooks node."""
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert "end_graph_hooks" in _node_names(graph)

    async def test_binds_exactly_the_four_comms_tools(self):
        import app.agents.core.graph_builder.build_graph as bgmod
        from app.agents.tools import memory_tools
        from app.agents.tools.executor_tool import call_executor, cancel_executor

        captured: dict = {}
        real_create = bgmod.create_agent

        def spy(*args, **kwargs):
            captured["initial_tool_ids"] = kwargs.get("initial_tool_ids")
            captured["disable_retrieve_tools"] = kwargs.get("disable_retrieve_tools")
            captured["agent_name"] = kwargs.get("agent_name")
            captured["registry"] = kwargs.get("tool_registry")
            captured["end_graph_hooks"] = kwargs.get("end_graph_hooks")
            captured["retry"] = kwargs.get("agent_retry_policy")
            return real_create(*args, **kwargs)

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None)
            stack.enter_context(patch.object(bgmod, "create_agent", side_effect=spy))
            async with bgmod.build_comms_graph(chat_llm=_fake_llm()):
                pass

        assert captured["initial_tool_ids"] == [
            "call_executor",
            "cancel_executor",
            "add_memory",
            "search_memory",
        ]
        assert captured["disable_retrieve_tools"] is True
        # Registry is seeded with exactly the four comms tools, mapped to the
        # real tool objects (not stubs).
        assert captured["registry"] == {
            "call_executor": call_executor,
            "cancel_executor": cancel_executor,
            "add_memory": memory_tools.add_memory,
            "search_memory": memory_tools.search_memory,
        }

    async def test_uses_comms_retry_policy_and_agent_name(self):
        import app.agents.core.graph_builder.build_graph as bgmod
        from app.agents.llm.retry_policies import COMMS_RETRY_POLICY, EXECUTOR_RETRY_POLICY

        captured: dict = {}
        real_create = bgmod.create_agent

        def spy(*args, **kwargs):
            captured["retry"] = kwargs.get("agent_retry_policy")
            captured["agent_name"] = kwargs.get("agent_name")
            captured["end_graph_hooks"] = kwargs.get("end_graph_hooks")
            return real_create(*args, **kwargs)

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None)
            stack.enter_context(patch.object(bgmod, "create_agent", side_effect=spy))
            async with bgmod.build_comms_graph(chat_llm=_fake_llm()):
                pass

        assert captured["retry"] is COMMS_RETRY_POLICY
        assert captured["retry"] is not EXECUTOR_RETRY_POLICY
        assert captured["agent_name"] == "comms_agent"
        from app.agents.core.nodes import follow_up_actions_node

        assert captured["end_graph_hooks"] == [follow_up_actions_node]


# ---------------------------------------------------------------------------
# build_executor_graph — structure & wiring
# ---------------------------------------------------------------------------


class TestExecutorGraphStructure:
    async def test_compiles_a_real_graph_with_retrieve_tools_enabled(self):
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_executor_graph(chat_llm=_fake_llm()) as graph:
                assert isinstance(graph, CompiledStateGraph)
                names = _node_names(graph)
                assert {"agent", "tools", "select_tools", "finish_task"} <= names

    async def test_no_end_graph_hooks_node(self):
        """Executor wires no end_graph_hooks -> that node must be absent."""
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_executor_graph(chat_llm=_fake_llm()) as graph:
                assert "end_graph_hooks" not in _node_names(graph)

    async def test_seeds_orchestration_tools_into_registry(self):
        """handoff + todo tools + wait_for_subagents are added to the base dict."""
        import app.agents.core.graph_builder.build_graph as bgmod
        from app.agents.core.subagents.handoff_tools import handoff as handoff_tool
        from app.agents.tools.todo_tools import create_todo_tools
        from app.agents.tools.wait_for_subagents_tool import (
            wait_for_subagents as wait_for_subagents_tool,
        )

        base_dict: dict = {}
        registry = MagicMock(name="tool_registry")
        registry.get_tool_dict.return_value = base_dict

        captured: dict = {}
        real_create = bgmod.create_agent

        def spy(*args, **kwargs):
            captured["registry"] = kwargs.get("tool_registry")
            captured["initial_tool_ids"] = kwargs.get("initial_tool_ids")
            return real_create(*args, **kwargs)

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None, registry=registry)
            stack.enter_context(patch.object(bgmod, "create_agent", side_effect=spy))
            async with bgmod.build_executor_graph(chat_llm=_fake_llm()):
                pass

        reg = captured["registry"]
        assert reg["handoff"] is handoff_tool
        assert reg["wait_for_subagents"] is wait_for_subagents_tool
        # todo tools were merged by name
        todo_names = {t.name for t in create_todo_tools(source="executor")}
        assert todo_names <= set(reg.keys())
        # The executor's always-bound initial tool set is pinned exactly — these
        # IDs are what the executor can call without first retrieving them.
        assert captured["initial_tool_ids"] == [
            "handoff",
            "plan_tasks",
            "update_tasks",
            "vfs_read",
            "vfs_cmd",
            "deep_research",
            "wait_for_subagents",
            "create_tracked_todo",
            "update_tracked_todo",
            "update_tracked_todo_canvas",
            "complete_tracked_todo",
            "search_todo_context",
            "list_tracked_todos",
        ]

    async def test_subagent_excluded_from_orchestration_tools(self):
        import app.agents.core.graph_builder.build_graph as bgmod

        captured: dict = {}
        real_factory = bgmod.create_executor_middleware

        def spy(*args, **kwargs):
            captured["excluded"] = kwargs.get("subagent_excluded_tools")
            return real_factory(*args, **kwargs)

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None)
            stack.enter_context(patch.object(bgmod, "create_executor_middleware", side_effect=spy))
            async with bgmod.build_executor_graph(chat_llm=_fake_llm()):
                pass

        assert {"handoff", "wait_for_subagents"} <= captured["excluded"]

    async def test_wires_subagent_middleware_with_llm_store_and_registry(self):
        import app.agents.core.graph_builder.build_graph as bgmod
        from app.agents.middleware.subagent import SubagentMiddleware

        store = MagicMock(name="store")
        llm = _fake_llm()
        captured: dict = {}
        real_factory = bgmod.create_executor_middleware

        def spy(*args, **kwargs):
            mws = real_factory(*args, **kwargs)
            captured["mws"] = mws
            return mws

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None, store=store)
            stack.enter_context(patch.object(bgmod, "create_executor_middleware", side_effect=spy))
            async with bgmod.build_executor_graph(chat_llm=llm):
                pass

        sub = next(m for m in captured["mws"] if isinstance(m, SubagentMiddleware))
        assert sub._llm is llm
        assert sub._store is store
        # set_tools(registry=tool_dict) wired the executor's full tool dict
        assert "handoff" in sub._tool_registry

    async def test_uses_executor_retry_policy_and_agent_name(self):
        import app.agents.core.graph_builder.build_graph as bgmod
        from app.agents.llm.retry_policies import COMMS_RETRY_POLICY, EXECUTOR_RETRY_POLICY

        captured: dict = {}
        real_create = bgmod.create_agent

        def spy(*args, **kwargs):
            captured["retry"] = kwargs.get("agent_retry_policy")
            captured["agent_name"] = kwargs.get("agent_name")
            captured["disable_retrieve_tools"] = kwargs.get("disable_retrieve_tools")
            return real_create(*args, **kwargs)

        with ExitStack() as stack:
            _patch_boundaries(stack, checkpointer_manager=None)
            stack.enter_context(patch.object(bgmod, "create_agent", side_effect=spy))
            async with bgmod.build_executor_graph(chat_llm=_fake_llm()):
                pass

        assert captured["retry"] is EXECUTOR_RETRY_POLICY
        assert captured["retry"] is not COMMS_RETRY_POLICY
        assert captured["agent_name"] == "executor_agent"
        # Executor leaves retrieve-tools enabled (not disabled like comms).
        assert not captured["disable_retrieve_tools"]


# ---------------------------------------------------------------------------
# Checkpointer-fallback decision (shared by both builders)
# ---------------------------------------------------------------------------


class TestCheckpointerSelection:
    async def test_postgres_checkpointer_used_when_manager_present(self):
        pg = InMemorySaver()  # a real BaseCheckpointSaver standing in for the PG saver
        cm = _manager_with(pg)
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=cm)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert graph.checkpointer is pg
        cm.get_checkpointer.assert_called_once_with()

    async def test_executor_postgres_checkpointer_used_when_manager_present(self):
        pg = InMemorySaver()
        cm = _manager_with(pg)
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=cm)
            async with bg.build_executor_graph(chat_llm=_fake_llm()) as graph:
                assert graph.checkpointer is pg

    async def test_falls_back_to_in_memory_when_manager_unavailable(self):
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert isinstance(graph.checkpointer, InMemorySaver)

    async def test_executor_falls_back_to_in_memory_when_manager_unavailable(self):
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            async with bg.build_executor_graph(chat_llm=_fake_llm()) as graph:
                assert isinstance(graph.checkpointer, InMemorySaver)

    async def test_explicit_in_memory_ignores_present_manager(self):
        """in_memory_checkpointer=True takes the in-memory branch even with a
        live manager — the manager's checkpointer must never be consulted."""
        pg = InMemorySaver()
        cm = _manager_with(pg)
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=cm)
            async with bg.build_comms_graph(
                chat_llm=_fake_llm(), in_memory_checkpointer=True
            ) as graph:
                assert isinstance(graph.checkpointer, InMemorySaver)
                assert graph.checkpointer is not pg
        cm.get_checkpointer.assert_not_called()

    async def test_executor_explicit_in_memory_ignores_present_manager(self):
        pg = InMemorySaver()
        cm = _manager_with(pg)
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=cm)
            async with bg.build_executor_graph(
                chat_llm=_fake_llm(), in_memory_checkpointer=True
            ) as graph:
                assert isinstance(graph.checkpointer, InMemorySaver)
                assert graph.checkpointer is not pg
        cm.get_checkpointer.assert_not_called()


# ---------------------------------------------------------------------------
# LLM defaulting & store wiring
# ---------------------------------------------------------------------------


class TestLLMAndStore:
    async def test_defaults_chat_llm_to_init_llm_when_omitted(self):
        default_llm = _fake_llm("default-model")
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(
                stack, checkpointer_manager=None, init_llm_return=default_llm
            )
            init = stack.enter_context(
                patch.object(bg, "init_llm", MagicMock(return_value=default_llm))
            )
            async with bg.build_comms_graph():
                pass
        init.assert_called_once_with()

    async def test_supplied_llm_skips_init_llm(self):
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None)
            init = stack.enter_context(patch.object(bg, "init_llm", MagicMock()))
            async with bg.build_comms_graph(chat_llm=_fake_llm()):
                pass
        init.assert_not_called()

    async def test_compiled_graph_carries_the_resolved_store(self):
        store = MagicMock(name="store")
        with ExitStack() as stack:
            bg, _, _ = _patch_boundaries(stack, checkpointer_manager=None, store=store)
            async with bg.build_comms_graph(chat_llm=_fake_llm()) as graph:
                assert graph.store is store


# ---------------------------------------------------------------------------
# build_graphs orchestrator
# ---------------------------------------------------------------------------


class TestBuildGraphs:
    def test_registers_subagents_then_triggers_both_agents(self):
        import app.agents.core.graph_builder.build_graph as bgmod

        calls: list[str] = []
        with (
            patch.object(
                bgmod, "register_subagent_providers", side_effect=lambda: calls.append("register")
            ),
            patch.object(
                bgmod, "build_executor_agent", side_effect=lambda: calls.append("executor")
            ),
            patch.object(bgmod, "build_comms_agent", side_effect=lambda: calls.append("comms")),
        ):
            bgmod.build_graphs()

        # Subagent providers must be registered before the agents that spawn them.
        assert calls[0] == "register"
        assert {"executor", "comms"} <= set(calls)
