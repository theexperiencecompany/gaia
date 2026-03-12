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
- LLM: FakeMessagesListChatModel
- Store: InMemoryStore (no ChromaDB)
- Checkpointer: MemorySaver (no PostgreSQL)
- No real database or scheduler calls

DELETE ``app/agents/tools/todo_tools.py`` → these tests FAIL.
DELETE ``app/override/langgraph_bigtool/create_agent.py`` → these tests FAIL.
DELETE ``app/agents/core/nodes/filter_messages.py`` → these tests FAIL.
"""

import pytest
from tests.helpers import BindableToolsFakeModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.tools.todo_tools import (
    TODO_TOOL_NAMES,
    create_todo_pre_model_hook,
    create_todo_tools,
)
from tests.e2e.conftest import build_gaia_test_graph


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

    async def test_add_task_tool_appends_to_todos(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks must append a new todo to existing todos in state.

        Sequence: plan_tasks creates 1 task → update_tasks adds a second → verify 2 todos.
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
                # Turn 2: add another task via update_tasks
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_add_001",
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
            f"Expected 2 todos after plan_tasks + update_tasks, got {len(todos)}"
        )
        todo_contents = [t["content"] for t in todos]
        assert "Initial task" in todo_contents
        assert "Bonus task discovered later" in todo_contents

    async def test_mark_task_tool_updates_status(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks must update the status of an existing todo by ID.

        Uses a SINGLE compiled graph with MemorySaver and the SAME thread_id for
        both turns so that real LangGraph checkpoint continuity is exercised:
          Turn 1: plan_tasks creates a task and persists it in checkpointed state.
          Turn 2 (same graph, same thread): update_tasks reads the task ID from
              checkpointed todos and marks it completed.

        This ensures the test breaks if the graph loses state between invocations.
        """
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        # The fake LLM is pre-programmed with responses for BOTH turns.
        # Turn 1 consumes the first two responses (plan_tasks call + final reply).
        # Turn 2 consumes the next two (update_tasks call + final reply) — but
        # update_tasks's task_id is a placeholder here; we patch it after Turn 1.
        #
        # Because BindableToolsFakeModel cycles through a fixed response list we
        # supply all four responses up-front and use a sentinel task_id that we
        # replace after inspecting Turn-1 output.
        SENTINEL_ID = "SENTINEL"

        fake_llm = BindableToolsFakeModel(
            responses=[
                # Turn 1 — plan one task
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
                # Turn 2 — mark task completed via update_tasks (task_id filled in below)
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_mark_001",
                            "name": "update_tasks",
                            "args": {
                                "updates": [
                                    {"task_id": SENTINEL_ID, "status": "completed"}
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task marked as completed."),
            ]
        )

        # Single graph, single MemorySaver — both turns share state via thread_id.
        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        # Turn 1: plan a task and capture the generated ID from checkpointed state.
        result_turn1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan a task")]},
            config=thread_config,
        )
        todos_after_plan = result_turn1.get("todos", [])
        assert len(todos_after_plan) == 1, (
            f"Turn 1 must produce exactly 1 todo, got {len(todos_after_plan)}"
        )
        task_id = todos_after_plan[0]["id"]

        # Patch the sentinel so the pre-programmed Turn-2 tool call uses the real ID.
        turn2_ai: AIMessage = fake_llm.responses[2]  # type: ignore[index]
        turn2_ai.tool_calls[0]["args"]["updates"][0]["task_id"] = task_id

        # Turn 2: same graph, same thread — update_tasks reads todos from checkpoint.
        result_turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Mark the task done")]},
            config=thread_config,
        )
        todos_after_mark = result_turn2.get("todos", [])
        assert len(todos_after_mark) >= 1, (
            "Turn 2 must preserve at least one todo in state"
        )
        completed = [t for t in todos_after_mark if t["id"] == task_id]
        assert len(completed) == 1, (
            f"Todo with id {task_id!r} must still be present after update_tasks"
        )
        assert completed[0]["status"] == "completed", (
            f"update_tasks must update status to 'completed', got "
            f"'{completed[0]['status']}'"
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

    async def test_todo_pre_model_hook_injects_task_context_into_system_message(
        self, thread_config, in_memory_store, memory_saver
    ):
        """create_todo_pre_model_hook must inject todo context into the system prompt.

        Instead of calling the hook directly, this test invokes the real compiled
        GAIA graph so that the hook is exercised through the official wiring path
        (create_agent -> acall_model -> execute_hooks).

        A capturing fake LLM records the exact messages list it receives from
        acall_model.  We then assert that the SystemMessage seen by the model
        contains the todo task context injected by create_todo_pre_model_hook.

        This test breaks if:
        - create_todo_pre_model_hook is removed from the pre_model_hooks list, OR
        - the hook stops appending todo context to the SystemMessage.
        """
        from typing import Any

        from langchain_core.language_models.fake_chat_models import (
            FakeMessagesListChatModel,
        )
        from langchain_core.messages import BaseMessage
        from langchain_core.outputs import ChatResult

        captured_inputs: list[list[BaseMessage]] = []

        class CapturingFakeModel(FakeMessagesListChatModel):
            """Fake LLM that records the messages list on every invocation."""

            def bind_tools(self, tools: Any, **kwargs: Any) -> "CapturingFakeModel":  # type: ignore[override]
                return self

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> ChatResult:
                captured_inputs.append(list(messages))
                return super()._generate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )

            async def _agenerate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> ChatResult:
                captured_inputs.append(list(messages))
                return await super()._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )

        from typing import cast

        from app.agents.core.nodes.filter_messages import filter_messages_node
        from app.agents.core.nodes.manage_system_prompts import (
            manage_system_prompts_node,
        )
        from app.override.langgraph_bigtool.hooks import HookType

        todo_hooks = [create_todo_pre_model_hook(source="test")]

        fake_llm = CapturingFakeModel(responses=[AIMessage(content="Done.")])

        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        # Build graph with all three hooks: filter → manage_system_prompts → todo_pre_model
        from app.override.langgraph_bigtool.create_agent import create_agent

        pre_model_hooks: list[HookType] = [
            cast(HookType, filter_messages_node),
            cast(HookType, manage_system_prompts_node),
            cast(HookType, todo_hooks[0]),
        ]

        builder = create_agent(
            llm=fake_llm,
            agent_name="test_agent",
            tool_registry=tool_registry,
            disable_retrieve_tools=True,
            initial_tool_ids=list(tool_registry.keys()),
            middleware=None,
            pre_model_hooks=pre_model_hooks,
        )
        graph = builder.compile(checkpointer=memory_saver, store=in_memory_store)

        # Invoke with a system message and a pre-seeded todo in state so the hook
        # has something to inject.
        await graph.ainvoke(
            {
                "messages": [
                    SystemMessage(content="You are a helpful assistant."),
                    HumanMessage(content="Do the work"),
                ],
                "todos": [
                    {
                        "id": "abc123",
                        "content": "Write the report",
                        "status": "in_progress",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
            },
            config=thread_config,
        )

        assert captured_inputs, "CapturingFakeModel must have been called at least once"

        # The first call to the model is the one where hooks ran.
        messages_seen_by_model = captured_inputs[0]
        system_messages_seen = [
            m for m in messages_seen_by_model if isinstance(m, SystemMessage)
        ]
        assert system_messages_seen, (
            "The model must receive at least one SystemMessage after hooks ran"
        )
        combined_content = "\n".join(m.content for m in system_messages_seen)
        assert "Write the report" in combined_content, (
            "create_todo_pre_model_hook must inject todo content into the system message "
            f"seen by the model. Got: {combined_content!r}"
        )
        assert "abc123" in combined_content, (
            "create_todo_pre_model_hook must inject todo ID into the system message "
            f"seen by the model. Got: {combined_content!r}"
        )
