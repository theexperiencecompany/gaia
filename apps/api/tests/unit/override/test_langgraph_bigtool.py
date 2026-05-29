"""Behavior spec + tests for app.override.langgraph_bigtool.create_agent.

UNIT: app/override/langgraph_bigtool/create_agent.py :: create_agent
      (and the closures it builds and wires into the StateGraph:
       call_model, acall_model, select_tools, aselect_tools, should_continue,
       reject_unbound_tools, areject_unbound_tools, finish_task_node,
       afinish_task_node, _get_bound_tool_names)

EXPECTED:
  create_agent builds a langgraph StateGraph wiring an agent node, a tools node,
  a finish_task node, a reject_unbound_tools node, an optional select_tools node
  and an optional end_graph_hooks node, with a should_continue conditional edge.
  The closures it builds encode all the routing / model-binding / tool-selection
  behavior the agent depends on at runtime.

MECHANISM:
  - middleware tools are extracted: only BaseTool instances kept; missing `tools`
    attr -> []; non-BaseTool entries dropped.
  - retrieve_tools wiring: disabled when disable_retrieve_tools; else a default
    retrieval StructuredTool is built when neither fn nor coroutine given.
  - graph: select_tools node only added when retrieve enabled; end_graph_hooks
    node only added when hooks given.
  - call_model: raises RuntimeError when middleware configured (sync path banned);
    binds [retrieve?]+selected+initial+middleware tools (deduped); invokes the
    bound model with state["messages"]; fills empty response with
    "Empty response from model."; appends NEW_MESSAGE_BREAKER iff
    agent_name == "comms_agent"; returns {"messages": [response]}.
  - acall_model: runs pre_model_hooks + before_model; binds same tool set; routes
    through wrap_model_invocation iff middleware has_wrap_model_call else direct
    ainvoke(state["messages"]); fills empty / appends breaker like sync; runs
    after_model; returns {"messages":[response]} PLUS any non-base keys after_model
    added (base = {"messages","selected_tool_ids"}).
  - select_tools/aselect_tools: raise RuntimeError if retrieve disabled; for each
    tool_call, invoke retrieve_tools with args (+store_arg +user_id from config);
    dict result -> split tools_to_bind/response; list result -> both = list;
    drop "subagent:"-prefixed ids from binding; dedupe; return
    {"messages":[...], "selected_tool_ids":[...]}.
  - should_continue: last msg not AIMessage / no tool_calls -> "end_graph_hooks"
    (iff end_graph_hooks) else END. finish_task calls -> Send(FINISH_TASK_NAME).
    a retrieve_tools call -> Send("select_tools"). a bound call -> Send("tools").
    an unbound call whose underscore-canonical form maps to a bound name is
    rewritten to that bound name and routed to tools; otherwise -> Send(
    "reject_unbound_tools").
  - reject_unbound_tools: one error ToolMessage per call naming the tool and the
    retrieve_tools remediation; async delegates to sync.
  - finish_task_node: ToolMessage per call; content = str(args["result"]) or
    "Task completed." when result is None; name == FINISH_TASK_NAME; async
    delegates to sync.

MUST-CATCH (each maps to >=1 test + >=1 killed mutant):
  - create_agent returns a StateGraph with the core nodes; select_tools node
    present iff retrieve on; end_graph_hooks node present iff hooks given.
  - non-BaseTool middleware entries are filtered out of binding.
  - sync call_model with middleware raises RuntimeError.
  - call_model invokes the bound model with state["messages"] and returns it.
  - call_model binds retrieve_tools + selected + initial + middleware tools.
  - empty model response -> exact "Empty response from model." sentinel;
    non-empty response is left untouched.
  - comms_agent appends NEW_MESSAGE_BREAKER; other agents do NOT.
  - acall_model direct path calls ainvoke with state["messages"].
  - acall_model wrap path used iff has_wrap_model_call() is True.
  - acall_model surfaces after_model-added keys (e.g. "todos") but not base keys.
  - acall_model runs pre_model_hooks before invocation.
  - select_tools dict vs list result both bind the tool id.
  - select_tools drops "subagent:"-prefixed ids.
  - select_tools injects user_id from config into retrieve args only when present.
  - should_continue: no tool calls -> END / end_graph_hooks.
  - should_continue: finish_task -> Send(FINISH_TASK_NAME) early (priority).
  - should_continue: retrieve_tools call -> Send("select_tools").
  - should_continue: bound (selected/initial) call -> Send("tools").
  - should_continue: unbound call -> Send("reject_unbound_tools"), not tools.
  - should_continue: hyphen/underscore canonical rewrite routes to tools.
  - reject_unbound_tools: error message names the unbound tool + remediation.
  - finish_task_node: result payload vs "Task completed." default.

EQUIVALENT MUTANTS (allowed survivors, justified):
  1. The message-preview logging block in acall_model (lines ~196-206) is
     best-effort observability only, wrapped in try/except and feeding only
     log.info. Its truncation arithmetic (`[-6:]`, `> 200`, `[:197] + "..."`)
     and literal preview strings never affect any return value or routing, so
     mutations confined to that block that only change the logged string are
     behavior-preserving. test_log_preview_* pins the externally observable
     consequence (the model is still invoked exactly once with the real
     messages and returns normally) so any structural mutation that would break
     execution is still killed.
  2. The RuntimeError messages in select_tools / aselect_tools (the
     `if retrieve_tools is None: raise RuntimeError(...)` guards) are defensive
     dead code: those closures are only wired into the graph as the
     "select_tools" node when retrieve is ENABLED (retrieve_tools is not None),
     and when retrieve is DISABLED the node is never created — so the guard's
     True branch is unreachable through the public builder. The const_str -> ''
     mutations on those message strings are therefore behavior-preserving.
  3. Docstrings and code comments (e.g. the acall_model / _get_bound_tool_names
     docstrings) are non-executable; their const_str -> '' mutations cannot
     change behavior.
  4. path_map.insert(0, "select_tools") ordering (the int 0): path_map is the
     set of *valid* conditional-edge destinations; LangGraph routes by the Send
     target name, not by list position, so the insert index does not affect
     routing.
  5. The And -> Or mutations in the select_tools_node branch selection
     (`retrieve_tools_function is not None and retrieve_tools_coroutine is None`,
     and the symmetric coroutine-only branch): these elif branches are only
     reached when the prior branch (both fn+coro) is False. For every reachable
     input (fn-only, coro-only — both-None can't occur because the default
     retrieval tool fills both), And and Or evaluate to the same branch, so the
     mutation is behavior-preserving.
  6. The ValueError("One of retrieve_tools_function or retrieve_tools_coroutine
     must be provided.") is unreachable: when retrieve is enabled and neither
     fn nor coro is supplied, the default retrieval tool fills BOTH before this
     branch, so the else is dead. Its const_str -> '' is behavior-preserving.
  7. The `limit` (default 2) and `namespace_prefix` (default ("tools",)) only
     feed the *default* semantic-retrieval tool built against a live Store.
     Exercising them requires a real ChromaDB-backed Store (out of scope for a
     unit test that mocks at the I/O boundary), so const_int 2->3 and the
     namespace string mutation on those defaults are not unit-observable.
  8. The `agent_name` default ("main_agent"): the only behavioral check on
     agent_name is `agent_name == "comms_agent"` (append breaker). Any default
     other than "comms_agent" yields identical behavior, so const_str '' on the
     "main_agent" default is behavior-preserving (covered indirectly by
     test_default_agent_name_does_not_append_breaker, which pins the no-breaker
     outcome for the default).
  9. The create_agent docstring lines and inner-function docstrings/comments
     are non-executable; const_str -> '' on them cannot change behavior.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
import pytest

from app.constants.general import FINISH_TASK_NAME, NEW_MESSAGE_BREAKER
from app.override.langgraph_bigtool.create_agent import create_agent

# ---------------------------------------------------------------------------
# Fixtures / builders (I/O boundary = the LLM; everything else is real)
# ---------------------------------------------------------------------------


@tool
def dummy_tool_a(query: str) -> str:
    """A dummy tool for testing."""
    return "result_a"


@tool
def dummy_tool_b(query: str) -> str:
    """Another dummy tool for testing."""
    return "result_b"


def _make_tool_registry(*tools_list: BaseTool) -> dict[str, BaseTool]:
    return {t.name: t for t in tools_list}


def _make_llm(response: AIMessage | None = None) -> MagicMock:
    """LLM stub mocked only at the invoke boundary.

    Records the tools passed to bind_tools and the messages passed to
    invoke/ainvoke so tests can assert the real binding/invocation contract.
    """
    resp = response if response is not None else AIMessage(content="hello")
    llm = MagicMock()
    configured = MagicMock()
    bound = MagicMock()
    bound.invoke = MagicMock(return_value=resp)
    bound.ainvoke = AsyncMock(return_value=resp)
    configured.bind_tools = MagicMock(return_value=bound)
    llm.with_config = MagicMock(return_value=configured)
    # expose inner mocks for assertions
    llm._configured = configured
    llm._bound = bound
    return llm


def _bound_tool_names(llm: MagicMock) -> list[str]:
    """Tool names passed to the (single) bind_tools call."""
    tools_arg = llm._configured.bind_tools.call_args.args[0]
    return [t.name for t in tools_arg]


def _make_config(**configurable: Any) -> dict:
    return {"configurable": configurable}


def _make_state(
    messages: list | None = None,
    selected_tool_ids: list | None = None,
    todos: list | None = None,
) -> dict:
    return {
        "messages": messages or [],
        "selected_tool_ids": selected_tool_ids or [],
        "todos": todos or [],
    }


def _agent_fn(builder: StateGraph):
    return builder.nodes["agent"].runnable.func  # type: ignore[union-attr]


def _agent_afn(builder: StateGraph):
    return builder.nodes["agent"].runnable.afunc  # type: ignore[union-attr]


def _should_continue(builder: StateGraph):
    return builder.branches["agent"]["should_continue"].path.func  # type: ignore[attr-defined]


def _edges(builder: StateGraph) -> set[tuple[str, str]]:
    return {(a, b) for a, b in builder.edges}


# ---------------------------------------------------------------------------
# create_agent — graph construction / wiring
# ---------------------------------------------------------------------------


class TestCreateAgentWiring:
    def test_returns_state_graph_with_core_nodes(self) -> None:
        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True
        )

        assert isinstance(builder, StateGraph)
        for node in ("agent", "tools", FINISH_TASK_NAME, "reject_unbound_tools"):
            assert node in builder.nodes

    def test_select_tools_node_present_when_retrieve_enabled(self) -> None:
        def my_func(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), retrieve_tools_function=my_func
        )

        assert "select_tools" in builder.nodes

    def test_select_tools_node_absent_when_retrieve_disabled(self) -> None:
        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True
        )

        assert "select_tools" not in builder.nodes

    def test_end_graph_hooks_node_present_only_when_hooks_given(self) -> None:
        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        with_hooks = create_agent(
            _make_llm(),
            _make_tool_registry(),
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )
        without = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)

        assert "end_graph_hooks" in with_hooks.nodes
        assert "end_graph_hooks" not in without.nodes

    def test_core_edges_wired(self) -> None:
        """tools and reject_unbound_tools loop back to agent; finish_task and
        the entry point are wired. These edge strings are the graph contract."""
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        edges = _edges(builder)
        assert ("tools", "agent") in edges
        assert ("reject_unbound_tools", "agent") in edges
        assert (FINISH_TASK_NAME, END) in edges
        # the entry point is "agent": START routes into the agent node
        assert (START, "agent") in edges

    def test_select_tools_edge_present_iff_retrieve_enabled(self) -> None:
        def my_func(query: str = "") -> list[str]:
            """Retrieve tools."""
            return []

        enabled = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), retrieve_tools_function=my_func
        )
        disabled = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True
        )
        assert ("select_tools", "agent") in _edges(enabled)
        assert ("select_tools", "agent") not in _edges(disabled)

    def test_finish_task_edge_targets_end_hooks_when_hooks_given(self) -> None:
        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            _make_llm(), _make_tool_registry(), disable_retrieve_tools=True, end_graph_hooks=[hook]
        )
        edges = _edges(builder)
        assert (FINISH_TASK_NAME, "end_graph_hooks") in edges
        assert ("end_graph_hooks", END) in edges
        assert (FINISH_TASK_NAME, END) not in edges

    def test_conditional_edge_destinations_match_enabled_disabled(self) -> None:
        """The should_continue conditional edge's destination set (path_map) is
        the routing contract: select_tools appears iff retrieve is enabled, and
        end_graph_hooks iff hooks are configured."""

        def my_func(query: str = "") -> list[str]:
            """Retrieve tools."""
            return []

        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        disabled = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        disabled_ends = set(disabled.branches["agent"]["should_continue"].ends)  # type: ignore[attr-defined]
        assert disabled_ends == {"tools", FINISH_TASK_NAME, "reject_unbound_tools", END}

        enabled_with_hooks = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            retrieve_tools_function=my_func,
            end_graph_hooks=[hook],
        )
        ends = set(enabled_with_hooks.branches["agent"]["should_continue"].ends)  # type: ignore[attr-defined]
        assert ends == {
            "select_tools",
            "tools",
            FINISH_TASK_NAME,
            "reject_unbound_tools",
            "end_graph_hooks",
            END,
        }

    def test_select_tools_node_exposes_sync_func_when_function_provided(self) -> None:
        """A retrieve_tools_function wires a callable sync select_tools.func; a
        coroutine-only config wires no sync func (func is None)."""

        def f(query: str = "") -> list[str]:
            """Retrieve tools."""
            return []

        async def c(query: str = "") -> list[str]:
            """Retrieve tools."""
            return []

        fn_only = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), retrieve_tools_function=f
        )
        coro_only = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), retrieve_tools_coroutine=c
        )
        both = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            retrieve_tools_function=f,
            retrieve_tools_coroutine=c,
        )

        # fn-only and both expose a runnable sync func; coro-only does not.
        assert fn_only.nodes["select_tools"].runnable.func is not None  # type: ignore[union-attr]
        assert both.nodes["select_tools"].runnable.func is not None  # type: ignore[union-attr]
        assert coro_only.nodes["select_tools"].runnable.func is None  # type: ignore[union-attr]
        # all three expose an async path.
        assert coro_only.nodes["select_tools"].runnable.afunc is not None  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Middleware tool extraction
# ---------------------------------------------------------------------------


class TestMiddlewareToolExtraction:
    @pytest.mark.asyncio
    async def test_non_basetool_middleware_entries_excluded_from_binding(self) -> None:
        """Only BaseTool middleware tools reach bind_tools; strings/ints dropped.

        Uses a plain MagicMock middleware (no wrap_model_call override) so the
        real MiddlewareExecutor takes the direct-ainvoke path and bind_tools is
        exercised with the actual extracted tool set.
        """
        llm = _make_llm()
        mw = MagicMock()
        mw.tools = [dummy_tool_b, "not_a_tool", 123]

        builder = create_agent(
            llm, _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True, middleware=[mw]
        )
        await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())

        names = _bound_tool_names(llm)
        assert names == ["dummy_tool_b"]  # only the BaseTool survived

    @pytest.mark.asyncio
    async def test_middleware_without_tools_attr_binds_no_extra_tools(self) -> None:
        llm = _make_llm()
        mw = MagicMock(spec=[])  # no `tools` attribute -> getattr default []

        builder = create_agent(
            llm, _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True, middleware=[mw]
        )
        await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())

        assert _bound_tool_names(llm) == []


# ---------------------------------------------------------------------------
# call_model (sync)
# ---------------------------------------------------------------------------


class TestCallModelSync:
    def test_raises_runtime_error_when_middleware_configured(self) -> None:
        mw = MagicMock()
        mw.tools = []
        builder = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        with pytest.raises(RuntimeError, match="sync execution was requested"):
            _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())

    def test_invokes_bound_model_with_state_messages_and_returns_response(self) -> None:
        msg = AIMessage(content="user said hi")
        llm = _make_llm(response=AIMessage(content="model reply"))
        builder = create_agent(llm, _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True)

        state = _make_state(messages=[msg])
        result = _agent_fn(builder)(state, _make_config(), store=MagicMock())

        llm._bound.invoke.assert_called_once_with([msg])
        assert result == {"messages": [llm._bound.invoke.return_value]}
        assert result["messages"][0].content == "model reply"

    def test_applies_configurable_model_config_to_llm(self) -> None:
        """The configurable block from config is forwarded to llm.with_config so
        the runtime model/provider override takes effect (the whole reason this
        override exists)."""
        llm = _make_llm()
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        config = _make_config(model_name="gemini-2.0", provider="google")
        _agent_fn(builder)(_make_state(), config, store=MagicMock())

        llm.with_config.assert_called_once_with(
            configurable={"model_name": "gemini-2.0", "provider": "google"}
        )

    def test_binds_selected_initial_and_default_retrieve_tools(self) -> None:
        llm = _make_llm()
        builder = create_agent(
            llm,
            _make_tool_registry(dummy_tool_a, dummy_tool_b),
            initial_tool_ids=["dummy_tool_b"],
        )

        state = _make_state(selected_tool_ids=["dummy_tool_a"])
        _agent_fn(builder)(state, _make_config(), store=MagicMock())

        names = _bound_tool_names(llm)
        assert "dummy_tool_a" in names  # selected
        assert "dummy_tool_b" in names  # initial
        assert any(n.startswith("retrieve") for n in names)  # default retrieve tool

    def test_empty_response_gets_sentinel_content(self) -> None:
        llm = _make_llm(response=AIMessage(content="", tool_calls=[]))
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        result = _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "Empty response from model."

    def test_nonempty_response_not_overwritten(self) -> None:
        llm = _make_llm(response=AIMessage(content="real content"))
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        result = _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "real content"

    def test_comms_agent_appends_breaker(self) -> None:
        llm = _make_llm(response=AIMessage(content="body"))
        builder = create_agent(
            llm, _make_tool_registry(), disable_retrieve_tools=True, agent_name="comms_agent"
        )

        result = _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "body" + NEW_MESSAGE_BREAKER

    def test_non_comms_agent_does_not_append_breaker(self) -> None:
        llm = _make_llm(response=AIMessage(content="body"))
        builder = create_agent(
            llm, _make_tool_registry(), disable_retrieve_tools=True, agent_name="executor_agent"
        )

        result = _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "body"

    def test_default_agent_name_does_not_append_breaker(self) -> None:
        # Default agent_name is "main_agent" (not comms_agent) -> no breaker.
        llm = _make_llm(response=AIMessage(content="body"))
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        result = _agent_fn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "body"


# ---------------------------------------------------------------------------
# acall_model (async)
# ---------------------------------------------------------------------------


class TestAcallModelAsync:
    @pytest.mark.asyncio
    async def test_direct_path_invokes_ainvoke_with_state_messages(self) -> None:
        msg = AIMessage(content="prompt")
        llm = _make_llm(response=AIMessage(content="reply"))
        builder = create_agent(llm, _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True)

        state = _make_state(messages=[msg])
        result = await _agent_afn(builder)(state, _make_config(), store=MagicMock())

        llm._bound.ainvoke.assert_awaited_once_with([msg])
        assert result["messages"][0].content == "reply"

    @pytest.mark.asyncio
    async def test_applies_configurable_model_config_to_llm(self) -> None:
        llm = _make_llm()
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        config = _make_config(model_name="gpt-5", provider="openai")
        await _agent_afn(builder)(_make_state(), config, store=MagicMock())

        llm.with_config.assert_called_once_with(
            configurable={"model_name": "gpt-5", "provider": "openai"}
        )

    @pytest.mark.asyncio
    async def test_empty_response_gets_sentinel(self) -> None:
        llm = _make_llm(response=AIMessage(content="", tool_calls=[]))
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        result = await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "Empty response from model."

    @pytest.mark.asyncio
    async def test_comms_agent_appends_breaker(self) -> None:
        llm = _make_llm(response=AIMessage(content="body"))
        builder = create_agent(
            llm, _make_tool_registry(), disable_retrieve_tools=True, agent_name="comms_agent"
        )

        result = await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "body" + NEW_MESSAGE_BREAKER

    @pytest.mark.asyncio
    async def test_non_comms_agent_does_not_append_breaker(self) -> None:
        llm = _make_llm(response=AIMessage(content="body"))
        builder = create_agent(
            llm, _make_tool_registry(), disable_retrieve_tools=True, agent_name="executor_agent"
        )

        result = await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())
        assert result["messages"][0].content == "body"

    @pytest.mark.asyncio
    async def test_pre_model_hook_runs_before_invocation(self) -> None:
        """pre_model_hooks output feeds the model: a hook that replaces the
        messages must change what gets sent to ainvoke."""
        injected = AIMessage(content="injected by hook")

        async def hook(state: Any, config: Any, store: Any) -> Any:
            new = dict(state)
            new["messages"] = [injected]
            return new

        llm = _make_llm(response=AIMessage(content="r"))
        builder = create_agent(
            llm, _make_tool_registry(), disable_retrieve_tools=True, pre_model_hooks=[hook]
        )

        await _agent_afn(builder)(_make_state(messages=[]), _make_config(), store=MagicMock())
        llm._bound.ainvoke.assert_awaited_once_with([injected])

    @pytest.mark.asyncio
    async def test_after_model_receives_appended_messages_and_extra_keys_surface(self) -> None:
        """after_model sees the prior messages WITH the new response appended,
        and the keys it adds (e.g. todos) surface in the partial update while
        base channels (selected_tool_ids) are EXCLUDED so the messages
        append-reducer is not clobbered."""
        mw = MagicMock()
        mw.tools = []
        prior = AIMessage(content="prior turn")
        new_todos = [{"id": "t1", "content": "do it"}]
        seen_messages: list = []

        async def fake_after(state: Any, config: Any, store: Any) -> Any:
            seen_messages.extend(state["messages"])
            updated = dict(state)
            updated["todos"] = new_todos
            updated["selected_tool_ids"] = ["should_be_filtered"]
            return updated

        with patch("app.override.langgraph_bigtool.create_agent.MiddlewareExecutor") as me_cls:
            me = MagicMock()
            me.execute_before_model = AsyncMock(side_effect=lambda s, c, st: s)
            me.has_wrap_model_call = MagicMock(return_value=False)
            me.execute_after_model = AsyncMock(side_effect=fake_after)
            me_cls.return_value = me

            llm = _make_llm(response=AIMessage(content="r"))
            builder = create_agent(
                llm, _make_tool_registry(), disable_retrieve_tools=True, middleware=[mw]
            )
            result = await _agent_afn(builder)(
                _make_state(messages=[prior]), _make_config(), store=MagicMock()
            )

        # after_model got the prior message + the new response appended.
        assert [m.content for m in seen_messages] == ["prior turn", "r"]
        assert result["todos"] == new_todos
        assert "selected_tool_ids" not in result  # base key excluded
        assert result["messages"][0].content == "r"  # only the new response returned

    @pytest.mark.asyncio
    async def test_wrap_model_call_path_used_when_has_wrap_model_call(self) -> None:
        """When middleware advertises wrap_model_call, the response comes from
        wrap_model_invocation, NOT a direct ainvoke."""
        mw = MagicMock()
        mw.tools = []
        wrapped_resp = AIMessage(content="from wrap")

        with patch("app.override.langgraph_bigtool.create_agent.MiddlewareExecutor") as me_cls:
            me = MagicMock()
            me.execute_before_model = AsyncMock(side_effect=lambda s, c, st: s)
            me.has_wrap_model_call = MagicMock(return_value=True)
            me.wrap_model_invocation = AsyncMock(return_value=wrapped_resp)
            me.execute_after_model = AsyncMock(side_effect=lambda s, c, st: s)
            me_cls.return_value = me

            llm = _make_llm(response=AIMessage(content="direct"))
            builder = create_agent(
                llm, _make_tool_registry(), disable_retrieve_tools=True, middleware=[mw]
            )
            result = await _agent_afn(builder)(_make_state(), _make_config(), store=MagicMock())

        me.wrap_model_invocation.assert_awaited_once()
        llm._bound.ainvoke.assert_not_awaited()
        assert result["messages"][0].content == "from wrap"

    @pytest.mark.asyncio
    async def test_log_preview_does_not_break_invocation(self) -> None:
        """The best-effort message-preview logging must never affect the model
        call: a very long message still results in exactly one ainvoke and a
        normal return. (Pins the observable effect of the log block, whose
        internal truncation arithmetic is equivalent-mutant territory.)"""
        long_msg = AIMessage(content="x" * 5000)
        llm = _make_llm(response=AIMessage(content="ok"))
        builder = create_agent(llm, _make_tool_registry(), disable_retrieve_tools=True)

        result = await _agent_afn(builder)(
            _make_state(messages=[long_msg]), _make_config(), store=MagicMock()
        )
        llm._bound.ainvoke.assert_awaited_once_with([long_msg])
        assert result["messages"][0].content == "ok"


# ---------------------------------------------------------------------------
# select_tools / aselect_tools
# ---------------------------------------------------------------------------


class TestSelectTools:
    def _build(self, func=None, coro=None) -> StateGraph:
        kwargs: dict[str, Any] = {}
        if func is not None:
            kwargs["retrieve_tools_function"] = func
        if coro is not None:
            kwargs["retrieve_tools_coroutine"] = coro
        return create_agent(_make_llm(), _make_tool_registry(dummy_tool_a), **kwargs)

    def _select_fn(self, builder: StateGraph):
        return builder.nodes["select_tools"].runnable.func  # type: ignore[union-attr]

    def _aselect_fn(self, builder: StateGraph):
        return builder.nodes["select_tools"].runnable.afunc  # type: ignore[union-attr]

    def test_dict_result_splits_bind_and_response_channels(self) -> None:
        """A dict result drives selected_tool_ids from 'tools_to_bind' and the
        visible message from 'response' — they are distinct channels."""

        def my_func(query: str = "") -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_b"]}

        builder = self._build(func=my_func)
        result = self._select_fn(builder)(
            [{"id": "tc1", "args": {"query": "x"}}], _make_config(), store=MagicMock()
        )
        # binding comes from tools_to_bind
        assert result["selected_tool_ids"] == ["dummy_tool_a"]
        # the human-visible ToolMessage lists the 'response' channel, not bind
        assert len(result["messages"]) == 1
        assert "dummy_tool_b" in result["messages"][0].content
        assert "dummy_tool_a" not in result["messages"][0].content

    def test_list_result_binds_tool_id(self) -> None:
        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = self._build(func=my_func)
        result = self._select_fn(builder)(
            [{"id": "tc1", "args": {}}], _make_config(), store=MagicMock()
        )
        assert "dummy_tool_a" in result["selected_tool_ids"]

    def test_subagent_prefixed_ids_dropped_from_binding(self) -> None:
        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a", "subagent:gmail"]

        builder = self._build(func=my_func)
        result = self._select_fn(builder)(
            [{"id": "tc1", "args": {}}], _make_config(), store=MagicMock()
        )
        assert result["selected_tool_ids"] == ["dummy_tool_a"]
        assert "subagent:gmail" not in result["selected_tool_ids"]

    def test_user_id_injected_into_retrieve_args(self) -> None:
        # Explicit params so the StructuredTool schema passes query/user_id
        # through to the function (a **kwargs-only schema would strip them).
        seen: dict[str, Any] = {}

        def retrieve(query: str = "", user_id: str = "", store: Any = None) -> list:
            """Retrieve tools."""
            seen["query"] = query
            seen["user_id"] = user_id
            return ["dummy_tool_a"]

        builder = self._build(func=retrieve)
        self._select_fn(builder)(
            [{"id": "tc1", "args": {"query": "q"}}],
            _make_config(user_id="user-42"),
            store=MagicMock(),
        )
        assert seen["user_id"] == "user-42"
        assert seen["query"] == "q"

    def test_no_user_id_when_absent_from_config(self) -> None:
        seen: dict[str, Any] = {}

        def retrieve(query: str = "", user_id: str = "SENTINEL", store: Any = None) -> list:
            """Retrieve tools."""
            seen["user_id"] = user_id
            return ["dummy_tool_a"]

        builder = self._build(func=retrieve)
        self._select_fn(builder)(
            [{"id": "tc1", "args": {"query": "q"}}], _make_config(), store=MagicMock()
        )
        # No user_id in config -> the injection line is skipped, so the
        # function keeps its default rather than receiving an injected value.
        assert seen["user_id"] == "SENTINEL"

    @pytest.mark.asyncio
    async def test_async_list_result_binds_tool_id(self) -> None:
        async def my_coro(query: str = "") -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = self._build(coro=my_coro)
        result = await self._aselect_fn(builder)(
            [{"id": "tc1", "args": {}}], _make_config(), store=MagicMock()
        )
        assert "dummy_tool_a" in result["selected_tool_ids"]

    @pytest.mark.asyncio
    async def test_async_dict_result_splits_bind_and_response_and_drops_subagent(self) -> None:
        async def my_coro(query: str = "") -> dict:
            """Retrieve tools."""
            return {
                "tools_to_bind": ["dummy_tool_a", "subagent:cal"],
                "response": ["dummy_tool_b"],
            }

        builder = self._build(coro=my_coro)
        result = await self._aselect_fn(builder)(
            [{"id": "tc1", "args": {}}], _make_config(), store=MagicMock()
        )
        # subagent: dropped from binding; bind comes from tools_to_bind
        assert result["selected_tool_ids"] == ["dummy_tool_a"]
        # the visible message reflects the distinct 'response' channel
        assert "dummy_tool_b" in result["messages"][0].content
        # async result carries exactly the two graph channels
        assert set(result) == {"messages", "selected_tool_ids"}

    @pytest.mark.asyncio
    async def test_async_user_id_injected_into_retrieve_args(self) -> None:
        seen: dict[str, Any] = {}

        async def retrieve(query: str = "", user_id: str = "", store: Any = None) -> list:
            """Retrieve tools."""
            seen["query"] = query
            seen["user_id"] = user_id
            return ["dummy_tool_a"]

        builder = self._build(coro=retrieve)
        await self._aselect_fn(builder)(
            [{"id": "tc1", "args": {"query": "qq"}}],
            _make_config(user_id="u-async"),
            store=MagicMock(),
        )
        assert seen["user_id"] == "u-async"
        assert seen["query"] == "qq"


# ---------------------------------------------------------------------------
# should_continue routing
# ---------------------------------------------------------------------------


class TestShouldContinue:
    def test_no_tool_calls_returns_end(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = _should_continue(builder)(
            _make_state(messages=[AIMessage(content="done")]), store=MagicMock()
        )
        assert result == END

    def test_no_tool_calls_returns_end_graph_hooks_when_configured(self) -> None:
        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            _make_llm(), _make_tool_registry(), disable_retrieve_tools=True, end_graph_hooks=[hook]
        )
        result = _should_continue(builder)(
            _make_state(messages=[AIMessage(content="done")]), store=MagicMock()
        )
        assert result == "end_graph_hooks"

    def test_non_ai_message_returns_end(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = _should_continue(builder)(
            _make_state(messages=[ToolMessage(content="t", tool_call_id="1")]),
            store=MagicMock(),
        )
        assert result == END

    def test_finish_task_call_routes_to_finish_task_node(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "f1", "name": FINISH_TASK_NAME, "args": {"result": "x"}}],
        )
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())
        assert isinstance(result, Send)
        assert result.node == FINISH_TASK_NAME

    def test_finish_task_takes_priority_over_other_calls(self) -> None:
        """finish_task short-circuits: even mixed with a bound call it returns the
        single finish Send and ignores the rest."""
        builder = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(
            content="",
            tool_calls=[
                {"id": "a", "name": "dummy_tool_a", "args": {}},
                {"id": "f1", "name": FINISH_TASK_NAME, "args": {}},
            ],
        )
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())
        assert isinstance(result, Send)
        assert result.node == FINISH_TASK_NAME

    def test_retrieve_tools_call_routes_to_select_tools(self) -> None:
        # The StructuredTool name equals the function name; naming it
        # retrieve_tools makes the call name match retrieve_tools.name.
        def retrieve_tools(query: str = "") -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), retrieve_tools_function=retrieve_tools
        )
        msg = AIMessage(
            content="",
            tool_calls=[{"id": "r1", "name": "retrieve_tools", "args": {}}],
        )
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())
        assert any(getattr(s, "node", None) == "select_tools" for s in result)

    def test_initial_bound_tool_call_routes_to_tools(self) -> None:
        builder = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "dummy_tool_a", "args": {}}])
        state = _make_state(messages=[msg], todos=[{"id": "x"}])
        result = _should_continue(builder)(state, store=MagicMock())
        assert len(result) == 1
        send = result[0]
        assert send.node == "tools"
        # Tool calls are wrapped in a ToolCallWithContext carrying the full
        # state so the ToolNode can inject InjectedState (e.g. "todos").
        assert send.arg["__type"] == "tool_call_with_context"
        assert send.arg["tool_call"]["name"] == "dummy_tool_a"
        assert send.arg["state"]["todos"] == [{"id": "x"}]

    def test_selected_tool_call_routes_to_tools(self) -> None:
        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True
        )
        msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "dummy_tool_a", "args": {}}])
        # dummy_tool_a is bound only because it is in selected_tool_ids
        result = _should_continue(builder)(
            _make_state(messages=[msg], selected_tool_ids=["dummy_tool_a"]), store=MagicMock()
        )
        assert result[0].node == "tools"

    def test_unbound_tool_call_routes_to_reject_not_tools(self) -> None:
        builder = create_agent(
            _make_llm(), _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True
        )
        msg = AIMessage(
            content="", tool_calls=[{"id": "tc1", "name": "totally_unknown", "args": {}}]
        )
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())
        assert any(getattr(s, "node", None) == "reject_unbound_tools" for s in result)
        assert not any(getattr(s, "node", None) == "tools" for s in result)

    def test_hyphenated_call_rewritten_to_canonical_bound_name(self) -> None:
        """An LLM that echoes an underscored name for a hyphenated bound tool is
        rewritten to the canonical name and routed to tools, not rejected."""

        @tool
        def hyphen_tool(query: str) -> str:
            """Tool with a hyphenated name."""
            return "x"

        hyphen_tool.name = "my-mcp-tool"
        registry = {"my-mcp-tool": hyphen_tool}

        builder = create_agent(
            _make_llm(), registry, disable_retrieve_tools=True, initial_tool_ids=["my-mcp-tool"]
        )
        # LLM echoes the name with underscores.
        msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "my_mcp_tool", "args": {}}])
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())

        # Routed to tools (rewritten to canonical), not rejected. The Send to
        # "tools" carries the rewritten canonical tool name in its payload.
        tools_sends = [s for s in result if getattr(s, "node", None) == "tools"]
        assert len(tools_sends) == 1
        assert not any(getattr(s, "node", None) == "reject_unbound_tools" for s in result)
        assert tools_sends[0].arg["tool_call"]["name"] == "my-mcp-tool"

    def test_canonical_rewrite_maps_hyphens_to_underscores_exactly(self) -> None:
        """The canonical lookup replaces '-' with '_' (not with ''): a bound tool
        named with underscores is matched when the LLM calls it with hyphens."""

        @tool
        def under_tool(query: str) -> str:
            """Underscore-named tool."""
            return "x"

        under_tool.name = "my_under_tool"
        registry = {"my_under_tool": under_tool}

        builder = create_agent(
            _make_llm(), registry, disable_retrieve_tools=True, initial_tool_ids=["my_under_tool"]
        )
        # LLM calls it with hyphens.
        msg = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "my-under-tool", "args": {}}])
        result = _should_continue(builder)(_make_state(messages=[msg]), store=MagicMock())

        tools_sends = [s for s in result if getattr(s, "node", None) == "tools"]
        assert len(tools_sends) == 1
        assert tools_sends[0].arg["tool_call"]["name"] == "my_under_tool"


# ---------------------------------------------------------------------------
# reject_unbound_tools
# ---------------------------------------------------------------------------


class TestRejectUnboundTools:
    def _reject(self, builder: StateGraph):
        return builder.nodes["reject_unbound_tools"].runnable.func  # type: ignore[union-attr]

    def _areject(self, builder: StateGraph):
        return builder.nodes["reject_unbound_tools"].runnable.afunc  # type: ignore[union-attr]

    def test_error_message_names_the_unbound_tool(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = self._reject(builder)([{"id": "tc1", "name": "missing_tool"}], store=MagicMock())

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.name == "missing_tool"
        assert msg.tool_call_id == "tc1"
        # Full remediation contract the model relies on to recover.
        assert msg.content == (
            "Tool 'missing_tool' is not bound. "
            "You must call retrieve_tools(exact_tool_names=['missing_tool']) "
            "to bind it before calling it."
        )

    def test_one_message_per_call(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = self._reject(builder)(
            [{"id": "a", "name": "t1"}, {"id": "b", "name": "t2"}], store=MagicMock()
        )
        assert [m.name for m in result["messages"]] == ["t1", "t2"]

    @pytest.mark.asyncio
    async def test_async_delegates_to_sync(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = await self._areject(builder)(
            [{"id": "tc1", "name": "missing_tool"}], store=MagicMock()
        )
        assert result["messages"][0].name == "missing_tool"
        assert "not bound" in result["messages"][0].content


# ---------------------------------------------------------------------------
# finish_task_node
# ---------------------------------------------------------------------------


class TestFinishTaskNode:
    def _finish(self, builder: StateGraph):
        return builder.nodes[FINISH_TASK_NAME].runnable.func  # type: ignore[union-attr]

    def _afinish(self, builder: StateGraph):
        return builder.nodes[FINISH_TASK_NAME].runnable.afunc  # type: ignore[union-attr]

    def test_result_payload_becomes_message_content(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = self._finish(builder)(
            [{"id": "f1", "name": FINISH_TASK_NAME, "args": {"result": "all done"}}],
            store=MagicMock(),
        )
        msg = result["messages"][0]
        assert msg.content == "all done"
        assert msg.name == FINISH_TASK_NAME
        assert msg.tool_call_id == "f1"

    def test_missing_result_uses_default_content(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = self._finish(builder)(
            [{"id": "f1", "name": FINISH_TASK_NAME, "args": {}}], store=MagicMock()
        )
        assert result["messages"][0].content == "Task completed."

    def test_non_string_result_is_stringified(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = self._finish(builder)(
            [{"id": "f1", "name": FINISH_TASK_NAME, "args": {"result": {"k": 1}}}],
            store=MagicMock(),
        )
        assert result["messages"][0].content == str({"k": 1})

    @pytest.mark.asyncio
    async def test_async_delegates_to_sync(self) -> None:
        builder = create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)
        result = await self._afinish(builder)(
            [{"id": "f1", "name": FINISH_TASK_NAME, "args": {"result": "ok"}}], store=MagicMock()
        )
        assert result["messages"][0].content == "ok"


# ---------------------------------------------------------------------------
# end_graph_hooks node
# ---------------------------------------------------------------------------


class TestEndGraphHooksNode:
    def _build(self, hook):
        return create_agent(
            _make_llm(), _make_tool_registry(), disable_retrieve_tools=True, end_graph_hooks=[hook]
        )

    def test_sync_node_runs_hook_and_returns_its_state(self) -> None:
        def hook(state: Any, config: Any, store: Any) -> Any:
            new = dict(state)
            new["touched"] = "by_hook"
            return new

        builder = self._build(hook)
        node = builder.nodes["end_graph_hooks"].runnable  # type: ignore[union-attr]
        result = node.func(_make_state(), _make_config(), store=MagicMock())
        assert result["touched"] == "by_hook"

    @pytest.mark.asyncio
    async def test_async_node_runs_hook_and_returns_its_state(self) -> None:
        async def hook(state: Any, config: Any, store: Any) -> Any:
            new = dict(state)
            new["touched"] = "by_async_hook"
            return new

        builder = self._build(hook)
        node = builder.nodes["end_graph_hooks"].runnable  # type: ignore[union-attr]
        result = await node.afunc(_make_state(), _make_config(), store=MagicMock())
        assert result["touched"] == "by_async_hook"
