"""
Agent task management tools using InjectedState.

Three tools for agent self-organization during complex multi-step work:
- plan_tasks: Create initial task list
- mark_task: Update one or more task statuses in a single call
- add_task: Add newly discovered tasks

Tools read/write the `todos` channel in graph state directly via
InjectedState and Command(update=...). No middleware, no markers,
no class — just pure functions with closures over `source`.

Streaming: Each mutation emits a `todo_progress` event via
get_stream_writer() so the frontend renders progress in real-time.

Pre-model hook: `create_todo_pre_model_hook()` injects current task
context into the latest non-memory SystemMessage before each LLM call.
"""

from datetime import datetime, timezone
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast
from uuid import uuid4

from app.agents.prompts.todo_prompts import (
    ADD_TASK_DESCRIPTION,
    MARK_TASK_DESCRIPTION,
    PLAN_TASKS_DESCRIPTION,
    TODO_SYSTEM_PROMPT,
)
from app.config.loggers import app_logger as logger
from langchain.tools import InjectedToolCallId
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import InjectedState
from langgraph.store.base import BaseStore
from langgraph.types import Command
from langgraph_bigtool.graph import State
from typing_extensions import TypedDict


class Todo(TypedDict):
    """A single todo item."""

    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
    created_at: str


class TaskInput(TypedDict):
    """Input schema for plan_tasks."""

    content: str


class TaskUpdate(TypedDict):
    """Input schema for a single task status update."""

    task_id: str
    status: Literal["in_progress", "completed", "cancelled"]


def _emit_todo_progress(todos: list[Todo], source: str) -> None:
    """Emit a todo_progress event via LangGraph stream_writer."""
    payload = {
        "todo_progress": {
            "todos": [
                {"id": t["id"], "content": t["content"], "status": t["status"]}
                for t in todos
            ],
            "source": source,
        }
    }
    try:
        writer = get_stream_writer()
        writer(payload)
    except Exception as e:
        logger.warning(f"Stream writer not available for todo_progress: {e}")


def _format_todos(todos: list[Todo]) -> str:
    """Format todos for context injection."""
    if not todos:
        return ""

    lines = ["## Current Tasks"]
    for i, todo in enumerate(todos, 1):
        icon = {
            "completed": "\u2713",
            "in_progress": "\u2192",
            "cancelled": "\u2717",
            "pending": " ",
        }.get(todo["status"], " ")
        lines.append(f"[{icon}] {i}. ({todo['id']}) {todo['content']}")

    return "\n".join(lines)


def create_todo_tools(source: str = "executor") -> list[BaseTool]:
    """Create plan_tasks, mark_task, add_task tools with `source` baked in.

    Each tool reads current todos via InjectedState("todos"), mutates,
    streams progress, and returns Command(update={"todos": ...}).

    Args:
        source: Identifier for todo_progress events (e.g. "executor", "gmail")

    Returns:
        List of three BaseTool instances
    """

    # TODO: Remove these tool calls from the conversation history, we are tracking
    # the tasks in state and these tool calls are just for updating the state.
    # We should not be adding these tool calls to the conversation history.

    @tool(description=PLAN_TASKS_DESCRIPTION)
    async def plan_tasks(
        tasks: list[TaskInput],
        tool_call_id: Annotated[str, InjectedToolCallId],
        todos: Annotated[list, InjectedState("todos")],
    ) -> Command[Any]:
        """Create a task plan for multi-step work."""
        now = datetime.now(timezone.utc).isoformat()
        new_todos: list[Todo] = []

        for i, task in enumerate(tasks):
            new_todos.append(
                Todo(
                    id=str(uuid4())[:8],
                    content=task["content"],
                    status="in_progress" if i == 0 else "pending",
                    created_at=now,
                )
            )

        _emit_todo_progress(new_todos, source)

        first_task = new_todos[0]["content"] if new_todos else "none"
        return Command(
            update={
                "todos": new_todos,
                "messages": [
                    ToolMessage(
                        content=f"Created plan with {len(new_todos)} tasks. Starting: {first_task}",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    @tool(description=MARK_TASK_DESCRIPTION)
    async def mark_task(
        updates: list[TaskUpdate],
        tool_call_id: Annotated[str, InjectedToolCallId],
        todos: Annotated[list, InjectedState("todos")],
    ) -> Command[Any]:
        """Update one or more task statuses."""
        updated_todos: list[Todo] = [dict(t) for t in todos]  # type: ignore[misc]
        todo_map = {t["id"]: t for t in updated_todos}

        for entry in updates:
            tid = entry["task_id"]
            if tid in todo_map:
                todo_map[tid]["status"] = entry["status"]

        _emit_todo_progress(updated_todos, source)

        summary = ", ".join(f"{u['task_id']}\u2192{u['status']}" for u in updates)
        return Command(
            update={
                "todos": updated_todos,
                "messages": [
                    ToolMessage(
                        content=f"Updated: {summary}",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    @tool(description=ADD_TASK_DESCRIPTION)
    async def add_task(
        content: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
        todos: Annotated[list, InjectedState("todos")],
    ) -> Command[Any]:
        """Add a new task to the plan."""
        now = datetime.now(timezone.utc).isoformat()
        new_todo = Todo(
            id=str(uuid4())[:8],
            content=content,
            status="pending",
            created_at=now,
        )
        updated_todos = list(todos) + [new_todo]

        _emit_todo_progress(updated_todos, source)

        return Command(
            update={
                "todos": updated_todos,
                "messages": [
                    ToolMessage(
                        content=f"Added task: {content}",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    return [plan_tasks, mark_task, add_task]


def create_todo_pre_model_hook(
    source: str = "executor",
) -> Callable[[State, RunnableConfig, BaseStore], State]:
    """Create a pre-model hook that injects task context into system messages.

    Runs after manage_system_prompts_node. Reads todos from graph state
    and appends TODO_SYSTEM_PROMPT + formatted task list to the latest
    non-memory SystemMessage.

    Args:
        source: Identifier for logging (not used in hook logic)

    Returns:
        Hook function with signature (State, RunnableConfig, BaseStore) -> State
    """

    def todo_pre_model_hook(
        state: State, config: RunnableConfig, store: BaseStore
    ) -> State:
        todos = state.get("todos", [])

        messages = list(state.get("messages", []))
        if not messages:
            return state

        # Find the latest non-memory system message
        latest_sys_idx = None
        for idx, msg in enumerate(messages):
            if isinstance(msg, SystemMessage):
                extra = msg.model_extra or {}
                is_memory = msg.additional_kwargs.get(
                    "memory_message", False
                ) or extra.get("memory_message", False)
                if not is_memory:
                    latest_sys_idx = idx

        if latest_sys_idx is None:
            return state

        # Build todo context to append
        parts = [TODO_SYSTEM_PROMPT]
        todo_context = _format_todos(todos) if todos else ""
        if todo_context:
            parts.append(todo_context)
        suffix = "\n\n".join(parts)

        # Append to existing system message content
        sys_msg = messages[latest_sys_idx]
        base = sys_msg.content or ""
        new_content = f"{base}\n\n{suffix}" if base else suffix

        messages[latest_sys_idx] = SystemMessage(
            content=new_content,
            additional_kwargs=sys_msg.additional_kwargs,
        )

        return cast(State, {**state, "messages": messages})

    return todo_pre_model_hook
