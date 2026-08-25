"""Tests for app.override.langgraph_bigtool.create_agent."""

from collections.abc import Sequence
from typing import Any, Protocol, cast
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.graph import StateGraph
from langgraph.store.base import BaseStore
import pytest

from app.agents.llm import lane as lane_module
from app.agents.llm.lane import ModelLane
from app.agents.llm.types import LLMProviderName
from app.constants.llm import (
    DEFAULT_MAX_TOKENS,
    LANE_FIELD_ID,
    RECURSION_WRAPUP_THRESHOLD_STEPS,
)
from app.models.agent_models import AgentConfigurable
from app.override.langgraph_bigtool.create_agent import (
    _agent_sticky_key,
    _bind_session_id,
    _fallback_config,
    _prepare_fallback,
    create_agent,
)
from app.override.langgraph_bigtool.utils import State

# ---------------------------------------------------------------------------
# Helpers
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


def _make_llm() -> MagicMock:
    llm = MagicMock()
    configured = MagicMock()
    bound = MagicMock()
    bound.invoke.return_value = AIMessage(content="hello")
    bound.ainvoke = AsyncMock(return_value=AIMessage(content="hello"))
    # ainvoke_llm/invoke_llm wrap the bound model in with_llm_retry first.
    bound.with_retry.return_value = bound
    configured.bind_tools.return_value = bound
    llm.with_config.return_value = configured
    return llm


def _make_config(**configurable: Any) -> RunnableConfig:
    return {"configurable": configurable}


class _ModelNode(Protocol):
    """The two entry points the agent node exposes, named locally.

    LangGraph types ``node.runnable`` as a union that does not statically carry
    ``func`` / ``afunc``, and ``RunnableCallable`` is not an explicitly exported
    symbol. Naming only what is used here keeps the tests off a private import.
    """

    def func(self, state: State, config: RunnableConfig, *, store: BaseStore) -> State: ...

    async def afunc(self, state: State, config: RunnableConfig, *, store: BaseStore) -> State: ...


def _agent_runnable(builder: StateGraph) -> _ModelNode:
    """The agent node's runnable — what actually calls the model."""
    return cast(_ModelNode, builder.nodes["agent"].runnable)


def _make_state(
    messages: Sequence[AnyMessage] | None = None,
    selected_tool_ids: Sequence[str] | None = None,
    todos: Sequence[dict[str, Any]] | None = None,
    remaining_steps: int = RECURSION_WRAPUP_THRESHOLD_STEPS + 1,
) -> State:
    """A complete ``State`` — every channel the node's signature promises.

    ``remaining_steps`` defaults just clear of the wrap-up threshold so the
    recursion notice stays out of these tests; pass a lower value to exercise
    it.
    """
    # cast, like _maybe_inject_wrapup in the module under test: langgraph_bigtool
    # ships no py.typed, so its State base resolves to Any and mypy sees an
    # ordinary class rather than a TypedDict a literal could satisfy.
    return cast(
        "State",
        {
            "messages": list(messages or []),
            "selected_tool_ids": list(selected_tool_ids or []),
            "todos": list(todos or []),
            "intent": None,
            "integration_usernames": {},
            "remaining_steps": remaining_steps,
        },
    )


