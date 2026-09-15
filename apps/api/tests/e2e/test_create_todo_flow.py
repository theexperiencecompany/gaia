"""E2E tests wiring the real plan_tasks/update_tasks tools into a compiled GAIA graph, with a fake LLM and in-memory store/checkpointer."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from app.agents.tools.todo_tools import (
    TODO_TOOL_NAMES,
    create_todo_pre_model_hook,
    create_todo_tools,
)
from tests.e2e.conftest import build_gaia_test_graph
from tests.helpers import BindableToolsFakeModel


def _find_tool_message(messages: list, tool_call_id: str) -> ToolMessage:
    for msg in messages:
        if isinstance(msg, ToolMessage) and msg.tool_call_id == tool_call_id:
            return msg
    raise AssertionError(f"No ToolMessage for tool_call_id {tool_call_id!r} in {messages}")


@pytest.mark.e2e
class TestCreateTodoFlow:
    """E2E tests for the real GAIA todo tools wired into a compiled agent graph."""

    async def test_plan_tasks_tool_updates_todos_state(
        self, thread_config, in_memory_store, memory_saver
    ):
        """plan_tasks must update graph state's 'todos' channel via Command(update=...), using InjectedState('todos')."""
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
        """plan_tasks must set the first task to 'in_progress' and rest to 'pending'."""
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
        assert todos[0]["status"] == "in_progress", "plan_tasks must set first task to in_progress"
        assert todos[1]["status"] == "pending", "plan_tasks must set subsequent tasks to pending"

    async def test_add_task_tool_appends_to_todos(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks appends to existing todos: plan_tasks creates one, update_tasks adds a second, expect two total."""
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
                            "args": {"updates": [{"content": "Bonus task discovered later"}]},
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
        """update_tasks must update status by ID; uses one graph/thread across both turns so checkpoint continuity is actually exercised."""
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        # BindableToolsFakeModel cycles through a fixed response list, so all four
        # responses are supplied up front with a sentinel task_id patched in after Turn 1.
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
                            "args": {"updates": [{"task_id": SENTINEL_ID, "status": "completed"}]},
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
        turn2_ai: AIMessage = fake_llm.responses[2]
        turn2_ai.tool_calls[0]["args"]["updates"][0]["task_id"] = task_id

        # Turn 2: same graph, same thread — update_tasks reads todos from checkpoint.
        result_turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Mark the task done")]},
            config=thread_config,
        )
        todos_after_mark = result_turn2.get("todos", [])
        assert len(todos_after_mark) >= 1, "Turn 2 must preserve at least one todo in state"
        completed = [t for t in todos_after_mark if t["id"] == task_id]
        assert len(completed) == 1, (
            f"Todo with id {task_id!r} must still be present after update_tasks"
        )
        assert completed[0]["status"] == "completed", (
            f"update_tasks must update status to 'completed', got '{completed[0]['status']}'"
        )

    async def test_update_tasks_surfaces_error_for_unknown_task_id(
        self, thread_config, in_memory_store, memory_saver
    ):
        """update_tasks must fail loud on an unknown task_id — silently succeeding would let the model believe untracked work is done."""
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_unknown",
                            "name": "plan_tasks",
                            "args": {"tasks": [{"content": "Real task"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task planned."),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_unknown",
                            "name": "update_tasks",
                            "args": {"updates": [{"task_id": "deadbeef", "status": "completed"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Acknowledged."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result_turn1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan a task")]},
            config=thread_config,
        )
        real_id = result_turn1["todos"][0]["id"]
        assert real_id != "deadbeef"

        result_turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Mark deadbeef done")]},
            config=thread_config,
        )

        tool_msg = _find_tool_message(result_turn2["messages"], "call_update_unknown")
        assert tool_msg.status == "error", (
            "update_tasks must report an unknown task_id as a tool error, not success. "
            f"Got status={tool_msg.status!r} content={tool_msg.content!r}"
        )
        assert "deadbeef" in tool_msg.content, (
            f"The error must name the rejected task_id so the model can correct itself. "
            f"Got: {tool_msg.content!r}"
        )

        todos = result_turn2["todos"]
        assert len(todos) == 1
        assert todos[0]["status"] == "in_progress", (
            "A rejected update must leave existing todo state untouched"
        )

    async def test_update_tasks_rejects_whole_batch_when_one_entry_is_invalid(
        self, thread_config, in_memory_store, memory_saver
    ):
        """An invalid entry must fail the whole batch — partial application would double-apply the valid entry when the model retries."""
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        SENTINEL_ID = "SENTINEL"

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_batch",
                            "name": "plan_tasks",
                            "args": {"tasks": [{"content": "First task"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task planned."),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_batch",
                            "name": "update_tasks",
                            "args": {
                                "updates": [
                                    {"task_id": SENTINEL_ID, "status": "completed"},
                                    {"content": "Discovered task"},
                                    {"task_id": "nosuchid", "status": "in_progress"},
                                ]
                            },
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Acknowledged."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result_turn1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan a task")]},
            config=thread_config,
        )
        real_id = result_turn1["todos"][0]["id"]
        fake_llm.responses[2].tool_calls[0]["args"]["updates"][0]["task_id"] = real_id

        result_turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Update the batch")]},
            config=thread_config,
        )

        tool_msg = _find_tool_message(result_turn2["messages"], "call_update_batch")
        assert tool_msg.status == "error", (
            f"A batch with an invalid entry must be reported as an error. "
            f"Got status={tool_msg.status!r} content={tool_msg.content!r}"
        )

        todos = result_turn2["todos"]
        contents = [t["content"] for t in todos]
        assert "Discovered task" not in contents, (
            "The valid addition must not be applied when a sibling entry is invalid — "
            f"got todos {contents}"
        )
        assert len(todos) == 1
        assert todos[0]["status"] == "in_progress", (
            "The valid status change must not be applied when a sibling entry is invalid"
        )

    async def test_update_tasks_rejects_task_id_without_status(
        self, thread_config, in_memory_store, memory_saver
    ):
        """A task_id with no status is not an update — it must not pass silently."""
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        SENTINEL_ID = "SENTINEL"

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_plan_nostatus",
                            "name": "plan_tasks",
                            "args": {"tasks": [{"content": "Only task"}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Task planned."),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_nostatus",
                            "name": "update_tasks",
                            "args": {"updates": [{"task_id": SENTINEL_ID}]},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Acknowledged."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result_turn1 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Plan a task")]},
            config=thread_config,
        )
        real_id = result_turn1["todos"][0]["id"]
        fake_llm.responses[2].tool_calls[0]["args"]["updates"][0]["task_id"] = real_id

        result_turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(content="Touch the task")]},
            config=thread_config,
        )

        tool_msg = _find_tool_message(result_turn2["messages"], "call_update_nostatus")
        assert tool_msg.status == "error", (
            f"task_id without a status must be rejected. "
            f"Got status={tool_msg.status!r} content={tool_msg.content!r}"
        )
        assert result_turn2["todos"][0]["status"] == "in_progress"

    async def test_update_tasks_rejects_empty_updates_list(
        self, thread_config, in_memory_store, memory_saver
    ):
        """An empty batch changes nothing, so it must not be reported as an update."""
        todo_tools = create_todo_tools(source="test")
        tool_registry = {t.name: t for t in todo_tools}

        fake_llm = BindableToolsFakeModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_update_empty",
                            "name": "update_tasks",
                            "args": {"updates": []},
                            "type": "tool_call",
                        }
                    ],
                ),
                AIMessage(content="Acknowledged."),
            ]
        )

        graph = build_gaia_test_graph(
            fake_llm=fake_llm,
            tool_registry=tool_registry,
            checkpointer=memory_saver,
            store=in_memory_store,
        )

        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="Update nothing")]},
            config=thread_config,
        )

        tool_msg = _find_tool_message(result["messages"], "call_update_empty")
        assert tool_msg.status == "error", (
            f"An empty updates list must be rejected rather than reported as a change. "
            f"Got status={tool_msg.status!r} content={tool_msg.content!r}"
        )

    async def test_todo_tool_names_match_registry_constants(self):
        """TODO_TOOL_NAMES (used by middleware to detect todo tools) must match the names create_todo_tools() actually creates."""
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
        """Exercises create_todo_pre_model_hook through the real graph wiring (create_agent -> acall_model -> execute_hooks), not by calling the hook directly."""
        from typing import Any

        from langchain_core.language_models.fake_chat_models import (
            FakeMessagesListChatModel,
        )
        from langchain_core.messages import BaseMessage
        from langchain_core.outputs import ChatResult

        captured_inputs: list[list[BaseMessage]] = []

        class CapturingFakeModel(FakeMessagesListChatModel):
            """Fake LLM that records the messages list on every invocation."""

            def bind_tools(self, tools: Any, **kwargs: Any) -> "CapturingFakeModel":
                return self

            def _generate(
                self,
                messages: list[BaseMessage],
                stop: list[str] | None = None,
                run_manager: Any = None,
                **kwargs: Any,
            ) -> ChatResult:
                captured_inputs.append(list(messages))
                return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

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
        from app.override.langgraph_bigtool.create_agent import (
            AgentConfig,
            HookConfig,
            ToolRetrievalConfig,
            create_agent,
        )

        pre_model_hooks: list[HookType] = [
            cast(HookType, filter_messages_node),
            cast(HookType, manage_system_prompts_node),
            cast(HookType, todo_hooks[0]),
        ]

        builder = create_agent(
            llm=fake_llm,
            tool_registry=tool_registry,
            tools_config=ToolRetrievalConfig(
                disable_retrieve_tools=True,
                initial_tool_ids=list(tool_registry.keys()),
            ),
            hooks_config=HookConfig(pre_model_hooks=pre_model_hooks),
            agent_config=AgentConfig(agent_name="test_agent"),
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
        system_messages_seen = [m for m in messages_seen_by_model if isinstance(m, SystemMessage)]
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
