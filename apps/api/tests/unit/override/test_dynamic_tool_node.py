"""Unit tests for DynamicToolNode's middleware dispatch path.

The middleware branch of ``_afunc`` only runs when a middleware executor is
present AND at least one tool call escapes parent routing — the state
normalization between the two (``_coerce_middleware_state``) is what the
executor and every wrap_tool_call hook consume as their view of graph state.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
import pytest

from app.override.langgraph_bigtool.dynamic_tool_node import DynamicToolNode

pytestmark = pytest.mark.unit


def _echo_registry() -> dict[str, Any]:
    @tool
    def echo(query: str) -> str:
        """Echo back."""
        return query

    return {"echo": echo}


def _make_node() -> tuple[DynamicToolNode, MagicMock]:
    """A DynamicToolNode whose middleware executor claims wrap_tool_call."""
    executor = MagicMock()
    executor.has_wrap_tool_call.return_value = True
    executor.wrap_tool_invocation = AsyncMock(
        return_value=ToolMessage(content="done", tool_call_id="call_1")
    )
    node = DynamicToolNode(_echo_registry(), middleware_executor=executor)
    return node, executor


def _input_with_echo_call() -> dict[str, Any]:
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "echo", "args": {"query": "hi"}, "id": "call_1", "type": "tool_call"}
                ],
            )
        ]
    }


class TestMiddlewareDispatchPath:
    async def test_afunc_routes_plain_tool_calls_through_the_middleware_executor(self):
        node, executor = _make_node()

        result = await node._afunc(_input_with_echo_call(), {}, MagicMock())

        executor.wrap_tool_invocation.assert_awaited_once()
        returned = result["messages"]
        assert len(returned) == 1
        assert isinstance(returned[0], ToolMessage)
        assert returned[0].content == "done"
        assert returned[0].tool_call_id == "call_1"

    async def test_executor_receives_coerced_state_with_a_copied_messages_list(self):
        node, executor = _make_node()
        node_input = _input_with_echo_call()

        await node._afunc(node_input, {}, MagicMock())

        state = executor.wrap_tool_invocation.await_args.kwargs["state"]
        # The coerced state carries a messages channel even when the raw input
        # dict came straight through _extract_state unchanged.
        assert set(state.keys()) >= {"messages"}
        assert len(state["messages"]) == 1
        assert state["messages"][0].tool_calls[0]["name"] == "echo"
        assert state["messages"] is not node_input["messages"]


class TestMiddlewareDispatchPins:
    """Pin the dispatch branches: parent routing, missing executor, Command mix."""

    async def test_all_parent_routed_calls_delegate_to_the_parent_path(self):
        node, executor = _make_node()
        # InjectedState args make "echo" parent-routed for this node.
        object.__setattr__(node, "_injected_args", {"echo": MagicMock(state={"messages": True})})
        with patch.object(DynamicToolNode.__bases__[0], "_afunc", new_callable=AsyncMock) as parent:
            parent.return_value = {"messages": [ToolMessage(content="parent", tool_call_id="c1")]}
            result = await node._afunc(_input_with_echo_call(), {}, MagicMock())

        executor.wrap_tool_invocation.assert_not_awaited()
        assert isinstance(result, dict)
        assert result["messages"][0].content == "parent"

    async def test_mixed_command_results_are_returned_as_a_flat_list(self):
        from langgraph.types import Command

        node, _ = _make_node()
        command = Command(update={"messages": [ToolMessage(content="cmd", tool_call_id="c1")]})
        node._middleware_executor.wrap_tool_invocation = AsyncMock(return_value=command)

        result = await node._afunc(_input_with_echo_call(), {}, MagicMock())

        # Commands must NOT be wrapped in {"messages": ...} — LangGraph handles
        # a bare list containing Commands itself.
        assert isinstance(result, list)

    async def test_tool_messages_only_are_returned_under_the_messages_key(self):
        node, _ = _make_node()
        result = await node._afunc(_input_with_echo_call(), {}, MagicMock())
        assert set(result.keys()) == {"messages"}

    async def test_store_from_runtime_reaches_the_executor(self):
        node, executor = _make_node()
        store = MagicMock()

        class Runtime:
            pass

        runtime = Runtime()
        runtime.store = store

        await node._afunc(_input_with_echo_call(), {}, runtime)

        assert executor.wrap_tool_invocation.await_args.kwargs["store"] is store

    async def test_missing_runtime_store_passes_none(self):
        node, executor = _make_node()

        await node._afunc(_input_with_echo_call(), {}, MagicMock(spec=[]))

        assert executor.wrap_tool_invocation.await_args.kwargs["store"] is None
