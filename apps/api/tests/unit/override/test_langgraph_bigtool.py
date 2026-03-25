"""Tests for app.override.langgraph_bigtool.create_agent."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool


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
    configured.bind_tools.return_value = bound
    llm.with_config.return_value = configured
    return llm


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


# ---------------------------------------------------------------------------
# create_agent — basic construction
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_returns_state_graph(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_retrieve_tools_coroutine(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_retrieve_tools_function(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_both_retrieve_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_initial_tool_ids(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a, dummy_tool_b)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            initial_tool_ids=["dummy_tool_a"],
        )

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_end_graph_hooks(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_with_middleware(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_middleware_non_basetool_filtered(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)

    def test_middleware_without_tools_attr(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        mw = MagicMock(spec=[])  # no tools attribute

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
            middleware=[mw],
        )

        from langgraph.graph import StateGraph

        assert isinstance(builder, StateGraph)


# ---------------------------------------------------------------------------
# Inner function tests via graph node extraction
# ---------------------------------------------------------------------------


class TestCallModel:
    """Test the call_model inner function behavior indirectly."""

    def test_sync_call_model_raises_with_middleware(self) -> None:
        """When middleware is configured, sync call_model should raise RuntimeError."""
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

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        with pytest.raises(RuntimeError, match="sync execution was requested"):
            agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]

    def test_sync_call_model_without_middleware(self) -> None:
        """Sync call_model should work without middleware."""
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(
            llm,
            registry,
            disable_retrieve_tools=True,
        )

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]
        assert "messages" in result

    def test_sync_call_model_empty_response_gets_default(self) -> None:
        """Empty model response should get default content."""
        from app.override.langgraph_bigtool.create_agent import create_agent

        empty_response = AIMessage(content="", tool_calls=[])
        llm = MagicMock()
        configured = MagicMock()
        bound = MagicMock()
        bound.invoke.return_value = empty_response
        configured.bind_tools.return_value = bound
        llm.with_config.return_value = configured

        registry = _make_tool_registry()
        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]
        assert result["messages"][0].content == "Empty response from model."

    def test_sync_call_model_comms_agent_appends_breaker(self) -> None:
        """comms_agent should append NEW_MESSAGE_BREAKER."""
        from app.constants.general import NEW_MESSAGE_BREAKER
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        result = agent_node.runnable.func(state, config, store=store)  # type: ignore[union-attr]
        assert result["messages"][0].content.endswith(NEW_MESSAGE_BREAKER)


class TestAcallModel:
    @pytest.mark.asyncio
    async def test_acall_model_basic(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        config = _make_config()
        store = MagicMock()

        result = await agent_node.runnable.afunc(state, config, store=store)  # type: ignore[union-attr]
        assert "messages" in result

    @pytest.mark.asyncio
    async def test_acall_model_with_middleware_hooks(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry()

        mw = MagicMock()
        mw.tools = []

        with patch(
            "app.override.langgraph_bigtool.create_agent.MiddlewareExecutor"
        ) as mock_me_cls:
            mock_me = AsyncMock()
            mock_me.execute_before_model = AsyncMock(return_value=_make_state())
            mock_me.has_wrap_model_call.return_value = False
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
            result = await agent_node.runnable.afunc(  # type: ignore[union-attr]
                state, _make_config(), store=MagicMock()
            )
            assert "messages" in result

    @pytest.mark.asyncio
    async def test_acall_model_empty_response(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        empty_response = AIMessage(content="", tool_calls=[])
        llm = MagicMock()
        configured = MagicMock()
        bound = MagicMock()
        bound.ainvoke = AsyncMock(return_value=empty_response)
        configured.bind_tools.return_value = bound
        llm.with_config.return_value = configured

        registry = _make_tool_registry()
        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        agent_node = builder.nodes["agent"]
        state = _make_state()
        result = await agent_node.runnable.afunc(  # type: ignore[union-attr]
            state, _make_config(), store=MagicMock()
        )
        assert result["messages"][0].content == "Empty response from model."

    @pytest.mark.asyncio
    async def test_acall_model_comms_agent_appends_breaker(self) -> None:
        from app.constants.general import NEW_MESSAGE_BREAKER
        from app.override.langgraph_bigtool.create_agent import create_agent

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
        result = await agent_node.runnable.afunc(  # type: ignore[union-attr]
            state, _make_config(), store=MagicMock()
        )
        assert result["messages"][0].content.endswith(NEW_MESSAGE_BREAKER)


# ---------------------------------------------------------------------------
# should_continue
# ---------------------------------------------------------------------------


class TestShouldContinue:
    def test_no_tool_calls_returns_end(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent
        from langgraph.graph import END

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        msg = AIMessage(content="done")
        state = _make_state(messages=[msg])
        store = MagicMock()

        branch = builder.branches["agent"]["should_continue"]
        edge_fn = branch.path.func  # type: ignore[attr-defined]
        result = edge_fn(state, store=store)
        assert result == END

    def test_no_tool_calls_with_end_hooks(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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
        edge_fn = branch.path.func  # type: ignore[attr-defined]
        result = edge_fn(state, store=store)
        assert result == "end_graph_hooks"

    def test_bound_tool_calls_routed_to_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        edge_fn = builder.branches["agent"]["should_continue"].path.func  # type: ignore[attr-defined]
        result = edge_fn(state, store=store)
        assert len(result) == 1
        assert result[0].node == "tools"

    def test_unbound_tool_calls_routed_to_reject(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        msg = AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "unknown_tool", "args": {}}],
        )
        state = _make_state(messages=[msg])
        store = MagicMock()

        edge_fn = builder.branches["agent"]["should_continue"].path.func  # type: ignore[attr-defined]
        result = edge_fn(state, store=store)
        has_reject = any(
            getattr(s, "node", None) == "reject_unbound_tools" for s in result
        )
        assert has_reject


# ---------------------------------------------------------------------------
# reject_unbound_tools
# ---------------------------------------------------------------------------


class TestRejectUnboundTools:
    def test_reject_unbound_tools_returns_error_messages(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        reject_node = builder.nodes["reject_unbound_tools"]
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]
        store = MagicMock()

        result = reject_node.runnable.func(tool_calls, store=store)  # type: ignore[union-attr]
        assert len(result["messages"]) == 1
        assert "not bound" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_areject_unbound_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry()

        builder = create_agent(llm, registry, disable_retrieve_tools=True)

        reject_node = builder.nodes["reject_unbound_tools"]
        tool_calls = [{"id": "tc1", "name": "missing_tool"}]
        store = MagicMock()

        result = await reject_node.runnable.afunc(tool_calls, store=store)  # type: ignore[union-attr]
        assert len(result["messages"]) == 1


# ---------------------------------------------------------------------------
# select_tools (sync + async)
# ---------------------------------------------------------------------------


class TestSelectTools:
    def test_select_tools_with_dict_result(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        def my_func(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a"]}

        builder = create_agent(llm, registry, retrieve_tools_function=my_func)  # type: ignore[arg-type]

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {"query": "test"}}]
        config = _make_config()
        store = MagicMock()

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]
        assert "messages" in result
        assert "selected_tool_ids" in result

    def test_select_tools_with_list_result(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]
        assert "dummy_tool_a" in result["selected_tool_ids"]

    def test_select_tools_filters_subagent_prefix(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        result = select_node.runnable.func(tool_calls, config, store=store)  # type: ignore[union-attr]
        bind_ids = result["selected_tool_ids"]
        assert "subagent:gmail" not in bind_ids

    @pytest.mark.asyncio
    async def test_aselect_tools(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

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

        result = await select_node.runnable.afunc(tool_calls, config, store=store)  # type: ignore[union-attr]
        assert "dummy_tool_a" in result["selected_tool_ids"]

    @pytest.mark.asyncio
    async def test_aselect_tools_dict_result(self) -> None:
        from app.override.langgraph_bigtool.create_agent import create_agent

        llm = _make_llm()
        registry = _make_tool_registry(dummy_tool_a)

        async def my_coro(**kwargs: Any) -> dict:
            """Retrieve tools."""
            return {"tools_to_bind": ["dummy_tool_a"], "response": ["dummy_tool_a"]}

        builder = create_agent(llm, registry, retrieve_tools_coroutine=my_coro)  # type: ignore[arg-type]

        select_node = builder.nodes["select_tools"]
        tool_calls = [{"id": "tc1", "args": {}}]
        config = _make_config()
        store = MagicMock()

        result = await select_node.runnable.afunc(tool_calls, config, store=store)  # type: ignore[union-attr]
        assert "dummy_tool_a" in result["selected_tool_ids"]
