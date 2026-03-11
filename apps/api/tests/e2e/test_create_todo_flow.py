"""E2E test: GAIA todo tools (plan_tasks, update_tasks) wired into a real graph.

WHAT THIS TESTS (REAL GAIA CODE):
- ``create_todo_tools`` from ``app.agents.tools.todo_tools`` — the real
  plan_tasks and update_tasks tools used by the executor agent.
- The ``todos`` channel in GAIA's ``State`` (via InjectedState) is updated
  correctly when plan_tasks / update_tasks execute.
- ``filter_messages_node`` and ``manage_system_prompts_node`` run as
  pre-model hooks inside the compiled GAIA graph.
- ``create_agent`` from ``app.override.langgraph_bigtool.create_agent``
  compiles the graph.

Mock surfaces:
- LLM: BindableToolsFakeModel (wraps FakeMessagesListChatModel with bind_tools support)
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)
- No real database or scheduler calls

DELETE ``app/agents/tools/todo_tools.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
DELETE ``app/agents/core/nodes/filter_messages.py`` → these tests FAIL.
"""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.tools.todo_tools import (
    TODO_TOOL_NAMES,
    create_todo_pre_model_hook,
    create_todo_tools,
)
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel, assert_tool_called, extract_tool_calls


@pytest.mark.e2e
class TestCreateTodoFlow:
    """E2E tests for the real GAIA todo tools wired into a compiled agent graph."""

    async def test_plan_tasks_tool_updates_todos_state(
        self, thread_config, in_memory_store, memory_saver
    ):
        """plan_tasks must create todos in graph state via Command(update={'todos': ...}).

        This tests the real plan_tasks tool from create_todo_tools(), which uses
        InjectedState('todos') and returns a Command to update the 'todos' channel
        in the GAIA State.
        """
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_001",
                            "name": "plan_tasks",
                            "args": {
                                "tasks": [
                                    {"content": "Research the topic"},
                                    {"content": "Write the report"},
                                    {"content": "Review and publish"},
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="I've planned 3 tasks for you."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan my research project")]},
            config=thread_config,
        )

        # The 'todos' channel should be populated by the real plan_tasks tool
        todos = result.get("todos", [])
        assert len(todos) == 3, (
            f"plan_tasks must create 3 todos in state, got {len(todos)}. "
            "This confirms the real create_todo_tools() is wired into the graph."
        )
        todo_contents = [t["content"] for t in todos]
        assert "Research the topic" in todo_contents
        assert "Write the report" in todo_contents
        assert "Review and publish" in todo_contents

    async def test_plan_tasks_sets_first_task_in_progress(
        self, thread_config, in_memory_store, memory_saver
    ):
        """plan_tasks must set the first task to 'in_progress' and rest to 'pending'.

        This validates the real plan_tasks business logic from todo_tools.py.
        """
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_002",
                            "name": "plan_tasks",
                            "args": {
                                "tasks": [
                                    {"content": "Step one"},
                                    {"content": "Step two"},
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Tasks planned."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan two steps")]},
            config=thread_config,
        )

        todos = result.get("todos", [])
        assert len(todos) == 2
        assert todos[0]["status"] == "in_progress", (
            "plan_tasks must set first task to in_progress"
        )
        assert todos[1]["status"] == "pending", (
            "plan_tasks must set subsequent tasks to pending"
        )

    async def test_update_tasks_adds_new_task_to_todos(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks must append a new todo to existing todos in state.

        Sequence: plan_tasks creates 1 task → update_tasks adds a second → verify 2 todos.

        update_tasks is the real production tool that replaces the non-existent
        add_task tool. When passed a TaskUpdate without task_id, it appends a
        new task to the current todos list.
        """
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        fake_llm = BindableToolsFakeModel(
            responses=[
                # Turn 1: plan one task
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_add_001",
                            "name": "plan_tasks",
                            "args": {"tasks": [{"content": "Initial task"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                # Turn 2: add another task via update_tasks (no task_id = new task)
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_add_001",
                            "name": "update_tasks",
                            "args": {
                                "updates": [
                                    {"content": "Bonus task discovered later"}
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Added the extra task."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan then add a task")]},
            config=thread_config,
        )

        todos = result.get("todos", [])
        assert len(todos) == 2, (
            f"Expected 2 todos after plan_tasks + update_tasks (add), got {len(todos)}"
        )
        todo_contents = [t["content"] for t in todos]
        assert "Initial task" in todo_contents
        assert "Bonus task discovered later" in todo_contents

    async def test_update_tasks_updates_status_of_existing_task(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks must update the status of an existing todo by ID.

        Sequence: plan_tasks creates a task → read its ID → update_tasks sets it completed.

        update_tasks is the real production tool that replaces the non-existent
        mark_task tool. When passed a TaskUpdate with task_id and status, it
        updates the matching task's status in place.
        """
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        # Phase 1: plan one task and capture its ID
        fake_llm_phase1 = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_mark",
                            "name": "plan_tasks",
                            "args": {"tasks": [{"content": "Task to be completed"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task planned."),
            ]
        )
        config_phase1 = {
            "configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}
        }
        graph_phase1 = build_gaia_test_graph(
            fake_llm=fake_llm_phase1,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )
        result_phase1 = await graph_phase1.ainvoke(
            {"messages": [HumanMessage(content="Plan a task")]},
            config=config_phase1,
        )
        todos_after_plan = result_phase1.get("todos", [])
        assert len(todos_after_plan) == 1
        task_id = todos_after_plan[0]["id"]

        # Phase 2: mark the task completed using update_tasks with its real ID
        fake_llm_phase2 = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_001",
                            "name": "update_tasks",
                            "args": {
                                "updates": [
                                    {"task_id": task_id, "status": "completed"}
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task marked as completed."),
            ]
        )
        config_phase2 = {
            "configurable": {"thread_id": str(uuid4()), "user_id": str(uuid4())}
        }
        graph_phase2 = build_gaia_test_graph(
            fake_llm=fake_llm_phase2,
            tool_registry=tool_registry,
            checkpointer=MemorySaver(),
            store=in_memory_store,
        )
        # Pre-populate todos so update_tasks has something to update
        result_phase2 = await graph_phase2.ainvoke(
            {
                "messages": [HumanMessage(content="Mark the task done")],
                "todos": todos_after_plan,
            },
            config=config_phase2,
        )
        todos_after_update = result_phase2.get("todos", [])
        assert len(todos_after_update) == 1
        assert todos_after_update[0]["status"] == "completed", (
            f"update_tasks must update status to 'completed', got "
            f"'{todos_after_update[0]['status']}'"
        )

    async def test_todo_tool_names_match_registry_constants(self):
        """The tool names in create_todo_tools() must match TODO_TOOL_NAMES constant.

        This test ensures the TODO_TOOL_NAMES set (used by middleware and other
        production code to detect todo tools) stays in sync with what
        create_todo_tools() actually creates.
        """
        todo_tools = create_todo_tools(source="test")
        created_names = {t.name for t in todo_tools}
        assert created_names == TODO_TOOL_NAMES, (
            f"Tool names from create_todo_tools() {created_names} do not match "
            f"TODO_TOOL_NAMES constant {TODO_TOOL_NAMES}. "
            "Update TODO_TOOL_NAMES in todo_tools.py."
        )

    async def test_todo_pre_model_hook_injects_task_context_into_system_message(self):
        """create_todo_pre_model_hook must inject todo context into the system prompt.

        This tests the real pre-model hook factory from todo_tools.py.
        When todos exist in state, the hook appends task context to the
        latest non-memory SystemMessage.
        """
        from unittest.mock import MagicMock

        from tests.e2e.conftest import make_gaia_state, make_mock_store, make_node_config

        hook = create_todo_pre_model_hook(source="test")

        system_msg = SystemMessage(content="You are a helpful assistant.")
        human_msg = HumanMessage(content="Do the work")

        state = make_gaia_state(
            messages=[system_msg, human_msg],
            todos=[
                {
                    "id": "abc123",
                    "content": "Write the report",
                    "status": "in_progress",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        )
        config = make_node_config()
        store = make_mock_store()

        result = hook(state, config, store)

        updated_system = result["messages"][0]
        assert isinstance(updated_system, SystemMessage)
        assert "Write the report" in updated_system.content, (
            "create_todo_pre_model_hook must inject todo content into the system message"
        )
        assert "abc123" in updated_system.content, (
            "create_todo_pre_model_hook must inject todo ID into the system message"
        )