# ---------------------------------------------------------------------------
# create_agent — basic construction
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_returns_state_graph(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        assert isinstance(builder, StateGraph)

    def test_the_runtime_context_schema_reaches_the_graph(self) -> None:
        """Runtime context (the per-run config the tiers read) only arrives if
        the schema is declared on the StateGraph — dropped, every node sees an
        empty context and nothing raises to say so."""
        from dataclasses import dataclass

        @dataclass
        class _Ctx:
            tenant: str

        builder = create_agent(
            _make_llm(),
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            context_schema=_Ctx,
        )

        assert builder.context_schema is _Ctx

    def test_with_retrieve_tools_coroutine(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coroutine(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_coroutine=my_coroutine,
        )

        assert isinstance(builder, StateGraph)

    def test_with_retrieve_tools_function(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_function=my_func,
        )

        assert isinstance(builder, StateGraph)

    def test_with_both_retrieve_tools(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        async def my_coroutine(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_function=my_func,
            retrieve_tools_coroutine=my_coroutine,
        )

        assert isinstance(builder, StateGraph)

    def test_with_initial_tool_ids(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a, dummy_tool_b)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )

        assert isinstance(builder, StateGraph)

    def test_with_end_graph_hooks(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[my_hook],
        )

        assert isinstance(builder, StateGraph)

    def test_with_middleware(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        mw = MagicMock()
        mw.tools = [dummy_tool_a]

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        assert isinstance(builder, StateGraph)

    def test_middleware_non_basetool_filtered(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        mw = MagicMock()
        mw.tools = [dummy_tool_a, "not_a_tool"]  # non-BaseTool filtered

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        assert isinstance(builder, StateGraph)

    def test_middleware_without_tools_attr(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        mw = MagicMock(spec=[])  # no tools attribute

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        assert isinstance(builder, StateGraph)


# ---------------------------------------------------------------------------
# Inner function tests via graph node extraction
# ---------------------------------------------------------------------------


class TestCallModel:
    """Test the call_model inner function behavior indirectly."""

    def test_sync_call_model_raises_with_middleware(self) -> None:
        """When middleware is configured, sync call_model should raise RuntimeError."""

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = []

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        with pytest.raises(RuntimeError, match="sync execution was requested"):
            agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime

    def test_sync_call_model_without_middleware(self) -> None:
        """Sync call_model should work without middleware."""

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "messages" in result
        # The model must be bound to exactly the initial tool set — binding None
        # or a wrong list silently produces an agent that cannot call anything.
        llm.with_config.return_value.bind_tools.assert_called_once_with([dummy_tool_a])

    @pytest.mark.asyncio
    async def test_after_model_keys_flow_back_but_base_state_does_not(self) -> None:
        """Keys added by after_model hooks flow back to the graph, but the base
        state's own keys do not — messages use an append reducer, so echoing the
        full history would duplicate every earlier turn in the checkpoint."""
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry()

        mw = MagicMock()
        mw.tools = []
        history = [HumanMessage("hi")]
        after_state = {
            "messages": [*history, AIMessage(content="hello")],
            "selected_tool_ids": ["tool-a"],
            "todos": [{"id": "t1"}],
            "enriched": {"by": "after_model_hook"},
        }

        with patch("app.override.langgraph_bigtool.create_agent.MiddlewareExecutor") as mock_me_cls:
            mock_me = MagicMock()
            mock_me.execute_before_model = AsyncMock(return_value=_make_state(history))
            mock_me.has_wrap_model_call = MagicMock(return_value=False)
            mock_me.execute_after_model = AsyncMock(return_value=after_state)
            mock_me_cls.return_value = mock_me

            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )
            agent_node = builder.nodes["agent"]
            result = await agent_node.runnable.afunc(  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
                _make_state(), _make_config(), store=MagicMock()
            )

        # Only the new response rides the append reducer — not the full list.
        assert [m.content for m in result["messages"]] == ["hello"]
        # Hook-added keys flow back; the base state's own keys do not.
        assert result["todos"] == [{"id": "t1"}]
        assert result["enriched"] == {"by": "after_model_hook"}
        assert "selected_tool_ids" not in result

    def test_sync_call_model_empty_response_gets_default(self) -> None:
        """Empty model response should get default content."""

        empty_response = AIMessage(content="", tool_calls=[])
        llm = MagicMock()
        configured = MagicMock()
        bound = MagicMock()
        bound.invoke.return_value = empty_response
        bound.with_retry.return_value = bound
        configured.bind_tools.return_value = bound
        llm.with_config.return_value = configured

        registry = _make_tool_registry()
        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert result["messages"][0].content == "Empty response from model."

    def test_sync_call_model_comms_agent_appends_breaker(self) -> None:
        """comms_agent should append NEW_MESSAGE_BREAKER."""
        from app.constants.general import NEW_MESSAGE_BREAKER

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert result["messages"][0].content.endswith(NEW_MESSAGE_BREAKER)


class TestAcallModel:
    @pytest.mark.asyncio
    async def test_acall_model_basic(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = await agent_node.runnable.afunc(state, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_acall_model_with_middleware_hooks(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry()

        mw = MagicMock()
        mw.tools = []

        with patch("app.override.langgraph_bigtool.create_agent.MiddlewareExecutor") as mock_me_cls:
            mock_me = MagicMock()
            mock_me.execute_before_model = AsyncMock(return_value=_make_state())
            mock_me.has_wrap_model_call = MagicMock(return_value=False)
            mock_me.execute_after_model = AsyncMock(return_value=_make_state())
            mock_me_cls.return_value = mock_me

            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )
            agent_node = builder.nodes["agent"]
            state = _make_state()
            result = await agent_node.runnable.afunc(  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
                state, _make_config(), store=MagicMock()
            )
            assert "messages" in result

    @pytest.mark.asyncio
    async def test_acall_model_empty_response(self) -> None:
        empty_response = AIMessage(content="", tool_calls=[])
        llm = MagicMock()
        configured = MagicMock()
        bound = MagicMock()
        bound.ainvoke = AsyncMock(return_value=empty_response)
        bound.with_retry.return_value = bound
        configured.bind_tools.return_value = bound
        llm.with_config.return_value = configured

        registry = _make_tool_registry()
        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        result = await agent_node.runnable.afunc(  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
            state, _make_config(), store=MagicMock()
        )
        assert result["messages"][0].content == "Empty response from model."

    @pytest.mark.asyncio
    async def test_acall_model_comms_agent_appends_breaker(self) -> None:
        from app.constants.general import NEW_MESSAGE_BREAKER

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        agent_node = builder.nodes["agent"]
        state = _make_state()
        result = await agent_node.runnable.afunc(  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
            state, _make_config(), store=MagicMock()
        )
        assert result["messages"][0].content.endswith(NEW_MESSAGE_BREAKER)


# ---------------------------------------------------------------------------
# should_continue
# ---------------------------------------------------------------------------


class TestShouldContinue:
    def test_no_tool_calls_returns_end(self) -> None:
        from langgraph.graph import END

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        msg = AIMessage(content="done")
        state = _make_state(messages=[msg])
        store = MagicMock()

        branch = builder.branches["agent"]["should_continue"]
        edge_fn = branch.path.func  # type: ignore[attr-defined]  # langgraph Runnable exposes .func only at runtime
        result = edge_fn(state, store=store)
        assert result == END

    def test_no_tool_calls_with_end_hooks(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry()

        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )

        msg = AIMessage(content="done")
        state = _make_state(messages=[msg])
        store = MagicMock()

        branch = builder.branches["agent"]["should_continue"]
        edge_fn = branch.path.func  # type: ignore[attr-defined]  # langgraph Runnable exposes .func only at runtime
        result = edge_fn(state, store=store)
        assert result == "end_graph_hooks"

    def test_bound_tool_calls_routed_to_tools(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )

        msg = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "dummy_tool_a", "args": {}}],
        )
        state = _make_state(messages=[msg])
        store = MagicMock()

        # One task per call, so a call that pauses for approval leaves its completed
        # siblings alone (LangGraph persists their writes — see
        # tests/unit/agents/test_pause_checkpointing.py).
        edge_fn = builder.branches["agent"]["should_continue"].path.func  # type: ignore[attr-defined]  # langgraph Runnable exposes .func only at runtime
        result = edge_fn(state, store=store)
        assert len(result) == 1
        assert result[0].node == "tools"
        assert result[0].arg["tool_call"]["name"] == "dummy_tool_a"

    def test_unbound_tool_calls_routed_to_reject(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        msg = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "unknown_tool", "args": {}}],
        )
        state = _make_state(messages=[msg])
        store = MagicMock()

        edge_fn = builder.branches["agent"]["should_continue"].path.func  # type: ignore[attr-defined]  # langgraph Runnable exposes .func only at runtime
        result = edge_fn(state, store=store)
        has_reject = any(getattr(s, "node", None) == "reject_unbound_tools" for s in result)
        assert has_reject


# ---------------------------------------------------------------------------
# reject_unbound_tools
# ---------------------------------------------------------------------------


class TestFinishTaskNode:
    """The finish_task node turns each finished tool call into a ToolMessage the
    model can read — under its own name, keyed as messages for the reducer."""

    @staticmethod
    def _builder():
        from app.override.langgraph_bigtool.create_agent import create_agent

        return create_agent(_make_llm(), _make_tool_registry(), disable_retrieve_tools=True)

    def test_reports_the_result_the_task_returned(self) -> None:
        from app.constants.general import FINISH_TASK_NAME

        node = self._builder().nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "done"}}]

        result = node.func(tool_calls, store=MagicMock())

        assert [m.content for m in result["messages"]] == ["done"]
        assert result["messages"][0].tool_call_id == "tc1"
        assert result["messages"][0].name == FINISH_TASK_NAME

    def test_a_missing_result_still_closes_the_call(self) -> None:
        from app.constants.general import FINISH_TASK_NAME

        node = self._builder().nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc2", "name": FINISH_TASK_NAME, "args": {}}]

        result = node.func(tool_calls, store=MagicMock())

        assert [m.content for m in result["messages"]] == ["Task completed."]
        assert result["messages"][0].tool_call_id == "tc2"

    @pytest.mark.asyncio
    async def test_async_twin_matches(self) -> None:
        from app.constants.general import FINISH_TASK_NAME

        node = self._builder().nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc3", "name": FINISH_TASK_NAME, "args": {"result": "async done"}}]

        result = await node.afunc(tool_calls, store=MagicMock())

        assert [m.content for m in result["messages"]] == ["async done"]


