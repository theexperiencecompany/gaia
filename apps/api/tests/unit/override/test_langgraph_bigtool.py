"""Tests for app.override.langgraph_bigtool.create_agent.

Exercises the graph-building wiring, the model-call nodes (sync + async), the
tool-selection nodes, the routing branch, and every helper closure through the
compiled builder — asserting exact return values and exact arguments to
mocked seams (LLM client, hooks, logging) so a single flipped operator in
``create_agent`` fails loudly.
"""

from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock, call, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.graph import END
from langgraph.prebuilt import InjectedStore
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
import pytest

_MOD = "app.override.langgraph_bigtool.create_agent"

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


@tool
def dummy_tool_c(query: str) -> str:
    """A third dummy tool for testing."""
    return "result_c"


@tool("dash-tool")
def dash_tool(query: str) -> str:
    """A dummy tool whose name contains a hyphen."""
    return "result_dash"


@tool("a-b-c")
def hyphenated_tool(query: str) -> str:
    """A dummy tool whose name has multiple hyphens."""
    return "result_abc"


def _make_tool_registry(*tools_list: BaseTool) -> dict[str, BaseTool]:
    return {t.name: t for t in tools_list}


def _make_llm() -> MagicMock:
    llm = MagicMock()
    configured = MagicMock()
    bound = MagicMock()
    bound.invoke.return_value = AIMessage(content="hello")
    bound.ainvoke = AsyncMock(return_value=AIMessage(content="hello"))
    bound.with_retry.return_value = bound
    configured.bind_tools.return_value = bound
    llm.with_config.return_value = configured
    return llm


def _make_config(**configurable: Any) -> dict:
    return {"configurable": configurable}


def _make_state(
    messages: list | None = None,
    selected_tool_ids: list | None = None,
    todos: list | None = None,
    **extra: Any,
) -> dict:
    return {
        "messages": messages or [],
        "selected_tool_ids": selected_tool_ids or [],
        "todos": todos or [],
        **extra,
    }


def _agent_node(builder: Any) -> Any:
    return builder.nodes["agent"].runnable


def _should_continue(builder: Any) -> Any:
    return builder.branches["agent"]["should_continue"].path.func


def _retrieve_func(**kwargs: Any) -> list[str]:
    """Retrieve tools."""
    return ["dummy_tool_a"]


def _retrieve_coro(**kwargs: Any) -> list[str]:
    """Retrieve tools."""
    return ["dummy_tool_a"]


# ---------------------------------------------------------------------------
# _prepare_fallback
# ---------------------------------------------------------------------------


class TestPrepareFallback:
    def test_returns_none_when_no_fallback_llm(self) -> None:
        from app.override.langgraph_bigtool.create_agent import _prepare_fallback

        assert _prepare_fallback(None, [dummy_tool_a], {}) is None

    def test_returns_none_when_model_config_is_default(self) -> None:
        from app.override.langgraph_bigtool.create_agent import _prepare_fallback

        fallback_llm = MagicMock()
        with patch(f"{_MOD}.is_default_model_config", return_value=True) as mock_default:
            result = _prepare_fallback(
                fallback_llm, [dummy_tool_a], {"provider": "x", "model_name": "y"}
            )
        assert result is None
        mock_default.assert_called_once_with({"provider": "x", "model_name": "y"})

    def test_returns_factory_that_binds_exact_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import _prepare_fallback

        fallback_llm = MagicMock()
        tools = [dummy_tool_a, dummy_tool_b]
        with patch(f"{_MOD}.is_default_model_config", return_value=False):
            factory = _prepare_fallback(fallback_llm, tools, {"provider": "gemini"})
        assert callable(factory)
        bound = factory()
        fallback_llm.bind_tools.assert_called_once_with(tools)
        assert bound is fallback_llm.bind_tools.return_value

    def test_factory_binds_again_on_each_call(self) -> None:
        from app.override.langgraph_bigtool.create_agent import _prepare_fallback

        fallback_llm = MagicMock()
        with patch(f"{_MOD}.is_default_model_config", return_value=False):
            factory = _prepare_fallback(fallback_llm, [dummy_tool_a], {})
        factory()
        factory()
        assert fallback_llm.bind_tools.call_count == 2


