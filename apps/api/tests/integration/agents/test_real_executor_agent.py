"""Integration tests for the executor agent graph."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
import pytest

from app.agents.prompts.todo_prompts import TODO_SYSTEM_PROMPT
from app.agents.templates.agent_template import get_executor_prompt
from app.agents.tools.todo_tools import create_todo_tools
from tests.helpers import create_fake_llm

# ---------------------------------------------------------------------------
# Helpers / shared patches
# ---------------------------------------------------------------------------


def _make_stub_tool(name: str):
    """Create a minimal stub tool with the given name."""

    def _stub(query: str = "") -> str:
        return f"stub:{name}"

    _stub.__name__ = name
    _stub.__doc__ = f"Stub for {name}."
    return tool(_stub)


def _make_mock_tool_registry():
    """Return a minimal ToolRegistry-like mock with the attributes build_executor_graph accesses.

    Stubs every non-todo tool in EXECUTOR_INITIAL_TOOL_IDS, so the
    test stays resilient to changes in the initial tool set (e.g. vfs_cmd being
    added or removed) without hard-coding specific tool names.
    """
    from app.agents.core.graph_builder.build_graph import EXECUTOR_INITIAL_TOOL_IDS
    from app.agents.tools.todo_tools import TODO_TOOL_NAMES

    # Todo tools are injected by build_executor_graph itself, so they do NOT
    # come from the ToolRegistry mock.
    injected_by_graph = TODO_TOOL_NAMES

    tool_dict = {
        tid: _make_stub_tool(tid)
        for tid in EXECUTOR_INITIAL_TOOL_IDS
        if tid not in injected_by_graph
    }

    registry = MagicMock()
    registry.get_tool_dict.return_value = tool_dict
    registry.get_category_by_space.return_value = None
    registry._categories = {}
    return registry


def _make_mock_store():
    """Return a real InMemoryStore so graph compilation succeeds."""
    return InMemoryStore()


@pytest.mark.integration
async def test_the_built_executor_graph_answers_a_turn() -> None:
    """build_executor_graph, with only its tool registry, store and checkpointer faked, runs a turn to the reply."""
    from app.agents.core.graph_builder.build_graph import build_executor_graph

    with (
        patch(
            "app.agents.core.graph_builder.build_graph.get_tool_registry",
            new=AsyncMock(return_value=_make_mock_tool_registry()),
        ),
        patch(
            "app.agents.core.graph_builder.build_graph.get_tools_store",
            new=AsyncMock(return_value=_make_mock_store()),
        ),
        patch(
            "app.agents.core.graph_builder.build_graph.get_checkpointer_manager",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with build_executor_graph(
            chat_llm=create_fake_llm(["I am the executor", "Confirmed: nothing else to do"]),
            in_memory_checkpointer=True,
        ) as graph:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(content="what can you do?")]},
                config={"configurable": {"thread_id": str(uuid4())}},
            )

    # The completion check asks once more before the executor may finish; the second reply ends the turn.
    replies = [m.content for m in result["messages"] if isinstance(m, AIMessage)]
    assert replies == ["I am the executor", "Confirmed: nothing else to do"]
    assert isinstance(result["messages"][-1], AIMessage)


@pytest.mark.integration
class TestTodoTools:
    """The todo tools, their instructions in the executor prompt, and the plan each result states."""

    def test_executor_static_prompt_carries_the_todo_instructions(self):
        """The todo instructions ride the executor's static prompt, not a per-call message."""
        assert TODO_SYSTEM_PROMPT in get_executor_prompt()

    async def test_plan_tasks_result_states_the_plan(self):
        """plan_tasks' ToolMessage carries the rendered plan, so the thread holds the plan where it was set."""
        plan_tasks = next(t for t in create_todo_tools(source="executor") if t.name == "plan_tasks")
        result = await plan_tasks.ainvoke(
            {
                "type": "tool_call",
                "id": "call-plan",
                "name": "plan_tasks",
                "args": {
                    "tasks": [
                        {"content": "Step 1: complete the task"},
                        {"content": "Step 2: report back"},
                    ]
                },
            }
        )

        assert isinstance(result, Command)
        update = cast(dict[str, Any], result.update)
        todos = update["todos"]
        (message,) = update["messages"]
        assert isinstance(message, ToolMessage)
        assert message.tool_call_id == "call-plan"
        content = str(message.content)
        assert "## Current Tasks" in content
        assert f"({todos[0]['id']}) Step 1: complete the task" in content
        assert f"({todos[1]['id']}) Step 2: report back" in content

    def test_todo_tool_names_constant_is_correct(self):
        """TODO_TOOL_NAMES must match the actual tools returned by create_todo_tools."""
        from app.agents.tools.todo_tools import TODO_TOOL_NAMES, create_todo_tools

        tools = create_todo_tools(source="executor")
        actual_names = {t.name for t in tools}
        assert actual_names == TODO_TOOL_NAMES, (
            f"TODO_TOOL_NAMES {TODO_TOOL_NAMES} does not match "
            f"tools from create_todo_tools: {actual_names}"
        )
        # plan_tasks must always be present
        assert "plan_tasks" in TODO_TOOL_NAMES