class TestRejectUnboundTools:
    def test_reject_unbound_tools_returns_error_messages(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        reject_node = builder.nodes["reject_unbound_tools"]
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]
        store = MagicMock()

        result = reject_node.runnable.func(tool_calls, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert len(result["messages"]) == 1
        assert "not bound" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_areject_unbound_tools(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        reject_node = builder.nodes["reject_unbound_tools"]
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]
        store = MagicMock()

        result = await reject_node.runnable.afunc(tool_calls, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert len(result["messages"]) == 1


# ---------------------------------------------------------------------------
# select_tools (sync + async)
# ---------------------------------------------------------------------------


class TestSelectTools:
    def test_select_tools_with_dict_result(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a"]}

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)  # type: ignore[arg-type]  # test stub returns a bare dict, not the declared RetrieveToolsResult union

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]
        config = _make_config()
        store = MagicMock()

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "messages" in result
        assert "selected_tool_ids" in result

    def test_select_tools_with_list_result(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {}}]
        config = _make_config()
        store = MagicMock()

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "dummy_tool_a" in result["selected_tool_ids"]

    def test_select_tools_filters_subagent_prefix(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a", "subagent:gmail"]

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {}}]
        config = _make_config(user_id="u1")
        store = MagicMock()

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        bind_ids = result["selected_tool_ids"]
        assert "subagent:gmail" not in bind_ids

    @pytest.mark.asyncio
    async def test_aselect_tools(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {}}]
        config = _make_config()
        store = MagicMock()

        result = await select_node.runnable.afunc(tool_calls, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "dummy_tool_a" in result["selected_tool_ids"]

    @pytest.mark.asyncio
    async def test_aselect_tools_dict_result(self) -> None:
        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a"]}

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)  # type: ignore[arg-type]  # test stub returns a bare dict, not the declared RetrieveToolsResult union

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {}}]
        config = _make_config()
        store = MagicMock()

        result = await select_node.runnable.afunc(tool_calls, config, store=store)  # type: ignore[union-attr]  # langgraph Runnable union exposes .func/.afunc only at runtime
        assert "dummy_tool_a" in result["selected_tool_ids"]