# ---------------------------------------------------------------------------
# create_agent — construction wiring
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_returns_state_graph(self) -> None:
        from langgraph.graph import StateGraph

        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        assert isinstance(builder, StateGraph)

    def test_default_retrieval_tool_used_when_none_provided(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        sync_fn = _retrieve_func
        coro_fn = _retrieve_coro
        mock_tool = MagicMock()

        with (
            patch(
                f"{_MOD}.get_default_retrieval_tool",
                return_value=(sync_fn, coro_fn),
            ) as mock_get_default,
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool) as mock_from_fn,
            patch(f"{_MOD}.get_store_arg", return_value="store") as mock_store_arg,
        ):
            create_agent(llm, registry)

        mock_get_default.assert_called_once_with(("tools",), limit=2, filter=None)
        mock_from_fn.assert_called_once_with(func=sync_fn, coroutine=coro_fn)
        mock_store_arg.assert_called_once_with(mock_tool)

    def test_retrieval_params_forwarded_to_default_tool(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        with (
            patch(
                f"{_MOD}.get_default_retrieval_tool",
                return_value=(_retrieve_func, _retrieve_coro),
            ) as mock_get_default,
            patch(f"{_MOD}.StructuredTool.from_function", return_value=MagicMock()),
            patch(f"{_MOD}.get_store_arg", return_value=None),
        ):
            create_agent(
                llm,
                registry,
                limit=5,
                filter={"kind": "mcp"},
                namespace_prefix=("custom", "nested"),
            )

        mock_get_default.assert_called_once_with(
            ("custom", "nested"), limit=5, filter={"kind": "mcp"}
        )

    def test_provided_retrieval_funcs_skip_default_tool(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mock_tool = MagicMock()

        with (
            patch(f"{_MOD}.get_default_retrieval_tool") as mock_get_default,
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool) as mock_from_fn,
            patch(f"{_MOD}.get_store_arg", return_value="store"),
        ):
            create_agent(
                llm,
                registry,
                retrieve_tools_function=_retrieve_func,
                retrieve_tools_coroutine=_retrieve_coro,
            )

        mock_get_default.assert_not_called()
        mock_from_fn.assert_called_once_with(func=_retrieve_func, coroutine=_retrieve_coro)

    def test_only_sync_retrieval_function(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        node = builder.nodes["select_tools"].runnable
        assert callable(node.func)
        assert node.func is not None

    def test_only_async_retrieval_coroutine(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_coroutine=_retrieve_coro)

        node = builder.nodes["select_tools"].runnable
        assert node.func is None
        assert callable(node.afunc)

    def test_disable_retrieve_tools_omits_select_path(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        with (
            patch(f"{_MOD}.get_default_retrieval_tool") as mock_get_default,
            patch(f"{_MOD}.StructuredTool.from_function") as mock_from_fn,
        ):
            builder = create_agent(llm, registry, disable_retrieve_tools=True)

        mock_get_default.assert_not_called()
        mock_from_fn.assert_not_called()
        assert "select_tools" not in builder.nodes
        assert ("select_tools", "agent") not in builder.edges
        ends = builder.branches["agent"]["should_continue"].ends
        assert list(ends) == ["tools", "finish_task", "reject_unbound_tools", "__end__"]

    def test_raise_when_no_retrieval_funcs_available(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        with (
            patch(
                f"{_MOD}.get_default_retrieval_tool",
                return_value=(None, None),
            ),
            patch(f"{_MOD}.StructuredTool.from_function", return_value=MagicMock()),
            patch(f"{_MOD}.get_store_arg", return_value=None),
            pytest.raises(
                ValueError,
                match=r"^One of retrieve_tools_function or retrieve_tools_coroutine must be "
                r"provided\.$",
            ),
        ):
            create_agent(llm, registry)

    def test_middleware_tools_extracted_basetool_only(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = [dummy_tool_a, dummy_tool_b, "not_a_tool"]

        with patch(f"{_MOD}.DynamicToolNode") as mock_dtn:
            create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )

        assert mock_dtn.call_args.kwargs["middleware_tools"] == [dummy_tool_a, dummy_tool_b]

    def test_middleware_without_tools_attr(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock(spec=[])

        with patch(f"{_MOD}.DynamicToolNode") as mock_dtn:
            create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )

        assert mock_dtn.call_args.kwargs["middleware_tools"] == []

    def test_middleware_executor_constructed_with_list(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = []

        with (
            patch(f"{_MOD}.MiddlewareExecutor") as mock_me_cls,
            patch(f"{_MOD}.DynamicToolNode"),
        ):
            create_agent(llm, registry, disable_retrieve_tools=True, middleware=[mw])

        mock_me_cls.assert_called_once_with([mw])

    def test_middleware_executor_skipped_without_middleware(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        with (
            patch(f"{_MOD}.MiddlewareExecutor") as mock_me_cls,
            patch(f"{_MOD}.DynamicToolNode"),
        ):
            create_agent(llm, registry, disable_retrieve_tools=True)

        mock_me_cls.assert_not_called()

    def test_dynamic_tool_node_wired_with_guards(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent
        from app.override.langgraph_bigtool.dynamic_tool_node import (
            format_tool_error,
            hil_and_timeout_guarded_tool_call,
        )

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = [dummy_tool_a]

        with patch(f"{_MOD}.DynamicToolNode") as mock_dtn:
            create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )

        assert mock_dtn.call_args.args[0] == registry
        assert mock_dtn.call_args.kwargs["middleware_executor"] is not None
        assert mock_dtn.call_args.kwargs["middleware_tools"] == [dummy_tool_a]
        assert mock_dtn.call_args.kwargs["handle_tool_errors"] is format_tool_error
        assert mock_dtn.call_args.kwargs["awrap_tool_call"] is hil_and_timeout_guarded_tool_call

    def test_end_graph_hooks_wiring(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )

        assert "end_graph_hooks" in builder.nodes
        assert ("end_graph_hooks", "__end__") in builder.edges
        assert ("finish_task", "end_graph_hooks") in builder.edges
        ends = builder.branches["agent"]["should_continue"].ends
        assert list(ends) == ["tools", "finish_task", "reject_unbound_tools", "__end__", "end_graph_hooks"]

    def test_no_end_graph_hooks_routes_finish_to_end(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        assert "end_graph_hooks" not in builder.nodes
        assert ("finish_task", "__end__") in builder.edges
        assert ("finish_task", "end_graph_hooks") not in builder.edges

    def test_path_map_includes_select_tools_first(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        ends = builder.branches["agent"]["should_continue"].ends
        assert list(ends) == ["select_tools", "tools", "finish_task", "reject_unbound_tools", "__end__"]

    def test_agent_node_has_sync_and_async_impls(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        node = builder.nodes["agent"].runnable
        assert callable(node.func)
        assert callable(node.afunc)

    def test_select_tools_node_has_retry_policy(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        assert builder.nodes["select_tools"].retry_policy is not None

    def test_nodes_and_edges_wired_exactly(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        assert set(builder.nodes) == {
            "agent",
            "select_tools",
            "tools",
            "finish_task",
            "reject_unbound_tools",
        }
        assert builder.edges == {
            ("__start__", "agent"),
            ("select_tools", "agent"),
            ("tools", "agent"),
            ("finish_task", "__end__"),
            ("reject_unbound_tools", "agent"),
        }

    def test_context_schema_passed_to_state_graph(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        class CtxSchema:
            pass

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            context_schema=CtxSchema,
        )

        assert builder.context_schema is CtxSchema

    @pytest.mark.asyncio
    async def test_both_retrieval_funcs_node_runs_sync_and_async(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        async def my_coro(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_function=my_func,
            retrieve_tools_coroutine=my_coro,
        )
        node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]
        expected = {
            "messages": [
                ToolMessage(content="Available tools: ['dummy_tool_a']", tool_call_id="tc1")
            ],
            "selected_tool_ids": ["dummy_tool_a"],
        }

        assert node.func is not None
        assert node.afunc is not None
        assert node.func(tool_calls, _make_config(), store=MagicMock()) == expected
        assert await node.afunc(tool_calls, _make_config(), store=MagicMock()) == expected

    def test_fallback_llm_fetched_from_default(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        fallback_llm = MagicMock()

        with (
            patch(f"{_MOD}.get_default_llm", return_value=fallback_llm) as mock_get,
            patch(f"{_MOD}.MiddlewareExecutor"),
            patch(f"{_MOD}.DynamicToolNode"),
        ):
            create_agent(llm, registry, disable_retrieve_tools=True)

        mock_get.assert_called_once_with()

    def test_unconfigured_default_llm_tolerated(self) -> None:
        from langgraph.graph import StateGraph

        from app.agents.llm.exceptions import LLMNotConfiguredError
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        with (
            patch(f"{_MOD}.get_default_llm", side_effect=LLMNotConfiguredError("no key")),
            patch(f"{_MOD}.MiddlewareExecutor"),
            patch(f"{_MOD}.DynamicToolNode"),
        ):
            builder = create_agent(llm, registry, disable_retrieve_tools=True)

        assert isinstance(builder, StateGraph)


# ---------------------------------------------------------------------------
# call_model (sync) — exact LLM-client args
# ---------------------------------------------------------------------------


class TestCallModel:
    def test_sync_basic_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        configured = llm.with_config.return_value
        bound = configured.bind_tools.return_value
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="hello")

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=[HumanMessage(content="hi")])
        config = _make_config(user_id="u1")
        store = MagicMock()

        with patch(f"{_MOD}.invoke_llm", return_value=response) as mock_invoke:
            result = _agent_node(builder).func(state, config, store=store)

        llm.with_config.assert_called_once_with(configurable={"user_id": "u1"})
        configured.bind_tools.assert_called_once_with([])
        mock_invoke.assert_called_once_with(
            bound,
            [HumanMessage(content="hi")],
            fallback=None,
            config=config,
            label="main_agent",
        )
        assert result == {"messages": [response]}

    def test_sync_config_without_configurable(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")):
            _agent_node(builder).func(_make_state(), {"no_configurable": True}, store=MagicMock())

        llm.with_config.assert_called_once_with(configurable={})

    def test_sync_non_comms_content_untouched(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="plain answer")

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.invoke_llm", return_value=response):
            result = _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert result == {"messages": [AIMessage(content="plain answer")]}

    def test_sync_comms_agent_appends_breaker(self) -> None:
        from app.constants.general import NEW_MESSAGE_BREAKER
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="reply")

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        with patch(f"{_MOD}.invoke_llm", return_value=response) as mock_invoke:
            result = _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert mock_invoke.call_args.kwargs["label"] == "comms_agent"
        assert result == {"messages": [AIMessage(content="reply" + NEW_MESSAGE_BREAKER)]}

    def test_sync_comms_agent_list_content_untouched(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content=["block one", "block two"])

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        with patch(f"{_MOD}.invoke_llm", return_value=response):
            result = _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert result == {"messages": [AIMessage(content=["block one", "block two"])]}

    def test_sync_empty_response_gets_default_content(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="", tool_calls=[])

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.invoke_llm", return_value=response):
            result = _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert result["messages"][0].content == "Empty response from model."

    def test_sync_tool_call_response_not_overridden(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="", tool_calls=[{"id": "tc1", "name": "x", "args": {}}])

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.invoke_llm", return_value=response):
            result = _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert result["messages"][0].content == ""

    def test_sync_fallback_factory_passed_when_non_default_model(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        fallback_llm = MagicMock()
        tools_to_bind = [dummy_tool_a]
        model_config = {"provider": "gemini", "model_name": "g"}

        with (
            patch(f"{_MOD}.get_default_llm", return_value=fallback_llm),
            patch(f"{_MOD}._prepare_fallback", return_value="fallback-factory") as mock_prepare,
            patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke,
        ):
            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                initial_tool_ids=["dummy_tool_a"],
            )
            _agent_node(builder).func(
                _make_state(), _make_config(**model_config), store=MagicMock()
            )

        mock_prepare.assert_called_once_with(fallback_llm, tools_to_bind, model_config)
        assert mock_invoke.call_args.kwargs["fallback"] == "fallback-factory"

    def test_sync_no_fallback_when_default_model_config(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with (
            patch(f"{_MOD}.get_default_llm", return_value=MagicMock()),
            patch(f"{_MOD}.is_default_model_config", return_value=True),
            patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke,
        ):
            _agent_node(builder).func(
                _make_state(), _make_config(provider="openrouter"), store=MagicMock()
            )

        assert mock_invoke.call_args.kwargs["fallback"] is None

    def test_sync_no_fallback_when_llm_unconfigured(self) -> None:
        from app.agents.llm.exceptions import LLMNotConfiguredError
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with (
            patch(f"{_MOD}.get_default_llm", side_effect=LLMNotConfiguredError("no key")),
            patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke,
        ):
            _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

        assert mock_invoke.call_args.kwargs["fallback"] is None

    def test_sync_pre_model_hooks_run_and_state_used(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        hook = lambda state, config, store: state  # noqa: E731
        hooked_state = _make_state(messages=[HumanMessage(content="hooked")])

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            pre_model_hooks=[hook],
        )
        state = _make_state(messages=[HumanMessage(content="original")])
        config = _make_config()
        store = MagicMock()

        with (
            patch(f"{_MOD}.sync_execute_hooks", return_value=hooked_state) as mock_hooks,
            patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke,
        ):
            _agent_node(builder).func(state, config, store=store)

        mock_hooks.assert_called_once_with([hook], state, config, store)
        assert mock_invoke.call_args.args[1] == [HumanMessage(content="hooked")]

    def test_sync_middleware_raises(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        with pytest.raises(
            RuntimeError,
            match=r"^Agent middleware is configured but sync execution was requested\. "
            r"Use the async graph execution path \(ainvoke/astream\)\.$",
        ):
            _agent_node(builder).func(_make_state(), _make_config(), store=MagicMock())

    def test_sync_wrapup_injected_at_threshold(self) -> None:
        from app.constants.llm import RECURSION_WRAPUP_THRESHOLD_STEPS
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(
            messages=original_messages, remaining_steps=RECURSION_WRAPUP_THRESHOLD_STEPS
        )

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        sent_messages = mock_invoke.call_args.args[1]
        assert len(sent_messages) == 2
        assert isinstance(sent_messages[-1], HumanMessage)
        assert sent_messages[-1].content == (
            "[System notice: you are almost out of steps for this run "
            f"(~{RECURSION_WRAPUP_THRESHOLD_STEPS} left). Stop exploring now — summarize what you "
            "found and what remains to be done, and finish your reply.]"
        )
        assert state["messages"] == original_messages

    def test_sync_wrapup_injected_below_threshold(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=[HumanMessage(content="hi")], remaining_steps=2)

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        sent_messages = mock_invoke.call_args.args[1]
        assert "(~2 left)" in sent_messages[-1].content

    def test_sync_wrapup_not_injected_above_threshold(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi"), AIMessage(content="there")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=original_messages, remaining_steps=7)

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        assert mock_invoke.call_args.args[1] == original_messages

    def test_sync_wrapup_injected_without_messages_key(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = {"selected_tool_ids": [], "remaining_steps": 3}

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        sent_messages = mock_invoke.call_args.args[1]
        assert len(sent_messages) == 1
        assert isinstance(sent_messages[0], HumanMessage)
        assert "(~3 left)" in sent_messages[0].content

    def test_sync_wrapup_not_injected_for_non_int_remaining(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=original_messages, remaining_steps="6")

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        assert mock_invoke.call_args.args[1] == original_messages

    def test_sync_wrapup_not_injected_when_missing(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=original_messages)

        with patch(f"{_MOD}.invoke_llm", return_value=AIMessage(content="hello")) as mock_invoke:
            _agent_node(builder).func(state, _make_config(), store=MagicMock())

        assert mock_invoke.call_args.args[1] == original_messages


# ---------------------------------------------------------------------------
# acall_model (async)
# ---------------------------------------------------------------------------


class TestAcallModel:
    @pytest.mark.asyncio
    async def test_acall_binds_tools_in_stable_order(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        configured = llm.with_config.return_value
        registry = _make_tool_registry(dummy_tool_a, dummy_tool_b)
        mw = MagicMock()
        mw.tools = [dummy_tool_c, "not_a_tool"]

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_function=_retrieve_func,
            initial_tool_ids=["dummy_tool_b", "ghost_initial"],
            middleware=[mw],
        )
        state = _make_state(selected_tool_ids=["dummy_tool_a", "ghost", "dummy_tool_b"])

        with patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")):
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        bound_tools = configured.bind_tools.call_args.args[0]
        assert [t.name for t in bound_tools] == [
            "_retrieve_func",
            "dummy_tool_b",
            "dummy_tool_c",
            "dummy_tool_a",
        ]

    @pytest.mark.asyncio
    async def test_acall_binds_initial_tools_without_retrieve(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        configured = llm.with_config.return_value
        registry = _make_tool_registry(dummy_tool_a, dummy_tool_b)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_b", "ghost"],
        )
        state = _make_state(selected_tool_ids=["dummy_tool_a"])

        with patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")):
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        bound_tools = configured.bind_tools.call_args.args[0]
        assert [t.name for t in bound_tools] == ["dummy_tool_b", "dummy_tool_a"]

    @pytest.mark.asyncio
    async def test_acall_basic_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        configured = llm.with_config.return_value
        bound = configured.bind_tools.return_value
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="hello")
        messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = {"messages": messages, "selected_tool_ids": []}
        config = _make_config(user_id="u1")
        store = MagicMock()

        with patch(f"{_MOD}.ainvoke_llm", return_value=response) as mock_ainvoke:
            result = await _agent_node(builder).afunc(state, config, store=store)

        llm.with_config.assert_called_once_with(configurable={"user_id": "u1"})
        configured.bind_tools.assert_called_once_with([])
        mock_ainvoke.assert_awaited_once_with(
            bound,
            messages,
            fallback=None,
            config=config,
            label="main_agent",
        )
        assert result == {"messages": [response]}

    @pytest.mark.asyncio
    async def test_acall_includes_non_base_state_keys(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="hello")

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(todos=["t0"], intent="reply")

        with patch(f"{_MOD}.ainvoke_llm", return_value=response):
            result = await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        assert result == {"messages": [response], "todos": ["t0"], "intent": "reply"}

    @pytest.mark.asyncio
    async def test_acall_comms_agent_appends_breaker(self) -> None:
        from app.constants.general import NEW_MESSAGE_BREAKER
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="reply")

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            agent_name="comms_agent",
        )

        with (
            patch(f"{_MOD}.ainvoke_llm", return_value=response) as mock_ainvoke,
        ):
            result = await _agent_node(builder).afunc(
                _make_state(), _make_config(), store=MagicMock()
            )

        assert mock_ainvoke.call_args.kwargs["label"] == "comms_agent"
        assert result["messages"] == [AIMessage(content="reply" + NEW_MESSAGE_BREAKER)]

    @pytest.mark.asyncio
    async def test_acall_non_comms_content_untouched(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="plain")

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.ainvoke_llm", return_value=response):
            result = await _agent_node(builder).afunc(
                _make_state(), _make_config(), store=MagicMock()
            )

        assert result["messages"] == [AIMessage(content="plain")]

    @pytest.mark.asyncio
    async def test_acall_empty_response_gets_default_content(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        response = AIMessage(content="", tool_calls=[])

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.ainvoke_llm", return_value=response):
            result = await _agent_node(builder).afunc(
                _make_state(), _make_config(), store=MagicMock()
            )

        assert result["messages"][0].content == "Empty response from model."

    @pytest.mark.asyncio
    async def test_acall_fallback_factory_passed_when_non_default_model(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        fallback_llm = MagicMock()
        model_config = {"provider": "gemini", "model_name": "g"}

        with (
            patch(f"{_MOD}.get_default_llm", return_value=fallback_llm),
            patch(f"{_MOD}._prepare_fallback", return_value="fallback-factory") as mock_prepare,
            patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")) as mock_ainvoke,
        ):
            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                initial_tool_ids=["dummy_tool_a"],
            )
            await _agent_node(builder).afunc(
                _make_state(), _make_config(**model_config), store=MagicMock()
            )

        mock_prepare.assert_called_once_with(fallback_llm, [dummy_tool_a], model_config)
        assert mock_ainvoke.call_args.kwargs["fallback"] == "fallback-factory"

    @pytest.mark.asyncio
    async def test_acall_wrapup_injected(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=original_messages, remaining_steps=3)

        with patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")) as mock_ainvoke:
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        sent_messages = mock_ainvoke.call_args.args[1]
        assert isinstance(sent_messages[-1], HumanMessage)
        assert "(~3 left)" in sent_messages[-1].content
        assert state["messages"] == original_messages

    @pytest.mark.asyncio
    async def test_acall_wrapup_not_injected_above_threshold(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        original_messages = [HumanMessage(content="hi")]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=original_messages, remaining_steps=7)

        with patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")) as mock_ainvoke:
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        assert mock_ainvoke.call_args.args[1] == original_messages

    @pytest.mark.asyncio
    async def test_acall_pre_model_hooks_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        hook = lambda state, config, store: state  # noqa: E731
        hooked_state = _make_state(messages=[HumanMessage(content="hooked")])

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            pre_model_hooks=[hook],
        )
        state = _make_state(messages=[HumanMessage(content="original")])
        config = _make_config()
        store = MagicMock()

        with (
            patch(f"{_MOD}.execute_hooks", new=AsyncMock(return_value=hooked_state)) as mock_hooks,
            patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")) as mock_ainvoke,
        ):
            await _agent_node(builder).afunc(state, config, store=store)

        mock_hooks.assert_awaited_once_with([hook], state, config, store)
        assert mock_ainvoke.call_args.args[1] == [HumanMessage(content="hooked")]

    @pytest.mark.asyncio
    async def test_acall_config_without_configurable(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        with patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")):
            await _agent_node(builder).afunc(
                _make_state(), {"no_configurable": True}, store=MagicMock()
            )

        llm.with_config.assert_called_once_with(configurable={})

    @pytest.mark.asyncio
    async def test_acall_state_without_messages_key(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = []
        response = AIMessage(content="hello")

        with patch(f"{_MOD}.MiddlewareExecutor") as mock_me_cls:
            exec_mock = MagicMock()
            exec_mock.execute_before_model = AsyncMock(return_value={"selected_tool_ids": []})
            exec_mock.has_wrap_model_call.return_value = True
            exec_mock.wrap_model_invocation = AsyncMock(return_value=response)
            exec_mock.execute_after_model = AsyncMock(
                return_value={"messages": [response], "selected_tool_ids": []}
            )
            mock_me_cls.return_value = exec_mock

            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )
            state = {"selected_tool_ids": []}
            config = _make_config()
            store = MagicMock()

            with (
                patch(f"{_MOD}.ainvoke_llm", return_value=response),
                patch(f"{_MOD}.log") as mock_log,
            ):
                result = await _agent_node(builder).afunc(state, config, store=store)

        mock_log.info.assert_called_once()
        assert mock_log.info.call_args.kwargs["preview"] == []
        mock_log.debug.assert_not_called()
        exec_mock.execute_after_model.assert_awaited_once_with(
            {"selected_tool_ids": [], "messages": [response]}, config, store
        )
        assert result == {"messages": [response]}

    @pytest.mark.asyncio
    async def test_acall_preview_content_less_message(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        class NoContentMessage:
            pass

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=[NoContentMessage()])

        with (
            patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")),
            patch(f"{_MOD}.log") as mock_log,
        ):
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        mock_log.info.assert_called_once()
        assert mock_log.info.call_args.kwargs["preview"] == [
            {"role": "NoContentMessage", "content": ""}
        ]

    @pytest.mark.asyncio
    async def test_acall_preview_logs_last_six_truncated(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        messages = [HumanMessage(content="first")]
        messages += [
            HumanMessage(content="x" * 300),
            AIMessage(content="y" * 200),
            ToolMessage(content="z" * 250, tool_call_id="tc1", name="tool"),
            HumanMessage(content="w" * 201),
            AIMessage(content="short"),
            HumanMessage(content=""),
        ]
        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=messages)

        with (
            patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")),
            patch(f"{_MOD}.log") as mock_log,
        ):
            await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        mock_log.info.assert_called_once()
        assert mock_log.info.call_args.args[0] == "acall_model message preview"
        preview = mock_log.info.call_args.kwargs["preview"]
        assert [m["role"] for m in preview] == [
            "HumanMessage",
            "AIMessage",
            "ToolMessage",
            "HumanMessage",
            "AIMessage",
            "HumanMessage",
        ]
        assert preview[0]["content"] == "x" * 197 + "..."
        assert preview[1]["content"] == "y" * 200
        assert preview[2]["content"] == "z" * 197 + "..."
        assert preview[3]["content"] == "w" * 197 + "..."
        assert preview[4]["content"] == "short"
        assert preview[5]["content"] == ""

    @pytest.mark.asyncio
    async def test_acall_preview_never_blocks_model_call(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = {"messages": [HumanMessage(content="hi")], "selected_tool_ids": []}

        with (
            patch(
                f"{_MOD}.extract_text_content",
                side_effect=ValueError("boom"),
            ),
            patch(f"{_MOD}.ainvoke_llm", return_value=AIMessage(content="hello")),
            patch(f"{_MOD}.log") as mock_log,
        ):
            result = await _agent_node(builder).afunc(state, _make_config(), store=MagicMock())

        mock_log.info.assert_not_called()
        mock_log.debug.assert_called_once()
        assert mock_log.debug.call_args.args[0] == "Failed to log message preview"
        assert mock_log.debug.call_args.kwargs == {"error_type": "ValueError", "error": "boom"}
        assert result == {"messages": [AIMessage(content="hello")]}

    @pytest.mark.asyncio
    async def test_acall_middleware_before_after_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = []
        response = AIMessage(content="hello")
        before_state = _make_state(messages=[HumanMessage(content="hi")], intent="x")
        after_state = _make_state(
            messages=[HumanMessage(content="hi")],
            todos=["t1"],
            intent="x",
            selected_tool_ids=["stale"],
        )

        with patch(f"{_MOD}.MiddlewareExecutor") as mock_me_cls:
            exec_mock = MagicMock()
            exec_mock.execute_before_model = AsyncMock(return_value=before_state)
            exec_mock.has_wrap_model_call.return_value = False
            exec_mock.execute_after_model = AsyncMock(return_value=after_state)
            mock_me_cls.return_value = exec_mock

            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )
            state = _make_state(messages=[HumanMessage(content="hi")])
            config = _make_config()
            store = MagicMock()

            with patch(f"{_MOD}.ainvoke_llm", return_value=response):
                result = await _agent_node(builder).afunc(state, config, store=store)

        mock_me_cls.assert_called_once_with([mw])
        exec_mock.execute_before_model.assert_awaited_once_with(state, config, store)
        expected_updated = {
            **before_state,
            "messages": [HumanMessage(content="hi"), response],
        }
        exec_mock.execute_after_model.assert_awaited_once_with(expected_updated, config, store)
        # selected_tool_ids is a base key: after_model writes to it must not leak
        # into the returned state update.
        assert result == {"messages": [response], "todos": ["t1"], "intent": "x"}

    @pytest.mark.asyncio
    async def test_acall_middleware_wrap_model_call_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        configured = llm.with_config.return_value
        bound = configured.bind_tools.return_value
        registry = _make_tool_registry(dummy_tool_a)
        mw = MagicMock()
        mw.tools = []
        wrapped_response = AIMessage(content="wrapped")
        before_state = _make_state(messages=[HumanMessage(content="hi")], intent="x")
        after_state = {"messages": [HumanMessage(content="hi")], "selected_tool_ids": []}

        with patch(f"{_MOD}.MiddlewareExecutor") as mock_me_cls:
            exec_mock = MagicMock()
            exec_mock.execute_before_model = AsyncMock(return_value=before_state)
            exec_mock.has_wrap_model_call.return_value = True
            exec_mock.wrap_model_invocation = AsyncMock(return_value=wrapped_response)
            exec_mock.execute_after_model = AsyncMock(return_value=after_state)
            mock_me_cls.return_value = exec_mock

            builder = create_agent(
                llm,
                registry,
                disable_retrieve_tools=True,
                middleware=[mw],
            )
            state = {"messages": [HumanMessage(content="hi")], "selected_tool_ids": []}
            config = _make_config()
            store = MagicMock()

            with patch(f"{_MOD}.ainvoke_llm") as mock_ainvoke:
                result = await _agent_node(builder).afunc(state, config, store=store)

        call_kwargs = exec_mock.wrap_model_invocation.await_args.kwargs
        assert call_kwargs["model"] is configured
        assert call_kwargs["state"] is before_state
        assert call_kwargs["config"] is config
        assert call_kwargs["store"] is store
        assert call_kwargs["tools"] == []
        invoke_fn = call_kwargs["invoke_fn"]
        assert invoke_fn.func is mock_ainvoke
        assert invoke_fn.args == (bound,)
        assert invoke_fn.keywords == {"fallback": None, "config": config, "label": "main_agent"}
        mock_ainvoke.assert_not_awaited()
        assert result == {"messages": [wrapped_response]}


# ---------------------------------------------------------------------------
# should_continue
# ---------------------------------------------------------------------------


class TestShouldContinue:
    def test_no_tool_calls_returns_end(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(messages=[AIMessage(content="done")])

        assert _should_continue(builder)(state, store=MagicMock()) == END

    def test_no_tool_calls_with_end_hooks(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def hook(state: Any, config: Any, store: Any) -> Any:
            return state

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )
        state = _make_state(messages=[AIMessage(content="done")])

        assert _should_continue(builder)(state, store=MagicMock()) == "end_graph_hooks"

    def test_last_message_not_ai_returns_end(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        state = _make_state(
            messages=[
                AIMessage(content="", tool_calls=[{"id": "tc1", "name": "x", "args": {}}]),
                HumanMessage(content="resumed"),
            ]
        )

        assert _should_continue(builder)(state, store=MagicMock()) == END

    def test_finish_task_call_routed_to_finish_node(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        finish_calls = [
            {"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "done"}},
        ]

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        msg = AIMessage(content="", tool_calls=finish_calls)
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert result.node == FINISH_TASK_NAME
        assert result.arg == msg.tool_calls

    def test_finish_task_wins_over_other_calls(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        finish_call = {"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "done"}}
        other_call = {"id": "tc2", "name": "other_tool", "args": {}}

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        msg = AIMessage(content="", tool_calls=[finish_call, other_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert result.node == FINISH_TASK_NAME
        assert result.arg == [msg.tool_calls[0]]

    def test_retrieve_tools_call_routed_to_select_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        retrieve_call = {"id": "tc1", "name": "_retrieve_func", "args": {"query": "x"}}

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)
        msg = AIMessage(content="", tool_calls=[retrieve_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert len(result) == 1
        assert result[0].node == "select_tools"
        assert result[0].arg == msg.tool_calls

    def test_bound_tool_call_routed_to_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        bound_call = {"id": "tc1", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[bound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert len(result) == 1
        assert result[0].node == "tools"
        assert result[0].arg["__type"] == "tool_call_with_context"
        assert result[0].arg["tool_call"]["name"] == "dummy_tool_a"
        assert result[0].arg["state"] == state

    def test_unbound_call_routed_to_reject(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        unbound_call = {"id": "tc1", "name": "unknown_tool", "args": {}}

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        msg = AIMessage(content="", tool_calls=[unbound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert len(result) == 1
        assert result[0].node == "reject_unbound_tools"
        assert result[0].arg == msg.tool_calls

    def test_mixed_bound_and_unbound_calls(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        bound_call = {"id": "tc1", "name": "dummy_tool_a", "args": {}}
        unbound_call = {"id": "tc2", "name": "unknown_tool", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[bound_call, unbound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools", "reject_unbound_tools"]
        assert result[0].arg["tool_call"]["name"] == "dummy_tool_a"
        assert result[1].arg == [msg.tool_calls[1]]

    def test_retrieve_and_bound_calls_fan_out_in_order(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        retrieve_call = {"id": "tc1", "name": "_retrieve_func", "args": {"query": "x"}}
        bound_call = {"id": "tc2", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(
            llm,
            registry,
            retrieve_tools_function=_retrieve_func,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[retrieve_call, bound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["select_tools", "tools"]
        assert result[0].arg == [msg.tool_calls[0]]
        assert result[1].arg["tool_call"]["name"] == "dummy_tool_a"

    def test_unbound_then_bound_call_fan_out_in_order(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        unbound_call = {"id": "tc1", "name": "unknown_tool", "args": {}}
        bound_call = {"id": "tc2", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[unbound_call, bound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools", "reject_unbound_tools"]
        assert result[0].arg["tool_call"]["name"] == "dummy_tool_a"
        assert result[1].arg == [msg.tool_calls[0]]

    def test_retrieve_and_unbound_calls_fan_out_in_order(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        retrieve_call = {"id": "tc1", "name": "_retrieve_func", "args": {"query": "x"}}
        unbound_call = {"id": "tc2", "name": "unknown_tool", "args": {}}

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)
        msg = AIMessage(content="", tool_calls=[retrieve_call, unbound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["select_tools", "reject_unbound_tools"]
        assert result[0].arg == [msg.tool_calls[0]]
        assert result[1].arg == [msg.tool_calls[1]]

    def test_hyphenated_call_name_canonicalized_to_bound_tool(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dash_tool)
        hyphen_call = {"id": "tc1", "name": "dash_tool", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dash-tool"],
        )
        msg = AIMessage(content="", tool_calls=[hyphen_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert len(result) == 1
        assert result[0].node == "tools"
        assert msg.tool_calls[0]["name"] == "dash-tool"

    def test_already_hyphenated_call_name_canonicalized(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dash_tool)
        hyphen_call = {"id": "tc1", "name": "dash-tool", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dash-tool"],
        )
        msg = AIMessage(content="", tool_calls=[hyphen_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools"]

    def test_state_without_selected_tool_ids_key(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        bound_call = {"id": "tc1", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )
        msg = AIMessage(content="", tool_calls=[bound_call])
        state = {"messages": [msg]}

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools"]

    def test_selected_tool_ids_count_as_bound(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        bound_call = {"id": "tc1", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        msg = AIMessage(content="", tool_calls=[bound_call])
        state = _make_state(messages=[msg], selected_tool_ids=["dummy_tool_a"])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools"]

    def test_mixed_hyphen_call_name_canonicalized(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(hyphenated_tool)
        mixed_call = {"id": "tc1", "name": "a_b-c", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["a-b-c"],
        )
        msg = AIMessage(content="", tool_calls=[mixed_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools"]
        assert msg.tool_calls[0]["name"] == "a-b-c"

    def test_middleware_tool_name_counts_as_bound(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry()
        mw = MagicMock()
        mw.tools = [dummy_tool_a]
        bound_call = {"id": "tc1", "name": "dummy_tool_a", "args": {}}

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )
        msg = AIMessage(content="", tool_calls=[bound_call])
        state = _make_state(messages=[msg])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["tools"]

    def test_latest_tool_calling_message_wins(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        earlier_call = {"id": "tc0", "name": FINISH_TASK_NAME, "args": {}}
        later_call = {"id": "tc2", "name": FINISH_TASK_NAME, "args": {"result": "later"}}
        non_finish_call = {"id": "tc1", "name": "other_tool", "args": {}}

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        msg = AIMessage(content="", tool_calls=[non_finish_call, later_call])
        state = _make_state(
            messages=[
                AIMessage(content="", tool_calls=[earlier_call]),
                HumanMessage(content="resumed"),
                msg,
            ]
        )

        result = _should_continue(builder)(state, store=MagicMock())
        assert result.node == FINISH_TASK_NAME
        assert result.arg == [msg.tool_calls[1]]

    def test_retrieve_tools_call_skipped_in_dispatch(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        retrieve_call = {"id": "tc1", "name": "_retrieve_func", "args": {"query": "x"}}

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)
        state = _make_state(messages=[AIMessage(content="", tool_calls=[retrieve_call])])

        result = _should_continue(builder)(state, store=MagicMock())
        assert [s.node for s in result] == ["select_tools"]


# ---------------------------------------------------------------------------
# reject_unbound_tools
# ---------------------------------------------------------------------------


class TestRejectUnboundTools:
    def test_exact_message_content_and_fields(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        reject_node = builder.nodes["reject_unbound_tools"].runnable
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]

        result = reject_node.func(tool_calls, store=MagicMock())
        assert result == {
            "messages": [
                ToolMessage(
                    content=(
                        "Tool 'missing_tool' is not bound. "
                        "You must call retrieve_tools(exact_tool_names=['missing_tool']) "
                        "to bind it before calling it."
                    ),
                    tool_call_id="tc1",
                    name="missing_tool",
                )
            ]
        }

    def test_multiple_calls_in_order(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        reject_node = builder.nodes["reject_unbound_tools"].runnable
        tool_calls = [
            {"id": "tc1", "name": "missing_a"},
            {"id": "tc2", "name": "missing_b"},
        ]

        result = reject_node.func(tool_calls, store=MagicMock())
        assert [m.tool_call_id for m in result["messages"]] == ["tc1", "tc2"]
        assert "missing_a" in result["messages"][0].content
        assert "missing_b" in result["messages"][1].content

    @pytest.mark.asyncio
    async def test_areject_unbound_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        reject_node = builder.nodes["reject_unbound_tools"].runnable
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]

        result = await reject_node.afunc(tool_calls, store=MagicMock())
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_call_id == "tc1"
        assert "not bound" in result["messages"][0].content


# ---------------------------------------------------------------------------
# finish_task node
# ---------------------------------------------------------------------------


class TestFinishTaskNode:
    def test_with_result_arg(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "42"}}]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert result == {
            "messages": [ToolMessage(content="42", tool_call_id="tc1", name=FINISH_TASK_NAME)]
        }

    def test_without_result_arg_defaults(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc1", "name": FINISH_TASK_NAME, "args": {}}]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert result["messages"][0].content == "Task completed."

    def test_none_result_defaults(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": None}}]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert result["messages"][0].content == "Task completed."

    def test_call_without_args_or_id(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"name": FINISH_TASK_NAME}]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert result == {
            "messages": [
                ToolMessage(content="Task completed.", tool_call_id="", name=FINISH_TASK_NAME)
            ]
        }

    def test_non_string_result_str_coerced(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [
            {"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": {"summary": "done"}}}
        ]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert result["messages"][0].content == "{'summary': 'done'}"

    def test_multiple_calls_in_order(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [
            {"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "a"}},
            {"id": "tc2", "name": FINISH_TASK_NAME, "args": {}},
        ]

        result = finish_node.func(tool_calls, store=MagicMock())
        assert [m.content for m in result["messages"]] == ["a", "Task completed."]
        assert [m.tool_call_id for m in result["messages"]] == ["tc1", "tc2"]

    @pytest.mark.asyncio
    async def test_afinish_task_node(self) -> None:
        from app.constants.general import FINISH_TASK_NAME
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)
        finish_node = builder.nodes[FINISH_TASK_NAME].runnable
        tool_calls = [{"id": "tc1", "name": FINISH_TASK_NAME, "args": {"result": "7"}}]

        result = await finish_node.afunc(tool_calls, store=MagicMock())
        assert result["messages"][0].content == "7"


# ---------------------------------------------------------------------------
# end_graph_hooks node
# ---------------------------------------------------------------------------


class TestEndGraphHooksNode:
    def test_sync_hook_executed_with_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        hook = lambda state, config, store: state  # noqa: E731
        hook_result = _make_state(messages=[AIMessage(content="final")])

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )
        state = _make_state(messages=[AIMessage(content="done")])
        config = _make_config()
        store = MagicMock()

        with patch(f"{_MOD}.sync_execute_hooks", return_value=hook_result) as mock_hooks:
            result = builder.nodes["end_graph_hooks"].runnable.func(state, config, store=store)

        mock_hooks.assert_called_once_with([hook], state, config, store)
        assert result == hook_result

    @pytest.mark.asyncio
    async def test_async_hook_executed_with_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        hook = lambda state, config, store: state  # noqa: E731
        hook_result = _make_state(messages=[AIMessage(content="final")])

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            end_graph_hooks=[hook],
        )
        state = _make_state(messages=[AIMessage(content="done")])
        config = _make_config()
        store = MagicMock()

        with patch(f"{_MOD}.execute_hooks", new=AsyncMock(return_value=hook_result)) as mock_hooks:
            result = await builder.nodes["end_graph_hooks"].runnable.afunc(
                state, config, store=store
            )

        mock_hooks.assert_awaited_once_with([hook], state, config, store)
        assert result == hook_result


# ---------------------------------------------------------------------------
# select_tools (sync + async)
# ---------------------------------------------------------------------------


def _retrieve_func_with_store(query: str, *, store: Annotated[BaseStore, InjectedStore]) -> list[str]:
    """Retrieve tools."""
    return ["dummy_tool_a"]


class TestSelectTools:
    def test_kwargs_inject_store_and_user_id(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"tools_to_bind": ["dummy_tool_a"], "response": []}
        store = MagicMock()

        with (
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool),
            patch(f"{_MOD}.get_store_arg", return_value="store"),
        ):
            builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]
        config = _make_config(user_id="u1")

        select_node.func(tool_calls, config, store=store)

        mock_tool.invoke.assert_called_once_with(
            {"query": "test", "store": store, "user_id": "u1"},
            config=config,
        )

    def test_kwargs_without_user_id(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"tools_to_bind": [], "response": []}
        store = MagicMock()

        with (
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool),
            patch(f"{_MOD}.get_store_arg", return_value="store"),
        ):
            builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]
        config = _make_config()

        select_node.func(tool_calls, config, store=store)

        mock_tool.invoke.assert_called_once_with({"query": "test", "store": store}, config=config)

    def test_config_none_passes_no_extra_kwargs(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mock_tool = MagicMock()
        mock_tool.invoke.return_value = {"tools_to_bind": [], "response": []}
        store = MagicMock()

        with (
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool),
            patch(f"{_MOD}.get_store_arg", return_value="store"),
        ):
            builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func)

        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]

        select_node.func(tool_calls, None, store=store)

        mock_tool.invoke.assert_called_once_with({"query": "test", "store": store}, config=None)

    def test_dict_result_exact(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a", "subagent:x"]}

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]

        result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert result == {
            "messages": [
                ToolMessage(
                    content="Available tools: ['dummy_tool_a', 'subagent:x']",
                    tool_call_id="tc1",
                )
            ],
            "selected_tool_ids": ["dummy_tool_a"],
        }

    def test_dict_result_with_missing_keys(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {}

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert result == {
            "messages": [ToolMessage(content="Available tools: []", tool_call_id="tc1")],
            "selected_tool_ids": [],
        }

    def test_list_result_deduped_and_subagent_filtered(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a", "dummy_tool_a", "subagent:gmail", 1, None]

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert result == {
            "messages": [
                ToolMessage(
                    content="Available tools: ['dummy_tool_a', 'subagent:gmail']",
                    tool_call_id="tc1",
                )
            ],
            "selected_tool_ids": ["dummy_tool_a"],
        }

    def test_dict_tools_to_bind_filters_subagent_and_non_str(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {
                "tools_to_bind": ["dummy_tool_a", "subagent:gmail", 1],
                "response": ["subagent:gmail"],
            }

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert result["selected_tool_ids"] == ["dummy_tool_a"]
        assert result["messages"][0].content == "Available tools: ['subagent:gmail']"

    def test_multiple_tool_calls_keyed_by_id(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> list:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [
            {"id": "tc1", "args": {}},
            {"id": "tc2", "args": {}},
        ]

        result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert [m.tool_call_id for m in result["messages"]] == ["tc1", "tc2"]
        assert result["selected_tool_ids"] == ["dummy_tool_a", "dummy_tool_a"]

    def test_format_selected_tools_called_with_exact_args(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {
                "tools_to_bind": ["dummy_tool_a", "subagent:gmail", "subagent:gmail"],
                "response": ["dummy_tool_a", "subagent:gmail"],
            }

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        with patch(
            f"{_MOD}.format_selected_tools",
            side_effect=[("response_messages", "response_ids"), ("bind_messages", "bind_ids")],
        ) as mock_fmt:
            result = select_node.func(tool_calls, _make_config(), store=MagicMock())

        assert mock_fmt.call_args_list == [
            call({"tc1": ["dummy_tool_a", "subagent:gmail"]}, registry),
            call({"tc1": ["dummy_tool_a"]}, registry),
        ]
        assert result == {"messages": "response_messages", "selected_tool_ids": "bind_ids"}

    def test_real_store_injection_end_to_end(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, retrieve_tools_function=_retrieve_func_with_store)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "find me"}}]
        store = InMemoryStore()

        result = select_node.func(tool_calls, _make_config(user_id="u1"), store=store)

        assert result["selected_tool_ids"] == ["dummy_tool_a"]

    @pytest.mark.asyncio
    async def test_aselect_tools_kwargs_and_result(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)
        mock_tool = MagicMock()
        mock_tool.ainvoke = AsyncMock(
            return_value={"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a"]}
        )
        store = MagicMock()

        with (
            patch(f"{_MOD}.StructuredTool.from_function", return_value=mock_tool),
            patch(f"{_MOD}.get_store_arg", return_value="store"),
        ):
            builder = create_agent(llm, registry, retrieve_tools_coroutine=_retrieve_coro)

        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]
        config = _make_config(user_id="u1")

        result = await select_node.afunc(tool_calls, config, store=store)

        mock_tool.ainvoke.assert_awaited_once_with(
            {"query": "test", "store": store, "user_id": "u1"},
            config=config,
        )
        assert result == {
            "messages": [
                ToolMessage(content="Available tools: ['dummy_tool_a']", tool_call_id="tc1")
            ],
            "selected_tool_ids": ["dummy_tool_a"],
        }

    @pytest.mark.asyncio
    async def test_aselect_dict_result_with_missing_keys(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {}

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        result = await select_node.afunc(tool_calls, _make_config(), store=MagicMock())

        assert result == {
            "messages": [ToolMessage(content="Available tools: []", tool_call_id="tc1")],
            "selected_tool_ids": [],
        }

    @pytest.mark.asyncio
    async def test_aselect_subagent_prefix_filtered_from_bind(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(**kwargs: Any) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a", "subagent:gmail"]

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {}}]

        result = await select_node.afunc(tool_calls, _make_config(), store=MagicMock())

        assert result == {
            "messages": [
                ToolMessage(
                    content="Available tools: ['dummy_tool_a', 'subagent:gmail']",
                    tool_call_id="tc1",
                )
            ],
            "selected_tool_ids": ["dummy_tool_a"],
        }

    @pytest.mark.asyncio
    async def test_aselect_tools_real_coroutine(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(query: str, *, store: Annotated[BaseStore, InjectedStore]) -> list[str]:
            """Retrieve tools."""
            return ["dummy_tool_a"]

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)
        select_node = builder.nodes["select_tools"].runnable
        tool_calls = [{"id": "tc1", "args": {"query": "find me"}}]

        result = await select_node.afunc(tool_calls, _make_config(), store=InMemoryStore())

        assert result["selected_tool_ids"] == ["dummy_tool_a"]