class TestBindSessionId:
    """The OpenRouter sticky-routing key, bound onto the tool-bound runnable.

    It pins a conversation to one upstream provider so the prompt cache chains
    across turns. Binding the wrong key, or silently not binding at all, costs
    the cache with nothing failing — so both halves are asserted here rather
    than through a graph run that would never notice either.
    """

    def test_a_configured_session_id_is_bound_onto_the_runnable(self) -> None:
        llm = MagicMock()
        bound = _bind_session_id(
            llm, {"provider": LLMProviderName.OPENROUTER, "session_id": "conv-1"}
        )

        llm.bind.assert_called_once_with(session_id="conv-1")
        assert bound is llm.bind.return_value

    def test_no_session_id_leaves_the_runnable_exactly_as_it_was(self) -> None:
        llm = MagicMock()
        bound = _bind_session_id(llm, {"provider": LLMProviderName.OPENROUTER})

        llm.bind.assert_not_called()
        assert bound is llm

    def test_an_empty_session_id_is_not_bound(self) -> None:
        # Binding "" would pin every conversation to the same routing key.

        llm = MagicMock()
        bound = _bind_session_id(llm, {"provider": LLMProviderName.OPENROUTER, "session_id": ""})

        llm.bind.assert_not_called()
        assert bound is llm

    @pytest.mark.parametrize("provider", [LLMProviderName.OPENROUTER, LLMProviderName.CUSTOM])
    def test_a_sticky_provider_gets_the_key(self, provider: LLMProviderName) -> None:
        llm = MagicMock()
        _bind_session_id(llm, {"provider": provider, "session_id": "conv-1"})

        llm.bind.assert_called_once_with(session_id="conv-1")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("agent", ["comms_agent", "executor_agent"])
    async def test_a_real_model_call_carries_the_agent_s_own_key(self, agent: str) -> None:
        """``_bind_session_id`` being correct is worth nothing if ``create_agent``
        does not hand it the agent's name. This drives the actual model node and
        reads the key that reached the runnable, so dropping the argument at the
        call site is caught rather than only the helper being right in isolation.
        """

        llm = _make_llm()
        bound = llm.with_config.return_value.bind_tools.return_value
        # Binding the session id returns a NEW runnable, and that is the one the
        # call is actually made on — so it has to stay the configured double.
        bound.bind.return_value = bound
        builder = create_agent(
            llm, _make_tool_registry(dummy_tool_a), disable_retrieve_tools=True, agent_name=agent
        )

        await _agent_runnable(builder).afunc(
            _make_state(messages=[HumanMessage(content="hi")]),
            _make_config(provider=LLMProviderName.OPENROUTER, session_id="conv-1"),
            store=MagicMock(),
        )

        assert bound.bind.call_args.kwargs["session_id"] == f"conv-1-{agent}"

    def test_the_sync_model_path_carries_the_agent_s_key_too(self) -> None:
        """There are two model call sites — sync and async — and they drift
        independently. The async one above is the production path; this one
        exists so a fix applied to only one of them is caught here rather than
        as an unexplained cache gap on whichever lane still runs sync."""

        llm = _make_llm()
        bound = llm.with_config.return_value.bind_tools.return_value
        bound.bind.return_value = bound
        builder = create_agent(
            llm,
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        _agent_runnable(builder).func(
            _make_state(messages=[HumanMessage(content="hi")]),
            _make_config(provider=LLMProviderName.OPENROUTER, session_id="conv-1"),
            store=MagicMock(),
        )

        assert bound.bind.call_args.kwargs["session_id"] == "conv-1-comms_agent"

    def test_each_agent_class_gets_its_own_key_on_the_same_conversation(self) -> None:
        """The fix this parameter exists for. comms, the executor and each
        subagent run inside ONE conversation but send completely different
        system prompts, so sharing the conversation's bare key put them all in
        one routing chain where they evicted each other. The key has to differ
        per agent, or the eviction comes straight back."""

        keys = []
        for agent in ("comms_agent", "executor_agent", "gmail_agent"):
            llm = MagicMock()
            _bind_session_id(
                llm, {"provider": LLMProviderName.OPENROUTER, "session_id": "conv-1"}, agent
            )
            keys.append(llm.bind.call_args.kwargs["session_id"])

        assert keys == ["conv-1-comms_agent", "conv-1-executor_agent", "conv-1-gmail_agent"]
        assert len(set(keys)) == len(keys)

    def test_the_conversation_still_separates_two_agents_of_the_same_name(self) -> None:
        """The agent name narrows the key, it must not replace the conversation:
        two users' comms agents must never land in one chain."""

        first, second = MagicMock(), MagicMock()
        _bind_session_id(
            first, {"provider": LLMProviderName.OPENROUTER, "session_id": "conv-1"}, "comms_agent"
        )
        _bind_session_id(
            second, {"provider": LLMProviderName.OPENROUTER, "session_id": "conv-2"}, "comms_agent"
        )

        assert first.bind.call_args.kwargs["session_id"] == "conv-1-comms_agent"
        assert second.bind.call_args.kwargs["session_id"] == "conv-2-comms_agent"

    def test_gemini_is_left_alone(self) -> None:
        """session_id is an OpenRouter routing hint. Gemini has no stickiness to
        pin, so sending it there is an unsupported argument on every graph call."""

        llm = MagicMock()
        bound = _bind_session_id(llm, {"provider": LLMProviderName.GEMINI, "session_id": "conv-1"})

        llm.bind.assert_not_called()
        assert bound is llm

    def test_an_unrelated_configurable_key_is_not_mistaken_for_it(self) -> None:
        llm = MagicMock()
        bound = _bind_session_id(llm, cast(AgentConfigurable, {"thread_id": "conv-1"}))

        llm.bind.assert_not_called()
        assert bound is llm


# ---------------------------------------------------------------------------
# provider failover
# ---------------------------------------------------------------------------


class TestFallbackPreparation:
    """The graph's provider failover.

    Falling back to ``get_default_llm()`` was inert in production: it was skipped
    whenever the run already selected the default model, and since every tier
    resolves to that model the graph had no fallback at all — one 402 from
    OpenRouter killed the whole turn on every execution path. The target is a
    different PROVIDER now, which is what these pin.
    """

    def _openrouter_lane(self) -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.OPENROUTER,
            model="vendor/dead-model",
            reasoning={"effort": "low"},
            provider_pin={"provider": {"only": ["dead-vendor"]}},
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

    def _gemini_lane(self) -> ModelLane:
        return ModelLane(
            provider=LLMProviderName.GEMINI,
            model="gemini-x",
            reasoning=None,
            provider_pin=None,
            max_input_tokens=DEFAULT_MAX_TOKENS,
        )

    def _next_is_gemini(self) -> Any:
        return patch.object(
            lane_module,
            "next_fallback_provider",
            lambda _current: (LLMProviderName.GEMINI, "gemini-x"),
        )

    def test_a_run_with_no_lane_has_no_fallback_to_prepare(self) -> None:
        assert _prepare_fallback(_make_llm(), [dummy_tool_a], {}) is None

    def test_no_other_configured_provider_means_no_fallback(self) -> None:
        configurable = cast(
            AgentConfigurable, {LANE_FIELD_ID: self._openrouter_lane().to_configurable()}
        )

        with patch.object(lane_module, "next_fallback_provider", lambda _current: None):
            assert _prepare_fallback(_make_llm(), [dummy_tool_a], configurable) is None

    def test_the_fallback_targets_the_next_provider_with_the_same_tools(self) -> None:
        llm = MagicMock()
        bound = MagicMock()
        llm.bind_tools.return_value = bound
        configurable = cast(
            AgentConfigurable, {LANE_FIELD_ID: self._openrouter_lane().to_configurable()}
        )

        with self._next_is_gemini():
            prepared = _prepare_fallback(llm, [dummy_tool_a], configurable)

        assert prepared is not None
        factory, fallback_lane = prepared
        assert fallback_lane.provider == LLMProviderName.GEMINI
        assert fallback_lane.model == "gemini-x"
        # Zero-arg factory: the per-turn, tool-list-sized binding must not happen
        # unless the primary actually fails.
        llm.bind_tools.assert_not_called()
        assert factory() is bound
        llm.bind_tools.assert_called_once_with([dummy_tool_a])

    def test_the_fallback_config_clears_the_failed_lanes_keys(self) -> None:
        """A plain merge restored the just-failed provider — LangChain merges a
        passed config over a bound one, so the stale keys must be REMOVED."""
        config = {
            "configurable": {
                **self._openrouter_lane().binding_keys(),
                "user_id": "u1",
            }
        }

        rebound = _fallback_config(cast(RunnableConfig, config), self._gemini_lane())

        configurable = rebound["configurable"]
        assert configurable["provider"] == LLMProviderName.GEMINI
        assert configurable["model"] == "gemini-x"
        assert "model_kwargs" not in configurable
        assert "reasoning" not in configurable
        assert configurable["user_id"] == "u1"

    def test_a_config_carrying_no_configurable_still_gets_the_fallback_lane(self) -> None:
        rebound = _fallback_config(cast(RunnableConfig, {}), self._gemini_lane())

        assert rebound["configurable"]["provider"] == LLMProviderName.GEMINI


class TestTheFallbackKeepsTheAgentsOwnChain:
    """The per-agent sticky key must survive a provider failover.

    The primary binds ``{session}-{agent}`` so comms, the executor and each
    subagent hold separate cache chains. ``ainvoke_llm`` used to recompute the
    fallback's key from config, which yields the BARE ``{session}`` — so the
    moment a provider hiccuped, every agent's fallback landed back in one
    shared chain and they resumed evicting each other, which is the exact
    failure the per-agent key was measured to fix (+19.2 points on comms).
    """

    def test_the_key_carries_the_agent_name(self) -> None:
        configurable = cast(
            AgentConfigurable,
            {"provider": LLMProviderName.OPENROUTER, "session_id": "conv-1"},
        )

        assert _agent_sticky_key(configurable, "comms_agent") == "conv-1-comms_agent"
        assert _agent_sticky_key(configurable, None) == "conv-1"

    def test_a_non_sticky_provider_has_no_key_to_carry(self) -> None:
        gemini = cast(
            AgentConfigurable, {"provider": LLMProviderName.GEMINI, "session_id": "conv-1"}
        )

        assert _agent_sticky_key(gemini, "comms_agent") is None

    @pytest.mark.asyncio
    async def test_the_model_node_hands_that_key_to_the_fallback(self) -> None:
        """The wiring, not just the helper: whatever the primary binds is what
        the fallback must be told to bind."""

        llm = _make_llm()
        builder = create_agent(
            llm,
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        with patch(
            "app.override.langgraph_bigtool.create_agent.ainvoke_llm",
            new=AsyncMock(return_value=AIMessage(content="ok")),
        ) as invoked:
            await _agent_runnable(builder).afunc(
                _make_state(messages=[HumanMessage(content="hi")]),
                _make_config(provider=LLMProviderName.OPENROUTER, session_id="conv-1"),
                store=MagicMock(),
            )

        assert invoked.await_args.kwargs["sticky_session_id"] == "conv-1-comms_agent"

    def test_the_sync_model_node_hands_that_key_over_too(self) -> None:
        """Both model call sites, same as the bind: they drift independently,
        and a fallback on whichever path lacks the key silently rejoins the
        shared chain."""
        llm = _make_llm()
        builder = create_agent(
            llm,
            _make_tool_registry(dummy_tool_a),
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        with patch(
            "app.override.langgraph_bigtool.create_agent.invoke_llm",
            return_value=AIMessage(content="ok"),
        ) as invoked:
            _agent_runnable(builder).func(
                _make_state(messages=[HumanMessage(content="hi")]),
                _make_config(provider=LLMProviderName.OPENROUTER, session_id="conv-1"),
                store=MagicMock(),
            )

        assert invoked.call_args.kwargs["sticky_session_id"] == "conv-1-comms_agent"
